from datetime import timedelta
from jsonschema import Draft202012Validator
from .db import configs, get_config, Session
from .models import Heartbeat, now
from .skills import load_skill

def validate_workflow(workflow, live=True, require_tests=True):
    errors=[]
    nodes=workflow.get('nodes',[])
    agents={a['id']:a for a in configs('agent')}
    if not nodes or nodes[0]!='START': errors.append('START must be the first node')
    if not nodes or nodes[-1]!='FINAL': errors.append('FINAL must be reachable at the end')
    if len(nodes)!=len(set(nodes)): errors.append('Duplicate nodes or circular dependency')
    selected=[agents[n] for n in nodes if n in agents]
    if sum(a['role']=='manager' for a in selected)!=1: errors.append('Exactly one Manager is required')
    if len(nodes)<4: errors.append('At least one Staff BOT is required')
    if len(nodes)>1 and (nodes[1] not in agents or agents[nodes[1]]['role']!='manager'): errors.append('Manager must follow START')
    for i,n in enumerate(nodes[1:-1],1):
        a=agents.get(n)
        if not a: errors.append(f'{n}: missing agent'); continue
        if not a['enabled']: errors.append(f'{n}: disabled')
        if a['before_node']!=nodes[i-1] or a['after_node']!=nodes[i+1]: errors.append(f'{n}: Before/After relationships do not match the workflow')
        if a['action']!='execute_skills': errors.append(f'{n}: unsupported action')
        if a['mqtt_topic']!='ai-agent/{workflow_id}/{agent_id}': errors.append(f'{n}: MQTT topic must use the approved namespace')
        try:
            Draft202012Validator.check_schema(a['input_schema']); Draft202012Validator.check_schema(a['output_schema'])
        except Exception: errors.append(f'{n}: invalid input/output schema')
        if a['role']=='staff' and not a['skills']: errors.append(f'{n}: no skills assigned')
        if require_tests and a['test_status']!='PASS': errors.append(f'{n}: BOT test required')
        seen=set()
        for ref in a['skills']:
            skill=get_config('skill',ref)
            if not skill or not skill['enabled']: errors.append(f'{n}: {ref} missing or disabled'); continue
            if require_tests and (skill['test_status']!='PASS' or not skill.get('approved')): errors.append(f'{n}: {ref} requires testing and approval')
            if not set(skill.get('dependencies',[])).issubset(seen): errors.append(f'{ref}: dependencies must precede the skill')
            try: load_skill(ref)
            except Exception as e: errors.append(f'{ref}: {e}')
            seen.add(ref)
        for source in a['data_sources']:
            src=get_config('source',source)
            if not src or not src.get('enabled') or src.get('test_status')!='PASS': errors.append(f'{n}: source {source} unavailable or untested')
        if live and not workflow.get('allow_offline'):
            with Session() as s: hb=s.get(Heartbeat,n)
            if not hb or hb.timestamp.replace(tzinfo=now().tzinfo)<now()-timedelta(seconds=20): errors.append(f'{n}: OFFLINE')
    return {'status':'FAIL' if errors else 'PASS','errors':errors,'trace':nodes}
