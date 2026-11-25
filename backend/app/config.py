import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.getenv('DATA_DIR', str(ROOT / 'data'))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
SKILLS = Path(os.getenv('SKILLS_DIR', str(ROOT / 'skills'))).resolve()
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///' + str(DATA / 'manager.db'))
MQTT_HOST = os.getenv('MQTT_HOST', 'localhost')
MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))
API_TOKEN = os.getenv('API_TOKEN', '')
