from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Text, JSON, DateTime, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def uid(): return str(uuid4())
def now(): return datetime.now(timezone.utc)

class Base(DeclarativeBase): pass

class Config(Base):
    __tablename__ = 'configurations'
    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    body: Mapped[dict] = mapped_column(JSON)

class Run(Base):
    __tablename__ = 'runs'
    id: Mapped[str] = mapped_column(String(50), primary_key=True, default=uid)
    workflow_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default='WAITING')
    current: Mapped[str] = mapped_column(String(100), default='MANAGER')
    started: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[dict] = mapped_column(JSON, default=dict)

class Execution(Base):
    __tablename__ = 'executions'
    __table_args__ = (UniqueConstraint('run_id', 'agent_id', 'attempt'),)
    id: Mapped[str] = mapped_column(String(50), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(String(50), index=True)
    agent_id: Mapped[str] = mapped_column(String(100))
    attempt: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(30), default='WAITING')
    started: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)

class Event(Base):
    __tablename__ = 'events'
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    topic: Mapped[str] = mapped_column(String(300))
    run_id: Mapped[str] = mapped_column(String(50), index=True, default='')
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    body: Mapped[dict] = mapped_column(JSON)
    processing: Mapped[str] = mapped_column(String(50), default='RECEIVED')

class Dataset(Base):
    __tablename__ = 'datasets'
    id: Mapped[str] = mapped_column(String(50), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(String(50), index=True)
    source: Mapped[dict] = mapped_column(JSON)
    schema: Mapped[list] = mapped_column(JSON)
    row_count: Mapped[int]
    path: Mapped[str] = mapped_column(Text)
    lineage: Mapped[list] = mapped_column(JSON)

class Audit(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[str] = mapped_column(String(50), primary_key=True, default=uid)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    user: Mapped[str] = mapped_column(String(100), default='operator')
    action: Mapped[str] = mapped_column(String(100))
    entity: Mapped[str] = mapped_column(String(180))
    old: Mapped[dict] = mapped_column(JSON, default=dict)
    new: Mapped[dict] = mapped_column(JSON, default=dict)

class Heartbeat(Base):
    __tablename__ = 'heartbeats'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    status: Mapped[str] = mapped_column(String(30), default='ONLINE')
