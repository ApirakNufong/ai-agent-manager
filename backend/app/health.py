import sys
from datetime import timedelta
from .db import Session
from .models import Heartbeat,now

with Session() as session:
    heartbeat=session.get(Heartbeat,sys.argv[1])
    healthy=heartbeat and heartbeat.timestamp.replace(tzinfo=now().tzinfo)>now()-timedelta(seconds=20)
sys.exit(0 if healthy else 1)
