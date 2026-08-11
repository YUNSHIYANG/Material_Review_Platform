"""数据库引擎与会话管理。"""
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import get_settings

logger = logging.getLogger("app")

settings = get_settings()

_engine_kwargs = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(settings.database_url, future=True, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

Base = declarative_base()


def sync_missing_columns(db_bind, base) -> None:
    """幂等补齐：为已存在的表添加模型中新增的列。

    Base.metadata.create_all 只会创建缺失的“表”，不会给已有表加“列”；
    Docker 持久卷（pgdata）升级旧库时若缺列，SQLAlchemy 查询将直接报错。
    此处用最简 ALTER TABLE ADD COLUMN 补齐（不补外键/索引），SQLite 与 PostgreSQL 均适用。
    """
    from sqlalchemy import inspect, text

    inspector = inspect(db_bind)
    existing_tables = set(inspector.get_table_names())
    with db_bind.begin() as conn:
        for table in base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                col_type = col.type.compile(dialect=db_bind.dialect)
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}'
                conn.execute(text(ddl))
                logger.info("补齐缺失列：%s.%s", table.name, col.name)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def supports_row_lock(db) -> bool:
    """SQLite 不支持 FOR UPDATE / SKIP LOCKED，仅 PG/MySQL 使用行锁。"""
    return db.bind.dialect.name in ("postgresql", "mysql", "mariadb")
