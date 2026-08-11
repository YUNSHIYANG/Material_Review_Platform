"""系统配置存取（system_config 表），业务阈值优先读库，默认取环境配置。"""
from sqlalchemy.orm import Session

from .config import get_settings
from .models import SystemConfig

settings = get_settings()


def get_config(db: Session, key: str, default=None):
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    return row.value if row and row.value is not None else default


def set_config(db: Session, key: str, value, operator_id: int | None = None) -> None:
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row is None:
        db.add(SystemConfig(key=key, value=value, updated_by=operator_id))
    else:
        row.value = value
        row.updated_by = operator_id
    db.flush()


def get_effective_timeout(db: Session) -> int:
    return int(get_config(db, "timeout_hours", settings.timeout_hours) or settings.timeout_hours)


def get_effective_cycle_threshold(db: Session) -> int:
    return int(get_config(db, "cycle_threshold", settings.cycle_threshold) or settings.cycle_threshold)


def get_effective_global_threshold(db: Session) -> int:
    return int(
        get_config(db, "global_reassign_threshold", settings.global_reassign_threshold)
        or settings.global_reassign_threshold
    )


def get_effective_pending_multiplier(db: Session) -> float:
    return float(
        get_config(db, "assignment_pending_multiplier", settings.assignment_pending_multiplier)
        or settings.assignment_pending_multiplier
    )


def config_snapshot(db: Session) -> dict:
    keys = ["timeout_hours", "cycle_threshold", "global_reassign_threshold", "assignment_pending_multiplier"]
    return {k: get_config(db, k, getattr(settings, k)) for k in keys}
