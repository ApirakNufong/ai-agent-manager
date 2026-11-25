import pytest
from app.seed import fixture_context, STANDARD
from app.skills import execute_skill, load_skill, confined, mysql_reader, read_dataset
from app.config import DATA

def test_all_packages_validate():
    for name in STANDARD:
        meta, instructions=load_skill(name+'@1.0.0')
        assert meta['version']=='1.0.0' and instructions

def test_deterministic_pipeline_and_lineage():
    context=fixture_context('test-run')
    for name in STANDARD[2:]: context=execute_skill(name+'@1.0.0',context,'test-run')
    assert context['metrics']['input']==20000
    assert context['metrics']['output']==19210
    assert context['metrics']['yield_rate']==pytest.approx(96.05)
    assert context['metrics']['gap']==pytest.approx(-1.95)
    assert context['abnormalities']['below_target']==20
    assert context['statistics']['mean']==pytest.approx(96.05)
    assert (DATA/'reports'/'test-run'/'report.html').exists()
    frame,lineage=read_dataset(context['dataset_id'])
    assert len(frame)==20 and any(x.get('step')=='join' for x in lineage)

def test_path_escape_rejected():
    with pytest.raises(ValueError): confined(DATA,'../../secrets.txt')

def test_sql_identifier_injection_rejected_before_connect():
    with pytest.raises(ValueError,match='approved'): mysql_reader({}, {'table':'production; DROP TABLE production'},'test')

def test_unpinned_skill_rejected():
    with pytest.raises(ValueError): load_skill('data-analysis@latest')

def test_missing_input_stops_skill():
    from jsonschema import ValidationError
    with pytest.raises(ValidationError): execute_skill('data-preparation@1.0.0',{},'test')

def test_excel_real_workbook():
    context=execute_skill('excel-reader@1.0.0',{},'test')
    frame,lineage=read_dataset(context['target_dataset'])
    assert len(frame)==20 and list(frame.columns)==['production_date','product_code','target']
    assert lineage[0]['worksheet']=='Targets'

def test_empty_dataset_fails_explicitly():
    import pandas as pd
    from app.skills import store_dataset
    ctx=fixture_context('empty-test')
    ctx['actual_dataset']=store_dataset('empty-test',pd.DataFrame(columns=['production_date','product_code','input_qty','good_output','ng']),{'type':'test'},[])
    with pytest.raises(ValueError,match='Empty'): execute_skill('data-preparation@1.0.0',ctx,'empty-test')
