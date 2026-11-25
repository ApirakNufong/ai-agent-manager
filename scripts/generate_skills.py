"""Generate the checked-in standard declarative packages. Run once during development."""
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]/'backend'/'skills'
names=['mysql-reader','excel-reader','data-preparation','data-analysis','statistical-analysis','abnormality-detector','data-visualization','production-report-generator']
inputs={'data-preparation':['actual_dataset','target_dataset'],'data-analysis':['dataset_id'],'statistical-analysis':['dataset_id'],'abnormality-detector':['dataset_id'],'data-visualization':['dataset_id'],'production-report-generator':['dataset_id']}
outputs={'mysql-reader':['actual_dataset'],'excel-reader':['target_dataset'],'data-preparation':['dataset_id'],'data-analysis':['dataset_id','metrics'],'statistical-analysis':['statistics'],'abnormality-detector':['abnormalities'],'data-visualization':['chart_url'],'production-report-generator':['report_url']}
configs={'data-preparation':{'join_keys':['production_date','product_code']},'data-analysis':{'yield_numerator':'good_output','yield_denominator':'input_qty'},'abnormality-detector':{'z_threshold':3},'mysql-reader':{'source':'mysql-production','table':'production'},'excel-reader':{'source':'excel-targets','sheet':'Targets'}}
for name in names:
    directory=root/name/'1.0.0'
    for sub in ('references','schemas','tests','assets'): (directory/sub).mkdir(parents=True,exist_ok=True)
    meta={'id':name,'version':'1.0.0','type':'connector' if 'reader' in name else 'script','handler':name,'permissions':['data:read','dataset:write'],'dependencies':[],'input_schema':{'type':'object','required':inputs.get(name,[])},'output_schema':{'type':'object','required':outputs[name]},'config':configs.get(name,{})}
    # JSON is a YAML subset, avoiding a generation-time dependency.
    (directory/'SKILL.md').write_text('---\n'+json.dumps(meta,indent=2)+'\n---\n\n# '+name+'\n\nExecute the approved deterministic handler. Preserve dataset lineage. Never start downstream agents. Fail explicitly when required input is missing.\n',encoding='utf-8')
    (directory/'schemas'/'input.json').write_text(json.dumps(meta['input_schema'],indent=2),encoding='utf-8')
    (directory/'schemas'/'output.json').write_text(json.dumps(meta['output_schema'],indent=2),encoding='utf-8')
    (directory/'tests'/'README.md').write_text('Run this skill through Test Center or POST /api/skills/'+name+'@1.0.0/test. Reader tests use actual configured sources; analysis tests use deterministic manufacturing fixtures. Numerical acceptance assertions live in backend/tests/test_skills.py.\n',encoding='utf-8')
    (directory/'references'/'permissions.md').write_text('This package calls an allowlisted server handler. It does not import or execute uploaded code. Source access is restricted to configured MySQL tables or the dataset directory.\n',encoding='utf-8')
print('Generated',len(names),'skill packages')
