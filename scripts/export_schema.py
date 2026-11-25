"""Export the SQLAlchemy model schema without connecting to PostgreSQL."""
import sys
from pathlib import Path
from sqlalchemy.schema import CreateTable,CreateIndex
from sqlalchemy.dialects import postgresql
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from app.models import Base
dialect=postgresql.dialect()
sql='-- Generated from backend/app/models.py. Runtime initialization creates these tables.\n\n'
for table in Base.metadata.sorted_tables:
    sql+=str(CreateTable(table).compile(dialect=dialect)).strip()+';\n\n'
    for index in table.indexes: sql+=str(CreateIndex(index).compile(dialect=dialect))+';\n'
(root/'backend'/'schema.sql').write_text(sql,encoding='utf-8')
print('Exported PostgreSQL schema')
