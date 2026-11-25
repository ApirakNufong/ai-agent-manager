import json
import pandas as pd
import yaml
from .config import DATA, SKILLS
from .db import initialize, get_config, save_config
from .schemas import Agent, Workflow
from .skills import store_dataset

STANDARD = ['mysql-reader','excel-reader','data-preparation','data-analysis','statistical-analysis','abnormality-detector','data-visualization','production-report-generator']

def fixture_context(run='fixture'):
    actual = pd.DataFrame([{'production_date':f'2026-11-{i:02d}','product_code':'PCB-A','input_qty':1000,'good_output':950+i,'ng':50-i} for i in range(1,21)])
    targets = pd.DataFrame([{'production_date':f'2026-11-{i:02d}','product_code':'PCB-A','target':98.0} for i in range(1,21)])
    return {'actual_dataset':store_dataset(run,actual,{'type':'test','name':'fixture'},[]),'target_dataset':store_dataset(run,targets,{'type':'test','name':'fixture'},[])}

def seed():
    initialize()
    settings = {'data-preparation':{'join_keys':['production_date','product_code']}, 'data-analysis':{'yield_numerator':'good_output','yield_denominator':'input_qty'},'abnormality-detector':{'z_threshold':3}}
    required = {'data-preparation':['actual_dataset','target_dataset'],'data-analysis':['dataset_id'],'statistical-analysis':['dataset_id'],'abnormality-detector':['dataset_id'],'data-visualization':['dataset_id'],'production-report-generator':['dataset_id']}
    for name in STANDARD:
        ref = name+'@1.0.0'
        if not get_config('skill',ref):
            save_config('skill',{'id':ref,'name':name,'type':'connector' if 'reader' in name else 'script','version':'1.0.0','enabled':True,'approved':False,'test_status':'UNTESTED','dependencies':[]},'seeded')
    agents = [Agent(id='MANAGER',name='Workflow supervisor',role='manager',before_node='START',after_node='BOT-001'),Agent(id='BOT-001',name='Data collector',before_node='MANAGER',after_node='BOT-002',skills=[x+'@1.0.0' for x in STANDARD[:2]],data_sources=['mysql-production','excel-targets']),Agent(id='BOT-002',name='Production analyst',before_node='BOT-001',after_node='BOT-003',skills=[x+'@1.0.0' for x in STANDARD[2:6]]),Agent(id='BOT-003',name='Report publisher',before_node='BOT-002',after_node='FINAL',skills=[x+'@1.0.0' for x in STANDARD[6:]])]
    for agent in agents:
        if not get_config('agent',agent.id): save_config('agent',agent.model_dump(),'seeded')
    workflow = Workflow(id='WF-001',name='Production intelligence',nodes=['START','MANAGER','BOT-001','BOT-002','BOT-003','FINAL'])
    if not get_config('workflow',workflow.id): save_config('workflow',workflow.model_dump(),'seeded')
    for src in [{'id':'mysql-production','name':'Production database','type':'mysql','enabled':True,'allowed_tables':['production'],'maximum_rows':10000,'authentication_reference':'MYSQL_*','read_only':True,'test_status':'UNTESTED'}, {'id':'excel-targets','name':'Production targets','type':'excel','enabled':True,'file':'targets.xlsx','maximum_size':10485760,'test_status':'UNTESTED'}]:
        if not get_config('source',src['id']): save_config('source',src,'seeded')
    if not (DATA/'targets.xlsx').exists():
        pd.DataFrame([{'production_date':f'2026-11-{i:02d}','product_code':'PCB-A','target':98.0} for i in range(1,21)]).to_excel(DATA/'targets.xlsx',sheet_name='Targets',index=False)

if __name__ == '__main__': seed()
