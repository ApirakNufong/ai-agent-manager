"""Versioned declarative skills. Uploaded packages cannot execute arbitrary code."""
import json
import zipfile
import os
import re
import socket
import ipaddress
from contextvars import ContextVar
from urllib.parse import urlparse
from pathlib import Path
from html import escape
import yaml
import pandas as pd
import numpy as np
import httpx
from scipy import stats
from sqlalchemy import create_engine, text, URL
from jsonschema import Draft202012Validator, validate
from .config import DATA, SKILLS
from .db import Session, get_config
from .models import Dataset, Audit, uid, now

SOURCE_SNAPSHOT=ContextVar('source_snapshot',default={})
def source_config(id): return SOURCE_SNAPSHOT.get().get(id) or get_config('source',id)

def confined(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()): raise ValueError('Path outside approved storage')
    return path

def load_skill(ref):
    if not re.fullmatch(r'[a-z0-9-]+@\d+\.\d+\.\d+', ref): raise ValueError('Skill requires a pinned semantic version')
    name, version = ref.split('@')
    path = confined(SKILLS, f'{name}/{version}/SKILL.md')
    raw = path.read_text(encoding='utf-8')
    pieces = raw.split('---', 2)
    if len(pieces) != 3 or pieces[0].strip(): raise ValueError('SKILL.md requires YAML front matter')
    meta = yaml.safe_load(pieces[1])
    if meta['id'] != name or str(meta['version']) != version: raise ValueError('Skill identity mismatch')
    if meta['handler'] not in HANDLERS: raise ValueError('Unapproved handler; arbitrary uploaded scripts are disabled')
    if not set(meta.get('permissions',[])).issubset({'data:read','dataset:write','network:read','report:write'}): raise ValueError('Unapproved skill permission')
    for reference in meta.get('references',[]):
        if not confined(path.parent,reference).is_file(): raise ValueError(f'Missing reference: {reference}')
    for key in ('input_schema', 'output_schema'): Draft202012Validator.check_schema(meta[key])
    return meta, pieces[2].strip()

def store_dataset(run_id, frame, source, lineage):
    id = uid()
    path = DATA / 'datasets' / (id + '.json')
    path.parent.mkdir(exist_ok=True)
    path.write_text(frame.to_json(orient='records', date_format='iso'), encoding='utf-8')
    with Session.begin() as s:
        s.add(Dataset(id=id, run_id=run_id, source=source,
                      schema=[{'name': c, 'type': str(t)} for c,t in frame.dtypes.items()],
                      row_count=len(frame), path=str(path), lineage=lineage))
        s.add(Audit(action='data.access',entity=id,new={'source':source,'rows':len(frame),'run_id':run_id}))
    return id

def read_dataset(id):
    with Session() as s:
        d = s.get(Dataset, id)
        if not d: raise ValueError('Dataset not found')
        return pd.DataFrame(json.loads(Path(d.path).read_text(encoding='utf-8')),columns=[column['name'] for column in d.schema]), d.lineage

def mysql_engine(source):
    prefix=source.get('authentication_reference','MYSQL_*').removesuffix('_*')
    if not re.fullmatch(r'MYSQL(?:_[A-Z0-9]+)*',prefix): raise ValueError('Invalid MySQL authentication reference')
    def env(key,default=None):
        value=os.getenv(prefix+'_'+key,default)
        if value is None: raise ValueError('Missing environment configuration: '+prefix+'_'+key)
        return value
    database=env('DATABASE')
    if source.get('database') and source['database']!=database: raise ValueError('Database is outside the approved connection')
    url=URL.create('mysql+pymysql',username=env('USERNAME'),password=env('PASSWORD'),host=env('HOST','mysql'),port=int(env('PORT','3306')),database=database)
    return create_engine(url,connect_args={'connect_timeout':min(int(source.get('connection_timeout',5)),30),'read_timeout':min(int(source.get('query_timeout',15)),60),'write_timeout':5})

def mysql_reader(ctx, cfg, run):
    source = source_config(cfg.get('source', 'mysql-production'))
    if not source or not source.get('enabled'): raise ValueError('MySQL source disabled')
    table = cfg.get('table', 'production')
    # Table names are identifiers, never interpolated from unvalidated SQL.
    if table not in source['allowed_tables'] or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', table):
        raise ValueError('Table is not approved')
    maximum = min(int(source['maximum_rows']), 100000)
    engine = mysql_engine(source)
    query = f'SELECT /*+ MAX_EXECUTION_TIME(10000) */ * FROM `{table}` WHERE production_date >= :start_date LIMIT :limit'
    try:
        with engine.connect() as con:
            con.execute(text('SET SESSION TRANSACTION READ ONLY'))
            frame = pd.read_sql(text(query), con, params={'start_date': cfg.get('start_date', '2000-01-01'), 'limit': maximum})
    finally: engine.dispose()
    lineage = [{'source': source['id'], 'table': table, 'query_reference': 'approved-production-select-v1', 'loaded': now().isoformat(), 'rows': len(frame), 'limit': maximum}]
    return {**ctx, 'actual_dataset': store_dataset(run, frame, {'type': 'mysql', 'name': source['id'], 'reference': table}, lineage)}

def excel_reader(ctx, cfg, run):
    source = source_config(cfg.get('source', 'excel-targets'))
    if not source or not source.get('enabled'): raise ValueError('Excel source disabled')
    path = confined(DATA, cfg.get('file', source['file']))
    if path.suffix.lower() != '.xlsx': raise ValueError('Only macro-free .xlsx is enabled')
    if path.stat().st_size > source.get('maximum_size', 10485760): raise ValueError('Workbook too large')
    with zipfile.ZipFile(path) as workbook:
        if sum(item.file_size for item in workbook.infolist())>100_000_000: raise ValueError('Expanded workbook exceeds 100 MB')
        if any('vbaproject' in item.filename.lower() for item in workbook.infolist()): raise ValueError('Macro-bearing workbooks are not accepted')
    sheet = cfg.get('sheet', 'Targets')
    with pd.ExcelFile(path,engine='openpyxl') as book:
        worksheets=book.sheet_names
        if sheet not in worksheets: raise ValueError('Worksheet not found; available: '+', '.join(worksheets))
        frame=pd.read_excel(book,sheet_name=sheet,usecols=cfg.get('columns') or cfg.get('range'),skiprows=cfg.get('skip_rows',0),nrows=min(int(cfg.get('maximum_rows',100000)),100000),header=cfg.get('header_row',0))
    missing = set(cfg.get('required_columns', ['production_date','product_code','target'])) - set(frame.columns)
    if missing: raise ValueError(f'Missing columns: {sorted(missing)}')
    frame,transformations=transform_frame(frame,cfg.get('operations',[]))
    lineage = [{'source': source['id'], 'file': path.name, 'worksheet': sheet, 'worksheets':worksheets,'loaded': now().isoformat(), 'rows': len(frame), 'blank_cells': int(frame.isna().sum().sum()), 'duplicates': int(frame.duplicated().sum())}]+transformations
    return {**ctx, 'target_dataset': store_dataset(run, frame, {'type':'excel','name':source['id'],'reference':path.name}, lineage)}

def transform_frame(frame,operations):
    """Structured transformations only: no eval, query strings, or arbitrary functions."""
    transformations=[]
    aggregations={'sum','mean','median','min','max','std','var','count','size','first','last'}
    for operation in operations:
        op=operation['operation']; before=len(frame)
        if op=='rename': frame=frame.rename(columns=operation['columns'])
        elif op=='map':
            column=operation['column']; mapping=operation['values']
            frame[column]=frame[column].map(lambda value:mapping.get(str(value),value))
        elif op=='cast': frame=frame.astype(operation['types'])
        elif op=='dates':
            for column in operation['columns']: frame[column]=pd.to_datetime(frame[column],format=operation.get('format'),errors='raise')
        elif op=='fill_missing': frame=frame.fillna(operation['values'])
        elif op=='drop_missing': frame=frame.dropna(subset=operation.get('columns'))
        elif op=='deduplicate': frame=frame.drop_duplicates(subset=operation.get('columns'))
        elif op=='sort': frame=frame.sort_values(operation['columns'],ascending=operation.get('ascending',True))
        elif op=='filter':
            column=frame[operation['column']]; value=operation['value']; compare=operation['comparison']
            operators={'eq':lambda:column.eq(value),'ne':lambda:column.ne(value),'gt':lambda:column.gt(value),'ge':lambda:column.ge(value),'lt':lambda:column.lt(value),'le':lambda:column.le(value),'in':lambda:column.isin(value)}
            if compare not in operators: raise ValueError('Unsupported filter comparison')
            frame=frame.loc[operators[compare]()].copy()
        elif op=='group':
            spec=operation['aggregations']
            if any(value not in aggregations for value in spec.values()): raise ValueError('Unapproved aggregation')
            frame=frame.groupby(operation['keys'],dropna=False,as_index=False).agg(spec)
        elif op=='pivot':
            function=operation.get('aggregation','sum')
            if function not in aggregations: raise ValueError('Unapproved aggregation')
            frame=frame.pivot_table(index=operation['index'],columns=operation['columns'],values=operation['values'],aggfunc=function).reset_index()
            frame.columns=[str(c) for c in frame.columns]
        else: raise ValueError('Unknown transformation: '+op)
        transformations.append({'step':op,'configuration':operation,'input_rows':before,'output_rows':len(frame),'removed_rows':before-len(frame)})
    return frame,transformations

def preparation(ctx, cfg, run):
    actual, lineage = read_dataset(ctx['actual_dataset'])
    targets, other = read_dataset(ctx['target_dataset'])
    keys = cfg['join_keys']
    before = len(actual)
    if not before or targets.empty: raise ValueError('Empty input or target dataset')
    transformations=[]
    if cfg.get('rename_columns'):
        actual=actual.rename(columns=cfg['rename_columns']); transformations.append({'step':'rename','columns':cfg['rename_columns']})
    if cfg.get('rename_target_columns'):
        targets=targets.rename(columns=cfg['rename_target_columns']); transformations.append({'step':'rename_targets','columns':cfg['rename_target_columns']})
    for column, dtype in cfg.get('column_types',{}).items():
        actual[column]=pd.to_datetime(actual[column],errors='raise') if dtype=='date' else actual[column].astype(dtype)
        transformations.append({'step':'convert','column':column,'dtype':dtype})
    for frame in (actual, targets):
        for col in keys:
            if col.endswith('date'): frame[col] = pd.to_datetime(frame[col], errors='raise').dt.strftime('%Y-%m-%d')
    if cfg.get('fill_missing'):
        counts={k:int(actual[k].isna().sum()) for k in cfg['fill_missing']}
        actual=actual.fillna(cfg['fill_missing']); transformations.append({'step':'fill_missing','counts':counts})
    actual = actual.drop_duplicates()
    invalid = actual[['input_qty','good_output','ng']].isna().any(axis=1) | (actual['input_qty'] <= 0) | (actual['good_output']<0) | (actual['good_output']>actual['input_qty']) | (actual['ng']<0)
    if invalid.any(): raise ValueError(f'{int(invalid.sum())} invalid rows; preparation stopped without discarding data')
    merged = actual.merge(targets, on=keys, how='left', validate='many_to_one', indicator=True)
    if (merged['_merge'] != 'both').any(): raise ValueError('Missing configured target join matches')
    merged = merged.drop(columns=['_merge']).sort_values(keys)
    merged,operations=transform_frame(merged,cfg.get('operations',[]))
    lineage += other + transformations + [{'step':'join', 'keys':keys, 'received_rows':before, 'duplicates_removed':before-len(actual), 'output_rows':len(merged)}]+operations
    return {**ctx, 'dataset_id': store_dataset(run, merged, {'type':'derived','name':'prepared','reference':run}, lineage)}

def analysis(ctx, cfg, run):
    frame, lineage = read_dataset(ctx['dataset_id'])
    numerator, denominator = cfg['yield_numerator'], cfg['yield_denominator']
    frame['yield_rate'] = frame[numerator] / frame[denominator] * 100
    frame['gap'] = frame['yield_rate'] - frame['target']
    metrics = {'input':float(frame[denominator].sum()), 'output':float(frame[numerator].sum()), 'ng':float(frame['ng'].sum()), 'yield_rate':float(frame[numerator].sum()/frame[denominator].sum()*100), 'target':float(frame['target'].mean()), 'rows':len(frame)}
    metrics['gap'] = metrics['yield_rate'] - metrics['target']
    for name,formula in cfg.get('kpi_ratios',{}).items():
        divisor=frame[formula['denominator']].sum()
        metrics[name]=float(frame[formula['numerator']].sum()/divisor*formula.get('scale',1)) if divisor else None
    for column in cfg.get('cumulative_columns',[]): frame[column+'_cumulative']=frame[column].cumsum()
    extra={}
    if cfg.get('group_by'):
        grouped=frame.groupby(cfg['group_by'],dropna=False,as_index=False)[cfg.get('value_columns',[numerator,denominator,'ng'])].sum()
        extra['grouped_dataset']=store_dataset(run,grouped,{'type':'analysis','name':'grouped','reference':run},lineage+[{'step':'group','keys':cfg['group_by']}])
    if cfg.get('time_series'):
        series=cfg['time_series']; series_frame=frame.copy(); series_frame[series['date_column']]=pd.to_datetime(series_frame[series['date_column']],errors='raise')
        summary=series_frame.set_index(series['date_column'])[series.get('value_columns',[numerator,denominator])].resample(series.get('frequency','D')).sum().reset_index()
        extra['time_series_dataset']=store_dataset(run,summary,{'type':'analysis','name':'time-series','reference':run},lineage+[{'step':'resample','configuration':series}])
    numeric=frame.select_dtypes(include='number')
    descriptive=numeric.describe().replace([np.inf,-np.inf],np.nan).reset_index().rename(columns={'index':'statistic'})
    extra['descriptive_dataset']=store_dataset(run,descriptive,{'type':'analysis','name':'descriptive','reference':run},lineage+[{'step':'descriptive-statistics'}])
    return {**ctx, **extra,'metrics':metrics, 'dataset_id':store_dataset(run, frame, {'type':'analysis','name':'production','reference':run}, lineage + [{'step':'yield', 'formula':f'{numerator}/{denominator}*100'}])}

def statistics(ctx, cfg, run):
    frame, _ = read_dataset(ctx['dataset_id'])
    x = frame['yield_rate']
    summary={'count':int(x.count()),'sum':float(x.sum()),'mean':float(x.mean()),'median':float(x.median()),'std':float(x.std(ddof=0)),'variance':float(x.var(ddof=0)),'min':float(x.min()),'max':float(x.max()),'missing':int(x.isna().sum())}
    if len(x)>1:
        trend=stats.linregress(np.arange(len(x)),x)
        summary['trend_slope']=float(trend.slope)
        summary['growth_rate']=float((x.iloc[-1]/x.iloc[0]-1)*100) if x.iloc[0] else None
    return {**ctx, 'statistics':summary}

def abnormality(ctx, cfg, run):
    frame, _ = read_dataset(ctx['dataset_id'])
    z = np.nan_to_num(stats.zscore(frame['yield_rate'])) if len(frame)>1 else np.zeros(len(frame))
    return {**ctx, 'abnormalities': {'below_target':int((frame['gap']<0).sum()), 'outliers':int((np.abs(z)>cfg.get('z_threshold',3)).sum())}}

def visualization(ctx, cfg, run):
    frame, _ = read_dataset(ctx['dataset_id'])
    bars = []
    for i, row in frame.head(30).iterrows():
        x = len(bars)*25+45; height = max(0,min(float(row['yield_rate']),100))*2
        bars.append(f'<rect x="{x}" y="{230-height}" width="16" height="{height}" fill="#18b89a"/>')
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 850 270"><rect width="850" height="270" fill="#10202b"/><text x="30" y="25" fill="white">Production yield (%) · first 30 rows</text>'+''.join(bars)+'</svg>'
    path = DATA / 'reports' / run
    path.mkdir(parents=True,exist_ok=True)
    (path/'yield.svg').write_text(svg,encoding='utf-8')
    return {**ctx, 'chart_url':f'/api/artifacts/{run}/yield.svg'}

def report(ctx, cfg, run):
    frame, lineage = read_dataset(ctx['dataset_id'])
    path = DATA / 'reports' / run
    path.mkdir(parents=True,exist_ok=True)
    chart=(path/'yield.svg').read_text(encoding='utf-8') if (path/'yield.svg').exists() else ''
    html = '<!doctype html><meta charset="utf-8"><title>Production report</title><style>body{font:16px system-ui;max-width:1000px;margin:40px auto}td,th{padding:10px;border-bottom:1px solid #ddd}</style><h1>Production management report</h1><p>Run '+escape(run)+'</p>'+chart+'<h2>Metrics</h2><pre>'+escape(json.dumps(ctx.get('metrics',{}),indent=2))+'</pre><h2>Results</h2>'+frame.head(1000).to_html(index=False,escape=True)+'<h2>Lineage</h2><pre>'+escape(json.dumps(lineage,indent=2))+'</pre>'
    (path/'report.html').write_text(html,encoding='utf-8')
    return {**ctx, 'report_url':f'/api/artifacts/{run}/report.html'}

def instruction(ctx,cfg,run): return {**ctx, 'instructions':cfg.get('text','')}
def template(ctx,cfg,run): return {**ctx, 'text':cfg.get('template','{run_id}').format_map({**ctx,'run_id':run})}

def api_reader(ctx,cfg,run):
    source=source_config(cfg['source'])
    if not source or not source.get('enabled') or source.get('type')!='api': raise ValueError('API source is unavailable')
    url=source['url']; parsed=urlparse(url)
    hosts=set(os.getenv('ALLOWED_API_HOSTS','').split(','))
    if parsed.scheme!='https' or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.port not in (None,443): raise ValueError('API requires an administrator-allowlisted HTTPS host')
    for address in socket.getaddrinfo(parsed.hostname,443):
        if not ipaddress.ip_address(address[4][0]).is_global: raise ValueError('API must resolve to a public address')
    headers={}
    if source.get('authentication_reference'):
        ref=source['authentication_reference']
        if not re.fullmatch(r'API_SECRET_[A-Z0-9_]+',ref): raise ValueError('Invalid API secret reference')
        headers['Authorization']='Bearer '+os.environ[ref]
    content=bytearray()
    with httpx.stream('GET',url,headers=headers,params=cfg.get('parameters',{}),timeout=10,follow_redirects=False,trust_env=False) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            content.extend(chunk)
            if len(content)>1_000_000: raise ValueError('API response exceeds 1 MB')
    data=json.loads(content)
    for key in cfg.get('data_path',[]): data=data[key]
    if not isinstance(data,list) or not all(isinstance(row,dict) for row in data): raise ValueError('API must return an array of row objects')
    frame=pd.DataFrame(data)
    if len(frame)>source.get('maximum_rows',10000): raise ValueError('API row limit exceeded')
    return {**ctx,'dataset_id':store_dataset(run,frame,{'type':'api','name':source['id'],'reference':parsed.hostname},[{'source':source['id'],'loaded':now().isoformat(),'rows':len(frame)}])}

def composite(ctx,cfg,run):
    result=ctx
    if not cfg.get('skills'): raise ValueError('Composite requires pinned child skills')
    for ref in cfg['skills']:
        registered=get_config('skill',ref)
        if not registered or not registered.get('enabled') or not registered.get('approved'): raise ValueError('Composite child must be enabled and approved: '+ref)
        result=execute_skill(ref,result,run)
    return result

HANDLERS = {'mysql-reader':mysql_reader,'excel-reader':excel_reader,'data-preparation':preparation,'data-analysis':analysis,'statistical-analysis':statistics,'abnormality-detector':abnormality,'data-visualization':visualization,'production-report-generator':report,'instruction':instruction,'template':template,'api-reader':api_reader,'composite':composite}
SKILL_STACK=ContextVar('skill_stack',default=())

def execute_skill(ref, context, run_id):
    stack=SKILL_STACK.get()
    if ref in stack or len(stack)>=10: raise ValueError('Circular or excessive composite skill dependency')
    meta, _ = load_skill(ref)
    validate(context, meta['input_schema'])
    token=SKILL_STACK.set(stack+(ref,))
    try: result = HANDLERS[meta['handler']](context, meta.get('config',{}), run_id)
    finally: SKILL_STACK.reset(token)
    validate(result, meta['output_schema'])
    with Session.begin() as s:
        for key in ('actual_dataset','target_dataset','dataset_id','grouped_dataset','time_series_dataset','descriptive_dataset'):
            if result.get(key) and result.get(key)!=context.get(key):
                dataset=s.get(Dataset,result[key])
                if dataset: dataset.lineage=dataset.lineage+[{'skill':ref,'run_id':run_id,'timestamp':now().isoformat()}]
    return result
