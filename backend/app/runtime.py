"""Separate engine, manager and staff processes communicating exclusively via MQTT."""
import json
import logging
import subprocess
import sys
import time
import threading
from datetime import datetime, timedelta
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from jsonschema import validate
from .db import Session, initialize, get_config
from .models import Run, Execution, Event, Heartbeat, Audit, Config, now, uid
from .bus import MqttBus, envelope

log=logging.getLogger(__name__)

def heartbeat(bus, identity):
    with Session.begin() as s:
        hb=s.get(Heartbeat,identity)
        if hb: hb.timestamp=now()
        else: s.add(Heartbeat(id=identity))
    bus.publish(f'ai-agent/system/status',envelope('system','',identity,'HEARTBEAT',source=identity,target='manager'))

class WorkflowEngine:
    def __init__(self,bus): self.bus=bus
    def receive(self,topic,m):
        try:
            with Session.begin() as s:
                s.add(Event(id=m['message_id'],topic=topic,run_id=m['run_id'],body=m))
        except IntegrityError:
            with Session.begin() as s: s.add(Audit(action='mqtt.duplicate_ignored',entity=m['message_id'],new={'run_id':m['run_id'],'topic':topic}))
            return
        if m['event'] not in ('COMPLETED','FAILED','TIMEOUT'): return
        if not topic.endswith('/result') and not topic.endswith('/error'): return
        with Session.begin() as s:
            event=s.get(Event,m['message_id'])
            run=s.scalar(select(Run).where(Run.id==m['run_id']).with_for_update())
            if not run or run.status!='RUNNING' or run.current!=m['agent_id'] or m['source_agent']!=run.current:
                event.processing='STALE'; return
            expected_topic=f'ai-agent/{run.workflow_id}/{run.current}/'+('result' if m['event']=='COMPLETED' else 'error')
            if topic!=expected_topic or m['workflow_id']!=run.workflow_id or m['correlation_id']!=run.id:
                event.processing='REJECTED'; return
            ex=s.get(Execution,m['payload'].get('execution_id',''))
            if not ex or ex.run_id!=run.id or ex.agent_id!=run.current or ex.status not in ('COMPLETED','FAILED','TIMEOUT'):
                event.processing='REJECTED'; return
            latest=s.scalar(select(Execution).where(Execution.run_id==run.id,Execution.agent_id==run.current).order_by(Execution.attempt.desc()))
            if latest.id!=ex.id: event.processing='STALE'; return
            stamp=datetime.fromisoformat(m['timestamp'])
            if stamp.replace(tzinfo=now().tzinfo)<run.started.replace(tzinfo=now().tzinfo): event.processing='STALE'; return
            a=run.snapshot['agents'][run.current]
            if ex.status=='COMPLETED':
                try: validate(ex.result['context'],a['output_schema'])
                except Exception as e:
                    run.status='FAILED'; run.error={'code':'OUTPUT_SCHEMA','agent':run.current,'reason':str(e)}; run.finished=now(); return
                run.context=ex.result['context']
                nodes=run.snapshot['workflow']['nodes']
                run.current=nodes[nodes.index(run.current)+1]
                if run.current=='FINAL':
                    run.status='COMPLETED'; run.finished=now()
                    kind=run.snapshot.get('test'); target=run.snapshot.get('target')
                    if kind in ('agent','workflow'):
                        c=s.get(Config,kind+':'+target)
                        tested_version=run.snapshot['agents'][target]['version'] if kind=='agent' else run.snapshot['workflow']['version']
                        if c and c.body.get('version')==tested_version:
                            c.body={**c.body,'test_status':'PASS','last_test':now().isoformat()}
                            s.add(Audit(action=kind+'.test_passed',entity=target,new={'run_id':run.id}))
            elif ex.attempt>=a['retries']:
                run.status='FAILED'; run.error=ex.result.get('error',{'code':ex.status}); run.finished=now()
                kind=run.snapshot.get('test'); target=run.snapshot.get('target')
                if kind in ('agent','workflow'):
                    c=s.get(Config,kind+':'+target)
                    if c: c.body={**c.body,'test_status':'FAIL','last_test':now().isoformat()}
            event.processing='ACCEPTED'
            terminal=run.status in ('COMPLETED','FAILED')
            notification=envelope(run.workflow_id,run.id,'MANAGER',run.status,{'current':run.current,'error':run.error},target='manager') if terminal else None
        if notification:
            try: self.bus.publish(f"ai-agent/{notification['workflow_id']}/manager/event",notification)
            except ConnectionError: pass
    def tick(self):
        with Session() as s: ids=list(s.scalars(select(Run.id).where(Run.status.in_(['WAITING','RUNNING']))))
        for id in ids:
            dispatch=None; announcements=[]
            with Session.begin() as s:
                run=s.scalar(select(Run).where(Run.id==id).with_for_update())
                if run.status=='WAITING':
                    run.status='RUNNING'; run.current=run.snapshot['workflow']['nodes'][2]
                    announcements.append((f'ai-agent/{run.workflow_id}/manager/event',envelope(run.workflow_id,id,'MANAGER','START',{'trace':run.snapshot['workflow']['nodes']},target='manager')))
                a=run.snapshot['agents'][run.current]
                ex=s.scalar(select(Execution).where(Execution.run_id==id,Execution.agent_id==run.current).order_by(Execution.attempt.desc()))
                if ex and ex.status in ('COMPLETED','FAILED','TIMEOUT'):
                    # Persisted terminal results are replayed after broker/engine restart.
                    dispatch=(f"ai-agent/{run.workflow_id}/{run.current}/"+('result' if ex.status=='COMPLETED' else 'error'),envelope(run.workflow_id,id,run.current,ex.status,{'execution_id':ex.id},source=run.current,target='engine'))
                    if ex.status!='COMPLETED' and ex.attempt<a['retries']:
                        ex=Execution(id=uid(),run_id=id,agent_id=run.current,attempt=ex.attempt+1)
                        s.add(ex); s.flush(); dispatch=None
                if not ex:
                    ex=Execution(id=uid(),run_id=id,agent_id=run.current)
                    s.add(ex); s.flush()
                if ex.status=='WAITING':
                    if now()-ex.started.replace(tzinfo=now().tzinfo)>timedelta(seconds=a['timeout']):
                        ex.status='TIMEOUT'; ex.finished=now(); ex.result={'error':{'code':'ACK_TIMEOUT','agent':run.current,'reason':'No worker acknowledged the command','retry':ex.attempt}}
                    else:
                        dispatch=(f'ai-agent/{run.workflow_id}/{run.current}/command',envelope(run.workflow_id,id,run.current,'START',{'execution_id':ex.id,'attempt':ex.attempt}))
                elif ex.status=='RUNNING' and now()-ex.started.replace(tzinfo=now().tzinfo)>timedelta(seconds=a['timeout']+15):
                    # Do not retry uncertain in-flight work: the worker may be partitioned.
                    run.status='FAILED'; run.finished=now(); run.error={'code':'WORKER_LOST','agent':run.current,'reason':'No terminal result before deadline; manual investigation required'}
            for announcement in announcements:
                try: self.bus.publish(*announcement)
                except ConnectionError: pass
            if dispatch:
                try: self.bus.publish(*dispatch)
                except ConnectionError: pass

class StaffAgent:
    def __init__(self,identity,bus): self.identity,self.bus=identity,bus
    def receive(self,topic,m):
        if m['event']!='START' or m['source_agent']!='engine' or m['target_agent']!=self.identity: return
        exid=m['payload'].get('execution_id','')
        with Session.begin() as s:
            run=s.get(Run,m['run_id']); ex=s.get(Execution,exid)
            if not run or run.status!='RUNNING' or run.current!=self.identity or not ex or ex.run_id!=run.id or ex.agent_id!=self.identity: return
            if datetime.fromisoformat(m['timestamp']).replace(tzinfo=now().tzinfo)<run.started.replace(tzinfo=now().tzinfo): return
            claimed=s.execute(update(Execution).where(Execution.id==exid,Execution.status=='WAITING').values(status='RUNNING',started=now())).rowcount
            timeout=run.snapshot['agents'][self.identity]['timeout']
        if not claimed:
            with Session.begin() as s: s.add(Audit(action='agent.duplicate_start_ignored',entity=exid,new={'message_id':m['message_id'],'run_id':m['run_id']}))
            return
        threading.Thread(target=self.work,args=(m,exid,timeout),daemon=True).start()
    def work(self,m,exid,timeout):
        prefix=f"ai-agent/{m['workflow_id']}/{self.identity}"
        try:
            self.bus.publish(prefix+'/status',envelope(m['workflow_id'],m['run_id'],self.identity,'ACK',{'execution_id':exid},source=self.identity,target='engine'))
            self.bus.publish(prefix+'/status',envelope(m['workflow_id'],m['run_id'],self.identity,'START',{'execution_id':exid},source=self.identity,target='manager'))
            subprocess.run([sys.executable,'-m','app.task',exid],timeout=timeout,check=True)
        except Exception as e:
            with Session.begin() as s:
                ex=s.get(Execution,exid)
                if ex.status=='RUNNING':
                    ex.status='TIMEOUT' if isinstance(e,subprocess.TimeoutExpired) else 'FAILED'; ex.finished=now()
                    ex.result={'error':{'agent':self.identity,'code':ex.status,'reason':str(e),'timestamp':now().isoformat()}}
        with Session() as s: ex=s.get(Execution,exid)
        try: self.bus.publish(prefix+('/result' if ex.status=='COMPLETED' else '/error'),envelope(m['workflow_id'],m['run_id'],self.identity,ex.status,{'execution_id':exid},source=self.identity,target='engine'))
        except ConnectionError: log.warning('Result retained in database for engine recovery')

class ManagerAgent:
    def receive(self,topic,m):
        if m['event'] in ('FAILED','TIMEOUT','SKILL_FAILED','SKILL_TIMEOUT'):
            log.error(json.dumps({'manager':'MANAGER','workflow':m['workflow_id'],'run':m['run_id'],'agent':m['agent_id'],'event':m['event'],'details':m['payload']}))

def main():
    initialize()
    identity=sys.argv[1]
    bus=MqttBus(identity)
    service=WorkflowEngine(bus) if identity=='engine' else ManagerAgent() if identity=='manager' else StaffAgent(identity,bus)
    bus.handler=service.receive
    bus.start()
    last=0
    try:
        while True:
            if bus.connected:
                if time.time()-last>5: heartbeat(bus,'MANAGER' if identity=='manager' else identity); last=time.time()
                if identity=='engine': service.tick()
            time.sleep(1)
    finally: bus.stop()

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    main()
