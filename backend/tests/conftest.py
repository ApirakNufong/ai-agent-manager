import os
import tempfile
import shutil
from pathlib import Path
import pytest

TEST_ROOT=Path(tempfile.mkdtemp(prefix='agent-manager-tests-'))
os.environ['DATA_DIR']=str(TEST_ROOT)
os.environ['DATABASE_URL']='sqlite:///'+str(TEST_ROOT/'test.db')
shutil.copytree(Path(__file__).resolve().parents[1]/'skills',TEST_ROOT/'skills')
os.environ['SKILLS_DIR']=str(TEST_ROOT/'skills')
os.environ['API_TOKEN']=''

@pytest.fixture(autouse=True)
def database():
    from app.db import engine, initialize
    from app.models import Base
    from app.seed import seed
    Base.metadata.drop_all(engine); initialize(); seed()
    yield
