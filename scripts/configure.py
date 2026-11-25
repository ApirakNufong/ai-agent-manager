"""Create local deployment secrets once without printing or overwriting them."""
from pathlib import Path
import secrets

root=Path(__file__).resolve().parents[1]
destination=root/'.env'
if destination.exists():
    print('.env already exists; no changes made.')
else:
    values={name:secrets.token_urlsafe(32) for name in ('POSTGRES_PASSWORD','MYSQL_ROOT_PASSWORD','MYSQL_PASSWORD','MQTT_PASSWORD','API_TOKEN')}
    values.update(MYSQL_USERNAME='agent_reader',MYSQL_DATABASE='production_db',MYSQL_HOST='mysql',MYSQL_PORT='3306')
    destination.write_text('\n'.join(f'{name}={value}' for name,value in values.items())+'\n',encoding='utf-8')
    print('Created .env with unique deployment secrets. Read API_TOKEN from that file for the Settings screen.')
