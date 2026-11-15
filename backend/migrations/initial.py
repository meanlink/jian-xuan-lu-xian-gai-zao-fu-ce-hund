from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models
def migrate():
    Base.metadata.create_all(engine)
    # 既有库的 deliveries 表补齐对账字段（新表由 create_all 直接建全）
    with engine.begin() as conn:
        existing={c['name'] for c in inspect(conn).get_columns('deliveries')}
        medium='MEDIUMTEXT' if engine.dialect.name=='mysql' else 'TEXT'
        additions={'json_checksum':'VARCHAR(64)','csv_content':medium,'json_content':medium,
                   'status':"VARCHAR(20) NOT NULL DEFAULT 'ok'"}
        for name,ddl in additions.items():
            if name not in existing:
                conn.execute(text(f'ALTER TABLE deliveries ADD COLUMN {name} {ddl}'))
if __name__=='__main__':migrate()
