import json
import logging
import os
import time
from typing import Protocol
import paho.mqtt.client as mqtt
from .config import MQTT_HOST, MQTT_PORT
from .schemas import Message

log = logging.getLogger(__name__)

class MessageBus(Protocol):
    def publish(self, topic: str, message: dict): ...

class MqttBus:
    def __init__(self, identity, handler=None, client_id=None):
        self.identity, self.handler, self.connected = identity, handler, False
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id or identity, protocol=mqtt.MQTTv311)
        self.client.username_pw_set(identity, os.getenv('MQTT_PASSWORD', ''))
        self.client.reconnect_delay_set(1, 15)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
    def on_connect(self, client, userdata, flags, reason, properties):
        self.connected = not reason.is_failure
        self.connection_audit('connected' if self.connected else 'rejected')
        if not self.connected: return
        if self.identity in ('engine', 'manager', 'api'):
            client.subscribe('ai-agent/#', qos=1)
        else:
            client.subscribe(f'ai-agent/+/{self.identity}/command', qos=1)
    def connection_audit(self,status):
        try:
            from .db import Session
            from .models import Audit
            with Session.begin() as s: s.add(Audit(action='mqtt.'+status,entity=self.identity,new={'broker':MQTT_HOST,'status':status}))
        except Exception: log.exception('Could not persist broker connection state')
    def on_disconnect(self,*args):
        self.connected=False
        self.connection_audit('disconnected')
    def on_message(self, client, userdata, msg):
        try:
            if len(msg.payload) > 65536: raise ValueError('MQTT message exceeds 64 KiB')
            body = Message.model_validate_json(msg.payload).model_dump()
            if self.handler: self.handler(msg.topic, body)
        except Exception:
            log.exception('MQTT delivery failed: %s', msg.topic)
    def start(self):
        self.client.connect_async(MQTT_HOST, MQTT_PORT, 30)
        self.client.loop_start()
    def publish(self, topic, message):
        raw = json.dumps(message)
        if len(raw.encode()) > 65536: raise ValueError('Use dataset references for large payloads')
        result = self.client.publish(topic, raw, qos=1, retain=False)
        if result.rc != mqtt.MQTT_ERR_SUCCESS: raise ConnectionError('Mosca unavailable')
    def stop(self):
        self.client.disconnect()
        self.client.loop_stop()

def envelope(workflow, run, agent, event, payload=None, source='engine', target=None):
    return Message(correlation_id=run, workflow_id=workflow, run_id=run, agent_id=agent,
                   source_agent=source, target_agent=target or agent, event=event, payload=payload or {}).model_dump()

class MemoryBus:
    """Explicit test adapter; never selected by production configuration."""
    connected = True
    def __init__(self): self.messages = []
    def publish(self, topic, message): self.messages.append((topic, message))
