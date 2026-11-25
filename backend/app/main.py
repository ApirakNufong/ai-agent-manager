import asyncio
import hashlib
import json
import re
import zipfile
import io
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import timedelta
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy import select
from . import config
from .db import Session, configs, get_config, save_config, serialize
from .models import Run, Execution, Event, Audit, Dataset, Heartbeat, now, uid, Config
from .schemas import Agent, Workflow
from .seed import seed, fixture_context
from .validation import validate_workflow
from .skills import load_skill, execute_skill, confined
from .bus import MqttBus

bus=MqttBus('api')

@asynccontextmanager
async def lifespan(app):
    seed(); bus.start()
    yield
    bus.stop()

app=FastAPI(title='AI Agent Manager',version='1.0.0',lifespan=lifespan)

@app.middleware('http')
async def security(request:Request,call_next):
    if request.url.path!='/api/health' and config.API_TOKEN and request.headers.get('authorization')!='Bearer '+config.API_TOKEN:
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'Authentication required'},status_code=401)
    try: return await call_next(request)
    except (ValueError,KeyError,FileNotFoundError,zipfile.BadZipFile) as e:
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':str(e)},status_code=400)

@app.get('/api/health')
def health():
    with Session() as s: s.execute(select(1))
    return {'backend':'ONLINE','database':'ONLINE','mosca':'ONLINE' if bus.connected else 'OFFLINE'}

def state():
    with Session() as s:
        beats={h.id:('ONLINE' if h.timestamp.replace(tzinfo=now().tzinfo)>now()-timedelta(seconds=20) else 'OFFLINE') for h in s.scalars(select(Heartbeat))}
        runs=[serialize(r) for r in s.scalars(select(Run).order_by(Run.started.desc()).limit(100))]
        active=[serialize(x) for x in s.scalars(select(Execution).where(Execution.status=='RUNNING'))]
    return {'agents':configs('agent'),'skills':configs('skill'),'sources':configs('source'),'workflows':configs('workflow'),'runs':runs,'active_executions':active,'heartbeats':beats,'health':health()}

@app.get('/api/state')
def get_state(): return state()

@app.get('/api/config/{kind}')
def list_config(kind:str): return configs(kind)

@app.put('/api/config/{kind}/{id}')
def put_config(kind:str,id:str,body:dict):
    if kind not in ('agent','workflow','source','skill'): raise HTTPException(404)
    if body.get('id')!=id: raise ValueError('Identity mismatch')
    old=get_config(kind,id)
    if kind=='agent': body=Agent.model_validate(body).model_dump(); body['test_status']='UNTESTED'
    if kind=='workflow': body=Workflow.model_validate(body).model_dump()
    if kind=='source':
        if body.get('type') not in ('mysql','excel','api'): raise ValueError('Unknown data connector')
        if any('password' in k.lower() for k in body): raise ValueError('Use environment authentication references')
        body['test_status']='UNTESTED'
        if body['type']=='mysql': body['read_only']=True
    if kind=='skill':
        load_skill(id)
        body['test_status']=(old or {}).get('test_status','UNTESTED')
        body['approved']=(old or {}).get('approved',False)
    body['version']=old.get('version',1)+1 if old and kind in ('agent','workflow') else body.get('version',1)
    if kind=='workflow': body['test_status']='UNTESTED'
    return save_config(kind,body)

@app.delete('/api/config/{kind}/{id}')
def delete_config(kind:str,id:str):
    if kind=='agent' and any(id in w['nodes'] for w in configs('workflow')): raise ValueError('Remove agent from workflows first')
    if kind=='skill' and any(id in a['skills'] for a in configs('agent')): raise ValueError('Remove skill from agents first')
    if kind=='source' and any(id in a['data_sources'] for a in configs('agent')): raise ValueError('Remove source from agents first')
    with Session.begin() as s:
        c=s.get(Config,kind+':'+id)
        if not c: raise HTTPException(404)
        s.add(Audit(action=kind+'.deleted',entity=id,old=c.body,new={}))
        s.delete(c)
    return {'deleted':id}

@app.post('/api/skills/{ref}/validate')
def skill_validate(ref:str):
    meta,instructions=load_skill(ref)
    return {'status':'PASS','metadata':meta,'instructions':instructions}

def test_context(ref):
    context=fixture_context('test-'+uid())
    if ref.split('@')[0] in ('data-analysis','statistical-analysis','abnormality-detector','data-visualization','production-report-generator'):
        context=execute_skill('data-preparation@1.0.0',context,'test-'+uid())
    if ref.split('@')[0] in ('statistical-analysis','abnormality-detector','data-visualization','production-report-generator'):
        context=execute_skill('data-analysis@1.0.0',context,'test-'+uid())
    return context

@app.post('/api/skills/{ref}/test')
def skill_test(ref:str,body:dict|None=None):
    skill=get_config('skill',ref)
    if not skill: raise HTTPException(404)
    try:
        context=body['input'] if body and 'input' in body else test_context(ref)
        result=execute_skill(ref,context,'test-'+uid())
        skill.update(test_status='PASS',last_error='',last_test=now().isoformat())
        save_config('skill',skill,'tested')
        return {'status':'PASS','result':result,'input_mode':'real source' if 'reader@' in ref else 'deterministic fixture'}
    except Exception as e:
        skill.update(test_status='FAIL',last_error=str(e),last_test=now().isoformat(),approved=False)
        save_config('skill',skill,'tested')
        return {'status':'FAIL','error':str(e)}

@app.post('/api/skills/{ref}/publish')
def publish_skill(ref:str):
    skill=get_config('skill',ref)
    if not skill or skill['test_status']!='PASS': raise ValueError('A passing test is required')
    load_skill(ref)
    skill['approved']=True
    return save_config('skill',skill,'published')

@app.post('/api/skills/upload')
async def upload_skill(file:UploadFile=File(...)):
    import yaml
    raw=await file.read(2_000_001)
    if len(raw)>2_000_000: raise ValueError('Skill upload exceeds 2 MB')
    if file.filename.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries=archive.infolist()
            if any(e.file_size>2_000_000 or '..' in Path(e.filename).parts or Path(e.filename).is_absolute() for e in entries): raise ValueError('Unsafe archive')
            candidates=[e for e in entries if e.filename=='SKILL.md']
            if len(candidates)!=1: raise ValueError('Package requires SKILL.md at its root')
            # Only the declarative entry point is imported. Executables never leave the ZIP.
            raw=archive.read(candidates[0])
    text=raw.decode('utf-8'); parts=text.split('---',2)
    if len(parts)!=3 or parts[0].strip(): raise ValueError('Missing YAML front matter')
    meta=yaml.safe_load(parts[1]); ref=f"{meta['id']}@{meta['version']}"
    if not re.fullmatch(r'[a-z0-9-]+@\d+\.\d+\.\d+',ref): raise ValueError('Invalid skill identity')
    path=confined(config.SKILLS,f"{meta['id']}/{meta['version']}/SKILL.md")
    if path.exists(): raise ValueError('Versions are immutable; upload a new version')
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(text,encoding='utf-8')
    try: load_skill(ref)
    except Exception:
        path.unlink(); raise
    return save_config('skill',{'id':ref,'name':meta['id'],'version':str(meta['version']),'type':meta.get('type','instruction'),'enabled':True,'approved':False,'test_status':'UNTESTED','dependencies':meta.get('dependencies',[])},'uploaded')

@app.post('/api/skills/create')
async def create_skill(body:dict):
    import yaml
    instructions=body.pop('instructions','Execute the configured approved handler.')
    markdown='---\n'+yaml.safe_dump(body,sort_keys=False)+'---\n\n'+instructions+'\n'
    return await upload_skill(UploadFile(filename='SKILL.md',file=io.BytesIO(markdown.encode('utf-8'))))

@app.post('/api/sources/{id}/test')
def source_test(id:str):
    source=get_config('source',id)
    if not source: raise HTTPException(404)
    from .skills import mysql_reader, excel_reader, api_reader
    try:
        {'mysql':mysql_reader,'excel':excel_reader,'api':api_reader}[source['type']]({}, {'source':id},'source-test-'+uid())
        source['test_status']='PASS'; source['last_error']=''
    except Exception as e: source['test_status']='FAIL'; source['last_error']=str(e)
    return save_config('source',source,'tested')

@app.get('/api/sources/{id}/inspect')
def inspect_source(id:str):
    source=get_config('source',id)
    if not source: raise HTTPException(404)
    if source['type']=='excel':
        import openpyxl
        path=confined(config.DATA,source['file'])
        if path.stat().st_size>source.get('maximum_size',10485760): raise ValueError('Workbook too large')
        with zipfile.ZipFile(path) as archive:
            if sum(i.file_size for i in archive.infolist())>100_000_000: raise ValueError('Expanded workbook too large')
        book=openpyxl.load_workbook(path,read_only=True,data_only=True,keep_links=False)
        try: return {'worksheets':[{'name':sheet.title,'rows':sheet.max_row,'columns':sheet.max_column,'headers':list(next(sheet.iter_rows(values_only=True),()))} for sheet in book]}
        finally: book.close()
    if source['type']=='mysql':
        from sqlalchemy import inspect
        from .skills import mysql_engine
        engine=mysql_engine(source)
        try:
            inspector=inspect(engine)
            available=inspector.get_table_names()
            return {'tables':{table:[{'name':c['name'],'type':str(c['type']),'nullable':c['nullable']} for c in inspector.get_columns(table)] for table in source['allowed_tables'] if table in available}}
        finally: engine.dispose()
    return {'type':'api','url':source['url'],'maximum_rows':source.get('maximum_rows',10000)}

@app.post('/api/sources/upload-excel')
async def upload_excel(file:UploadFile=File(...)):
    if not file.filename.lower().endswith('.xlsx'): raise ValueError('Upload a macro-free .xlsx workbook')
    raw=await file.read(10_485_761)
    if len(raw)>10_485_760: raise ValueError('Workbook exceeds 10 MB')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(i.file_size for i in archive.infolist())>100_000_000: raise ValueError('Expanded workbook exceeds 100 MB')
        if any('vbaproject' in i.filename.lower() for i in archive.infolist()): raise ValueError('Macros are not allowed')
    import openpyxl
    book=openpyxl.load_workbook(io.BytesIO(raw),read_only=True,data_only=True,keep_links=False)
    sheets=book.sheetnames; book.close()
    id='excel-'+uid(); relative='uploads/'+id+'.xlsx'
    path=confined(config.DATA,relative); path.parent.mkdir(exist_ok=True); path.write_bytes(raw)
    return save_config('source',{'id':id,'name':Path(file.filename).stem,'type':'excel','file':relative,'enabled':True,'maximum_size':10485760,'test_status':'UNTESTED','worksheets':sheets},'uploaded')

@app.get('/api/datasets/{id}')
def dataset_detail(id:str):
    from .skills import read_dataset
    with Session() as s:
        dataset=s.get(Dataset,id)
        if not dataset: raise HTTPException(404)
        result=serialize(dataset); result.pop('path',None)
    frame,_=read_dataset(id)
    result['preview']=json.loads(frame.head(100).to_json(orient='records',date_format='iso'))
    return result

@app.post('/api/workflows/{id}/validate')
def flow_validate(id:str):
    workflow=get_config('workflow',id)
    if not workflow: raise HTTPException(404)
    result=validate_workflow(workflow)
    if not bus.connected: result['errors'].append('Mosca OFFLINE'); result['status']='FAIL'
    return result

def start_run(workflow, context=None, test=None, target=None):
    if not bus.connected: raise HTTPException(503,'Mosca is offline')
    agents={a['id']:a for a in configs('agent') if a['id'] in workflow['nodes']}
    snapshot={'workflow':workflow,'agents':agents,'sources':{source['id']:source for source in configs('source')},'test':test,'target':target}
    with Session.begin() as s:
        run=Run(id=uid(),workflow_id=workflow['id'],snapshot=snapshot,context=context or {})
        s.add(run); s.add(Audit(action='workflow.'+('tested' if test else 'executed'),entity=run.id,new=snapshot))
    return {'run_id':run.id,'status':'WAITING'}

@app.post('/api/workflows/{id}/run')
def run_workflow(id:str,body:dict|None=None):
    result=flow_validate(id)
    if result['status']!='PASS': raise HTTPException(422,result)
    if get_config('workflow',id).get('test_status')!='PASS': raise ValueError('A successful full workflow test is required before production runs')
    return start_run(get_config('workflow',id),context=(body or {}).get('input',{}))

@app.post('/api/workflows/{id}/test')
def test_workflow(id:str,body:dict|None=None):
    workflow=get_config('workflow',id)
    if not workflow: raise HTTPException(404)
    result=validate_workflow(workflow,require_tests=False)
    if result['status']!='PASS': raise HTTPException(422,result)
    return start_run(workflow,context=(body or {}).get('input',{}),test='workflow',target=id)

@app.post('/api/agents/{id}/test')
def test_agent(id:str,body:dict|None=None):
    a=get_config('agent',id)
    if not a: raise HTTPException(404)
    if not bus.connected: raise HTTPException(503,'Mosca is offline')
    if a['role']=='manager':
        with Session() as s: hb=s.get(Heartbeat,id)
        if not hb or hb.timestamp.replace(tzinfo=now().tzinfo)<now()-timedelta(seconds=20): raise ValueError('Manager offline')
        a['test_status']='PASS'; return save_config('agent',a,'tested')
    if not a['skills']: raise ValueError('Assign a skill first')
    for ref in a['skills']: load_skill(ref)
    context=body['input'] if body and 'input' in body else test_context(a['skills'][0])
    return start_run({'id':'TEST-'+id,'name':'Individual BOT test','nodes':['START','MANAGER',id,'FINAL'],'version':1},context,test='agent',target=id)

@app.get('/api/runs/{id}')
def run_detail(id:str):
    with Session() as s:
        run=s.get(Run,id)
        if not run: raise HTTPException(404)
        return {'run':serialize(run),'executions':[serialize(x) for x in s.scalars(select(Execution).where(Execution.run_id==id).order_by(Execution.started))],'datasets':[serialize(d) for d in s.scalars(select(Dataset).where(Dataset.run_id==id))]}

@app.post('/api/runs/{id}/stop')
def stop_run(id:str):
    with Session.begin() as s:
        run=s.get(Run,id)
        if not run: raise HTTPException(404)
        if run.status not in ('WAITING','RUNNING'): raise ValueError('Run already finished')
        run.status='STOPPED'; run.finished=now()
        s.add(Audit(action='workflow.stopped',entity=id,new={'status':'STOPPED'}))
    return {'status':'STOPPED','note':'No downstream work will start; active read-only work may finish'}

@app.get('/api/events')
def events(run_id:str='',q:str=''):
    with Session() as s:
        query=select(Event).order_by(Event.timestamp.desc()).limit(500)
        if run_id: query=query.where(Event.run_id==run_id)
        rows=[serialize(e) for e in s.scalars(query)]
        return [r for r in rows if q.lower() in json.dumps(r).lower()]

@app.get('/api/logs')
def logs():
    with Session() as s: return [serialize(e) for e in s.scalars(select(Audit).order_by(Audit.timestamp.desc()).limit(500))]

@app.get('/api/artifacts/{run}/{name}')
def artifact(run:str,name:str):
    if name not in ('report.html','yield.svg'): raise HTTPException(404)
    path=confined(config.DATA/'reports',f'{run}/{name}')
    if not path.exists(): raise HTTPException(404)
    return FileResponse(path)

@app.websocket('/api/ws')
async def websocket(ws:WebSocket):
    await ws.accept()
    try:
        if config.API_TOKEN:
            auth=await asyncio.wait_for(ws.receive_json(),timeout=5)
            if auth.get('token')!=config.API_TOKEN: await ws.close(code=1008); return
        while True:
            await ws.send_json(await asyncio.to_thread(state))
            await asyncio.sleep(2)
    except (WebSocketDisconnect,RuntimeError,asyncio.TimeoutError): pass
