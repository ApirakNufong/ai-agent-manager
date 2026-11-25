"""Acceptance runner against the real Docker stack; no mocked broker or readers."""
import os
import time
import json
import urllib.request

base=os.getenv('BASE_URL','http://localhost:8080')+'/api'
token=os.getenv('API_TOKEN','')

def call(path,method='GET'):
    request=urllib.request.Request(base+path,data=b'{}' if method=='POST' else None,method=method,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=120) as response: return json.load(response)

def wait(id):
    for _ in range(180):
        detail=call('/runs/'+id)
        if detail['run']['status'] in ('COMPLETED','FAILED','STOPPED'):
            assert detail['run']['status']=='COMPLETED',detail
            return detail
        time.sleep(1)
    raise TimeoutError('Run did not complete')

for source in call('/config/source'):
    result=call('/sources/'+source['id']+'/test','POST')
    assert result['test_status']=='PASS',result
for skill in call('/config/skill'):
    result=call('/skills/'+skill['id']+'/test','POST')
    assert result['status']=='PASS',result
    call('/skills/'+skill['id']+'/publish','POST')
for agent in call('/config/agent'):
    result=call('/agents/'+agent['id']+'/test','POST')
    if 'run_id' in result: wait(result['run_id'])
result=call('/workflows/WF-001/test','POST'); wait(result['run_id'])
validation=call('/workflows/WF-001/validate','POST')
assert validation['status']=='PASS',validation
result=call('/workflows/WF-001/run','POST'); detail=wait(result['run_id'])
assert [e['agent_id'] for e in detail['executions']]==['BOT-001','BOT-002','BOT-003']
assert detail['run']['context']['metrics']['yield_rate']==96.05
assert detail['datasets'] and all(d['lineage'] for d in detail['datasets'])
events=call('/events?run_id='+result['run_id'])
assert any(e['body']['event']=='SKILL_COMPLETED' for e in events)
assert detail['run']['context']['report_url']
print(json.dumps({'acceptance':'PASS','run_id':result['run_id'],'yield':96.05,'mqtt_events':len(events),'datasets':len(detail['datasets'])},indent=2))
