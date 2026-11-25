from datetime import timedelta
from sqlalchemy import select
from app.bus import MemoryBus, envelope
from app.db import Session, configs, get_config, save_config
from app.models import Run, Execution, Event, now
from app.runtime import WorkflowEngine, StaffAgent
from app.validation import validate_workflow

def create_run(retries=0):
    wf=get_config('workflow','WF-001'); agents={a['id']:a for a in configs('agent')}
    for a in agents.values(): a['retries']=retries
    with Session.begin() as s: s.add(Run(id='run-test',workflow_id='WF-001',snapshot={'workflow':wf,'agents':agents}))
    bus=MemoryBus(); engine=WorkflowEngine(bus); engine.tick()
    return engine,bus

def finish(engine,bus,status='COMPLETED',context=None):
    topic,command=bus.messages[-1]
    exid=command['payload']['execution_id']
    with Session.begin() as s:
        ex=s.get(Execution,exid); ex.status=status; ex.finished=now(); ex.result={'context':context or {},'error':{'code':'INJECTED_FAILURE','skill':'data-preparation@1.0.0'}}
    msg=envelope('WF-001','run-test',command['agent_id'],status,{'execution_id':exid},source=command['agent_id'],target='engine')
    topic=f"ai-agent/WF-001/{command['agent_id']}/"+('result' if status=='COMPLETED' else 'error')
    engine.receive(topic,msg)
    return topic,msg

def test_engine_alone_authorizes_order_and_completes():
    engine,bus=create_run()
    assert bus.messages[-1][1]['agent_id']=='BOT-001'
    finish(engine,bus); engine.tick()
    assert bus.messages[-1][1]['agent_id']=='BOT-002'
    finish(engine,bus); engine.tick()
    assert bus.messages[-1][1]['agent_id']=='BOT-003'
    finish(engine,bus)
    with Session() as s: assert s.get(Run,'run-test').status=='COMPLETED'

def test_failed_skill_prevents_downstream():
    engine,bus=create_run(); finish(engine,bus,'FAILED'); engine.tick()
    assert all(m['agent_id']=='BOT-001' for topic,m in bus.messages if topic.endswith('/command'))
    with Session() as s:
        run=s.get(Run,'run-test'); assert run.status=='FAILED'; assert run.error['skill']=='data-preparation@1.0.0'

def test_duplicate_result_cannot_skip_node():
    engine,bus=create_run(); topic,msg=finish(engine,bus)
    engine.receive(topic,msg); engine.tick()
    with Session() as s: assert s.get(Run,'run-test').current=='BOT-002'

def test_stale_result_is_rejected():
    engine,bus=create_run(); topic,command=bus.messages[-1]
    msg=envelope('WF-001','run-test','BOT-003','COMPLETED',{'execution_id':command['payload']['execution_id']},source='BOT-003')
    engine.receive('ai-agent/WF-001/BOT-003/result',msg)
    with Session() as s:
        assert s.get(Run,'run-test').current=='BOT-001'
        assert s.get(Event,msg['message_id']).processing=='STALE'

def test_retry_creates_distinct_attempt():
    engine,bus=create_run(retries=1); first=bus.messages[-1][1]['payload']['execution_id']
    finish(engine,bus,'FAILED'); engine.tick()
    command=bus.messages[-1][1]
    assert command['agent_id']=='BOT-001' and command['payload']['attempt']==1
    assert command['payload']['execution_id']!=first

def test_duplicate_start_claimed_once(monkeypatch):
    engine,bus=create_run(); calls=[]
    class Thread:
        def __init__(self,target,args,daemon): self.args=args
        def start(self): calls.append(self.args)
    monkeypatch.setattr('app.runtime.threading.Thread',Thread)
    worker=StaffAgent('BOT-001',bus); topic,msg=bus.messages[-1]
    worker.receive(topic,msg); worker.receive(topic,msg)
    assert len(calls)==1

def test_offline_and_invalid_graph_block_execution():
    wf=get_config('workflow','WF-001')
    assert any('OFFLINE' in e for e in validate_workflow(wf)['errors'])
    wf['nodes']=['START','MANAGER','BOT-001','BOT-001','FINAL']
    errors=validate_workflow(wf)['errors']
    assert any('Duplicate' in e for e in errors)
    assert any('Before/After' in e for e in errors)

def test_lost_worker_fails_without_unsafe_retry():
    engine,bus=create_run(retries=3)
    with Session.begin() as s:
        ex=s.get(Execution,bus.messages[-1][1]['payload']['execution_id']); ex.status='RUNNING'; ex.started=now()-timedelta(hours=1)
    engine.tick()
    with Session() as s: assert s.get(Run,'run-test').error['code']=='WORKER_LOST'
    assert len([m for topic,m in bus.messages if topic.endswith('/command')])==1

def test_missing_ack_times_out():
    engine,bus=create_run()
    with Session.begin() as s:
        ex=s.get(Execution,bus.messages[-1][1]['payload']['execution_id']); ex.started=now()-timedelta(hours=1)
    engine.tick(); engine.tick()
    topic,msg=bus.messages[-1]; engine.receive(topic,msg)
    with Session() as s:
        assert s.get(Run,'run-test').status=='FAILED'
        assert s.get(Run,'run-test').error['code']=='ACK_TIMEOUT'
