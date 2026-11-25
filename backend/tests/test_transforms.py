import pandas as pd
import pytest
from app.skills import transform_frame,api_reader

def test_transformations_record_discarded_rows():
    frame=pd.DataFrame({'product':['A','A','B',None],'qty':[2,2,6,4]})
    result,lineage=transform_frame(frame,[{'operation':'drop_missing','columns':['product']},{'operation':'deduplicate'},{'operation':'group','keys':['product'],'aggregations':{'qty':'sum'}}])
    assert result['qty'].tolist()==[2,6]
    assert lineage[0]['removed_rows']==1
    assert lineage[1]['removed_rows']==1

def test_unsafe_aggregation_is_rejected():
    with pytest.raises(ValueError,match='Unapproved'):
        transform_frame(pd.DataFrame({'a':[1]}),[{'operation':'group','keys':['a'],'aggregations':{'a':'eval'}}])

def test_api_requires_deployment_allowlist():
    from app.db import save_config
    save_config('source',{'id':'external','type':'api','enabled':True,'url':'http://127.0.0.1/private'})
    with pytest.raises(ValueError,match='allowlisted'): api_reader({}, {'source':'external'},'test')
