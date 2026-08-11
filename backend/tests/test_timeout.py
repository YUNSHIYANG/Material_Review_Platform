"""超时判定测试：初审超时跳过、终审超时重派、全局阈值兜底。"""
from datetime import timedelta

from freezegun import freeze_time

from app.assignment import assign_first_review
from app.flows import _reassign_admin_after_timeout, check_and_handle_timeout
from app.models import StaffReview, Submission, User
from app.utils import utcnow

from conftest import make_submission, make_user

BASE = "2026-01-01 00:00:00"


def _setup(db, n_admins=2):
    team = make_user(db, "team", real_name="财务部")
    s1 = make_user(db, "staff", real_name="甲", student_id="S1")
    s2 = make_user(db, "staff", real_name="乙", student_id="S2")
    admins = [make_user(db, "admin", real_name=f"管理员{i}", student_id=f"A{i}") for i in range(n_admins)]
    with freeze_time(BASE):
        sub = make_submission(db, team)
        db.flush()
        assign_first_review(db, sub, team)
        db.commit()
    return team, s1, s2, admins, sub


def _enter_admin_phase(db, sub, admins):
    """跳过初审阶段，直接进入终审独占派发态。"""
    for sr in sub.staff_reviews:
        sr.personal_deadline = utcnow() + timedelta(days=30)  # 防止初审超时干扰
        sr.is_timeout = True  # 视为已超时（不再参与扫描）
    sub.status = "admin_reviewing"
    sub.assigned_admin_id = admins[0].id
    sub.admin_assigned_at = utcnow()
    sub.is_admin_pending_deducted = False
    db.get(User, admins[0].id).current_pending_count += 1
    db.commit()


@freeze_time(BASE)
def test_staff_timeout_skips_to_admin(db):
    team, s1, s2, admins, sub = _setup(db)
    with freeze_time("2026-01-04 01:00:00"):  # 已过 72h
        tasks = check_and_handle_timeout(db, sub)
        db.commit()
    assert sub.status == "admin_reviewing"
    assert sub.first_review_skip_reason == "timeout"
    assert sub.assigned_admin_id in (admins[0].id, admins[1].id)
    for sr in db.query(StaffReview).filter_by(submission_id=sub.id).all():
        assert sr.is_timeout is True


@freeze_time(BASE)
def test_admin_timeout_reassigns(db):
    team, s1, s2, admins, sub = _setup(db)
    _enter_admin_phase(db, sub, admins)
    with freeze_time("2026-01-04 01:00:00"):  # 已过 72h
        tasks = check_and_handle_timeout(db, sub)
        db.commit()
    assert sub.status == "admin_reviewing"
    assert sub.assigned_admin_id == admins[1].id  # 换人
    assert sub.total_reassign_count == 1
    assert sub.cycle_count == 0  # 换人 → 重置
    assert db.get(User, admins[0].id).current_pending_count == 0
    assert db.get(User, admins[1].id).current_pending_count == 1


@freeze_time(BASE)
def test_global_threshold_suspends_with_three_admins(db):
    """3名管理员轮转：交替循环不触发（去重数=3），累计重分配≥5 触发全局兜底。"""
    team, s1, s2, admins, sub = _setup(db, n_admins=3)
    _enter_admin_phase(db, sub, admins)

    for _ in range(5):
        with freeze_time("2026-01-04 01:00:00"):
            old_id = sub.assigned_admin_id
            sub.admin_assigned_at = utcnow() - timedelta(hours=73)  # 制造超时
            tasks = _reassign_admin_after_timeout(db, sub, utcnow())
            db.commit()
            if sub.status == "pending_admin_intervention":
                break

    assert sub.status == "pending_admin_intervention"
    assert sub.assigned_admin_id is None
    assert sub.total_reassign_count >= 5
    # 历史派发去重数 ≥3，说明挂起源于全局阈值而非交替循环
    distinct = len({x for x in sub.reassign_history if x != -1})
    assert distinct >= 3


@freeze_time(BASE)
def test_alternating_cycle_detection(db):
    """2名管理员交替：total_reassign_count≥3 且去重数≤2 → 立即挂起（交替循环）。"""
    team, s1, s2, admins, sub = _setup(db, n_admins=2)
    _enter_admin_phase(db, sub, admins)

    for _ in range(5):
        with freeze_time("2026-01-04 01:00:00"):
            sub.admin_assigned_at = utcnow() - timedelta(hours=73)
            tasks = _reassign_admin_after_timeout(db, sub, utcnow())
            db.commit()
            if sub.status == "pending_admin_intervention":
                break

    assert sub.status == "pending_admin_intervention"
    assert sub.assigned_admin_id is None
    assert sub.total_reassign_count >= 3  # 交替循环在重分配次数≥3时即触发
    distinct = len({x for x in sub.reassign_history if x != -1})
    assert distinct <= 2
