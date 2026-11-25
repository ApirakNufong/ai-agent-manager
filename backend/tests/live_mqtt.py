"""Real Mosca integration test. MySQL is explicitly replaced by an input fixture.
Run with a Mosca instance on MQTT_HOST and its MQTT_PASSWORD in the environment.
This does not count as MySQL or Docker acceptance verification.
"""
import os
import sys
import subprocess
import tempfile
import time
from pathlib import Path

root=Path(tempfile.mkdtemp(prefix='agent-live-mqtt-'))
os.environ['DATA_DIR']=str(root)
os.environ['DATABASE_URL']='sqlite:///'+str(root/'test.db')
os.environ['SKILLS_DIR']=str(Path(__file__).resolve().parents[1]/'skills')
os.environ['MQTT_HOST']=os.getenv('MQTT_HOST','127.0.0.1')

from app.seed import seed,fixture_context
from app.db import Session,configs,get_config,save_config
from app.models import Run,Execution,Event,Heartbeat,Audit,now,uid
from app.bus import MqttBus
from sqlalchemy import select

seed()
a=get_config('agent','BOT-001'); a['skills']=['excel-reader@1.0.0']; a['data_sources']=['excel-targets']; a['retries']=0
save_config('agent',a)
processes=[]
duplicates=set()
def repeat_command(topic,message):
    if topic.endswith('/command') and message['event']=='START' and message['payload']['execution_id'] not in duplicates:
        duplicates.add(message['payload']['execution_id'])
        observer.publish(topic,message)
observer=MqttBus('engine',handler=repeat_command,client_id='integration-observer')

def run_pipeline():
    id=uid(); wf=get_config('workflow','WF-001')
    with Session.begin() as s: s.add(Run(id=id,workflow_id=wf['id'],snapshot={'workflow':wf,'agents':{a['id']:a for a in configs('agent')}},context=fixture_context(id)))
    for _ in range(120):
        time.sleep(1)
        with Session() as s:
            run=s.get(Run,id)
            if run.status in ('COMPLETED','FAILED'):
                executions=list(s.scalars(select(Execution).where(Execution.run_id==id).order_by(Execution.started)))
                return run,executions
    raise TimeoutError('Pipeline did not terminate')

try:
    observer.start()
    for identity in ('engine','manager','BOT-001','BOT-002','BOT-003'):
        processes.append(subprocess.Popen([sys.executable,'-m','app.runtime',identity],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE))
    for _ in range(30):
        time.sleep(1)
        with Session() as s:
            if len(list(s.scalars(select(Heartbeat))))>=5: break
    else: raise AssertionError('All runtimes must report heartbeat')
    run,executions=run_pipeline()
    assert run.status=='COMPLETED',(run.status,run.error)
    assert [e.agent_id for e in executions]==['BOT-001','BOT-002','BOT-003']
    assert run.context['metrics']['yield_rate']==96.05
    assert len(executions)==3
    with Session() as s:
        events=list(s.scalars(select(Event).where(Event.run_id==run.id)))
        assert sum(e.body['event']=='SKILL_COMPLETED' for e in events)==7
        assert s.scalar(select(Audit).where(Audit.action=='agent.duplicate_start_ignored')) is not None
    # Real connector failure must stop before BOT-002.
    src=get_config('source','excel-targets'); src['file']='missing.xlsx'; save_config('source',src)
    failed,failed_executions=run_pipeline()
    assert failed.status=='FAILED'
    assert len(failed_executions)==1 and failed_executions[0].agent_id=='BOT-001'
    assert failed.error['skill']=='excel-reader@1.0.0'
    print('PASS: real Mosca / engine / manager / three subprocess workers / duplicate START delivery / Excel / deterministic analysis / report / failure propagation')
    print('MySQL reader and Docker deployment are not exercised by this test.')
finally:
    observer.stop()
    for p in processes: p.terminate()
    for p in processes:
        try: p.wait(timeout=10)
        except subprocess.TimeoutExpired: p.kill()
