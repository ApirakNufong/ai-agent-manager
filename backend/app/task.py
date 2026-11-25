import sys
import time
from jsonschema import validate
from .db import Session
from .models import Execution, Run, now
from .skills import execute_skill, SOURCE_SNAPSHOT
from .bus import MqttBus, envelope

def execute(exid):
    with Session() as s:
        ex=s.get(Execution,exid); run=s.get(Run,ex.run_id)
        agent=run.snapshot['agents'][ex.agent_id]; context=run.context.copy()
    SOURCE_SNAPSHOT.set(run.snapshot.get('sources',{}))
    # Skill events are published using the same staff credential, with a unique client ID.
    bus=MqttBus(ex.agent_id,client_id=ex.agent_id+'-task-'+exid)
    bus.start()
    for _ in range(50):
        if bus.connected: break
        time.sleep(.1)
    results=[]; current='input'
    def emit(event,ref,payload):
        bus.publish(f'ai-agent/{run.workflow_id}/{ex.agent_id}/skill/{ref}/status',envelope(run.workflow_id,run.id,ex.agent_id,event,payload,source=ex.agent_id,target='manager'))
    try:
        validate(context,agent['input_schema'])
        for ref in agent['skills']:
            current=ref; start=now()
            with Session.begin() as s:
                running=s.get(Execution,exid)
                if running.status!='RUNNING': raise RuntimeError('Execution is no longer authorized')
                running.result={'current_skill':ref,'skills':results.copy()}
            emit('SKILL_START',ref,{'skill':ref,'execution_id':exid})
            context=execute_skill(ref,context,run.id)
            results.append({'skill':ref,'status':'COMPLETED','started':start.isoformat(),'finished':now().isoformat()})
            emit('SKILL_COMPLETED',ref,{'skill':ref,'execution_id':exid})
        validate(context,agent['output_schema'])
        status='COMPLETED'; result={'context':context,'skills':results}
    except Exception as e:
        status='FAILED'; result={'skills':results,'error':{'agent':ex.agent_id,'skill':current,'step':'execute','code':type(e).__name__,'reason':str(e),'retry':ex.attempt,'timestamp':now().isoformat()}}
        try: emit('SKILL_FAILED',current,result['error'])
        except Exception: pass
    finally: bus.stop()
    with Session.begin() as s:
        ex=s.get(Execution,exid)
        if ex.status=='RUNNING': ex.status=status; ex.result=result; ex.finished=now()

if __name__=='__main__': execute(sys.argv[1])
