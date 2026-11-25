from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def test_state_and_validation():
    state=client.get('/api/state')
    assert state.status_code==200
    assert len(state.json()['agents'])==4
    result=client.post('/api/workflows/WF-001/validate').json()
    assert result['status']=='FAIL'
    assert client.post('/api/workflows/WF-001/run').status_code==422

def test_configuration_invalidates_test():
    agent=client.get('/api/config/agent').json()[1]
    agent['test_status']='PASS'
    response=client.put('/api/config/agent/'+agent['id'],json=agent)
    assert response.status_code==200
    assert response.json()['test_status']=='UNTESTED'

def test_skill_test_then_approval():
    assert client.post('/api/skills/data-analysis@1.0.0/publish').status_code==400
    result=client.post('/api/skills/data-analysis@1.0.0/test').json()
    assert result['status']=='PASS'
    assert client.post('/api/skills/data-analysis@1.0.0/publish').json()['approved'] is True

def test_assigned_skill_cannot_be_deleted():
    assert client.delete('/api/config/skill/data-analysis@1.0.0').status_code==400

def test_upload_rejects_code_execution():
    raw='---\n{"id":"evil","version":"1.0.0","handler":"exec","input_schema":{},"output_schema":{}}\n---\nExecute arbitrary code.'
    response=client.post('/api/skills/upload',files={'file':('SKILL.md',raw)})
    assert response.status_code==400

def test_source_change_invalidates_bot_and_workflow_tests():
    from app.db import get_config,save_config
    a=get_config('agent','BOT-001'); a['test_status']='PASS'; save_config('agent',a,'tested')
    w=get_config('workflow','WF-001'); w['test_status']='PASS'; save_config('workflow',w,'tested')
    src=get_config('source','mysql-production'); src['maximum_rows']=500
    assert client.put('/api/config/source/mysql-production',json=src).status_code==200
    assert get_config('agent','BOT-001')['test_status']=='UNTESTED'
    assert get_config('agent','BOT-001')['version']==a['version']+1
    assert get_config('workflow','WF-001')['test_status']=='UNTESTED'

def test_create_instruction_and_immutable_version():
    from uuid import uuid4
    meta={'id':'instruction-'+uuid4().hex,'version':'1.0.0','handler':'instruction','type':'instruction','input_schema':{'type':'object'},'output_schema':{'type':'object'},'config':{'text':'Check quality'},'instructions':'Quality instructions'}
    assert client.post('/api/skills/create',json=meta).status_code==200
    assert client.post('/api/skills/create',json=meta).status_code==400
    result=client.post('/api/skills/'+meta['id']+'@1.0.0/test').json()
    assert result['status']=='PASS' and result['result']['instructions']=='Check quality'

def test_excel_upload_and_inspect():
    from app.config import DATA
    response=client.post('/api/sources/upload-excel',files={'file':('targets.xlsx',(DATA/'targets.xlsx').read_bytes())})
    assert response.status_code==200
    id=response.json()['id']
    inspected=client.get('/api/sources/'+id+'/inspect').json()
    assert inspected['worksheets'][0]['name']=='Targets'

def test_api_token_is_enforced(monkeypatch):
    monkeypatch.setattr('app.config.API_TOKEN','unit-test-only')
    assert client.get('/api/state').status_code==401
    assert client.get('/api/state',headers={'Authorization':'Bearer unit-test-only'}).status_code==200
