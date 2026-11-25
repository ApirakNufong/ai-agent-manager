from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from .config import DATABASE_URL
from .models import Base, Config, Audit, Run, now

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={'check_same_thread': False, 'timeout': 30} if DATABASE_URL.startswith('sqlite') else {})
Session = sessionmaker(engine, expire_on_commit=False)

def initialize(): Base.metadata.create_all(engine)
def configs(kind):
    with Session() as s: return [c.body for c in s.scalars(select(Config).where(Config.kind == kind))]
def get_config(kind, id):
    with Session() as s:
        c = s.get(Config, kind + ':' + id)
        return c.body if c else None
def save_config(kind, body, action='updated'):
    with Session.begin() as s:
        key = kind + ':' + body['id']
        c = s.get(Config, key)
        s.add(Audit(action=kind + '.' + action, entity=body['id'], old=c.body if c else {}, new=body))
        if c: c.body = body
        else: s.add(Config(id=key, kind=kind, body=body))
        if action=='updated':
            affected={body['id']} if kind=='agent' else set()
            for agent in s.scalars(select(Config).where(Config.kind=='agent')):
                field='skills' if kind=='skill' else 'data_sources' if kind=='source' else None
                if field and body['id'] in agent.body.get(field,[]):
                    agent.body={**agent.body,'test_status':'UNTESTED','version':agent.body.get('version',1)+1}
                    affected.add(agent.body['id'])
            for flow in s.scalars(select(Config).where(Config.kind=='workflow')):
                if affected.intersection(flow.body.get('nodes',[])):
                    flow.body={**flow.body,'test_status':'UNTESTED','version':flow.body.get('version',1)+1}
    return body
def serialize(obj):
    return {c.name: (v.isoformat() if hasattr(v, 'isoformat') else v) for c in obj.__table__.columns for v in [getattr(obj, c.name)]}
