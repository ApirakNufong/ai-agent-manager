from typing import Literal
from pydantic import BaseModel, Field, model_validator
from .models import uid, now

class Agent(BaseModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]+$')
    name: str
    description: str = ''
    role: Literal['manager', 'staff'] = 'staff'
    system_prompt: str = ''
    action: str = 'execute_skills'
    input_schema: dict = Field(default_factory=lambda: {'type': 'object'})
    output_schema: dict = Field(default_factory=lambda: {'type': 'object'})
    before_node: str = 'MANAGER'
    after_node: str = 'FINAL'
    skills: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    mqtt_topic: str = 'ai-agent/{workflow_id}/{agent_id}'
    timeout: int = Field(default=60, ge=1, le=3600)
    retries: int = Field(default=1, ge=0, le=5)
    enabled: bool = True
    test_status: str = 'UNTESTED'
    version: int = 1

    @model_validator(mode='after')
    def check_identity(self):
        if self.role=='manager' and self.id!='MANAGER': raise ValueError('The Manager identity must be MANAGER')
        if self.role=='staff' and not self.id.startswith('BOT-'): raise ValueError('Staff identities must start with BOT-')
        return self

class Workflow(BaseModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]+$')
    name: str
    nodes: list[str]
    version: int = 1
    allow_offline: bool = False
    positions: dict = Field(default_factory=dict)

class Message(BaseModel):
    message_id: str = Field(default_factory=uid)
    correlation_id: str
    workflow_id: str
    run_id: str
    agent_id: str
    source_agent: str
    target_agent: str
    event: str
    timestamp: str = Field(default_factory=lambda: now().isoformat())
    payload: dict = Field(default_factory=dict)
