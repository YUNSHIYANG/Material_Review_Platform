"""Cron 定时任务：每5分钟扫描超时（初审 personal_deadline / 终审 admin_assigned_at+72h）、
邮件失败重试、每日 timeout_count 衰减。使用 Redis 分布式锁防止多实例重复执行。"""
import logging

from sqlalchemy.orm import Session

from .config_store import get_config, get_effective_timeout, set_config
from .counters import decay_timeout_count
from .database import SessionLocal
from .email_service import dispatch_emails, retry_failed_emails
from .flows import _reassign_admin_after_timeout
from .locking import cron_lock, submission_lock
from .models import StaffReview, Submission, User
from .utils import add_hours, utcnow

logger = logging.getLogger("cron")


def scan_timeouts(db: Session) -> None:
    now = utcnow()
    timeout_h = get_effective_timeout(db)

    # ---- 初审超时：staff_reviews.personal_deadline ----
    overdue = (
        db.query(StaffReview)
        .filter(
            StaffReview.is_timeout.is_(False),
            StaffReview.is_withdrawn.is_(False),
            StaffReview.submitted_at.is_(None),
            StaffReview.personal_deadline < now,
        )
        .all()
    )
    sub_ids = {sr.submission_id for sr in overdue}
    for sid in sub_ids:
        try:
            with submission_lock(sid):
                sub = db.get(Submission, sid)
                if sub is None or sub.status != "first_reviewing":
                    continue
                from .flows import check_and_handle_timeout

                tasks = check_and_handle_timeout(db, sub, now=now)
                db.commit()
                dispatch_emails(db, tasks)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.exception("初审超时处理失败 submission=%s: %s", sid, e)

    # ---- 终审超时：admin_assigned_at + 72h ----
    reviewing = (
        db.query(Submission)
        .filter(
            Submission.status == "admin_reviewing",
            Submission.assigned_admin_id.isnot(None),
            Submission.admin_assigned_at.isnot(None),
        )
        .all()
    )
    for sub in reviewing:
        if now <= add_hours(sub.admin_assigned_at, timeout_h):
            continue
        try:
            with submission_lock(sub.id):
                sub2 = db.get(Submission, sub.id)
                if (
                    sub2.status == "admin_reviewing"
                    and sub2.assigned_admin_id
                    and now > add_hours(sub2.admin_assigned_at, timeout_h)
                ):
                    tasks = _reassign_admin_after_timeout(db, sub2, now)
                    sub2.version += 1
                    db.commit()
                    dispatch_emails(db, tasks)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.exception("终审超时处理失败 submission=%s: %s", sub.id, e)


def daily_decay_if_needed(db: Session) -> None:
    today = utcnow().date().isoformat()
    if get_config(db, "last_decay_date", None) == today:
        return
    for u in db.query(User).filter(User.is_deleted.is_(False), User.role.in_(["staff", "admin"])).all():
        decay_timeout_count(u)
    set_config(db, "last_decay_date", today)
    db.commit()


def run_cron_tick() -> None:
    """一个完整 Cron 周期：超时扫描 → 邮件重试 → 每日衰减。"""
    try:
        with cron_lock("timeout_scanner"):
            db = SessionLocal()
            try:
                scan_timeouts(db)
                retry_failed_emails(db)
                daily_decay_if_needed(db)
            finally:
                db.close()
    except TimeoutError:
        logger.info("其他实例正在执行 Cron，跳过本轮")
    except Exception:  # noqa: BLE001
        logger.exception("Cron 执行失败")


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    from .config import get_settings

    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        run_cron_tick,
        "interval",
        minutes=get_settings().cron_interval_minutes,
        id="timeout_scanner",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("Cron 定时任务已启动（每 %s 分钟）", get_settings().cron_interval_minutes)
    return scheduler
