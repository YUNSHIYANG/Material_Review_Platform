"""状态机测试：完整通过链路、撤回、初审撤回补时、挂起拦截。"""
from datetime import timedelta

import pytest
from fastapi import HTTPException
from freezegun import freeze_time

from app.assignment import assign_admin_review, assign_first_review
from app.flows import (
    force_finalize,
    submit_admin_review,
    submit_staff_review,
    withdraw_staff_review,
    withdraw_submission,
)
from app.models import AdminReview, StaffReview, Submission, User

from conftest import make_submission, make_user


def _setup(db):
    team = make_user(db, "team", real_name="财务部")
    s1 = make_user(db, "staff", real_name="审核员甲", student_id="S1")
    s2 = make_user(db, "staff", real_name="审核员乙", student_id="S2")
    a1 = make_user(db, "admin", real_name="管理员A", student_id="A1")
    a2 = make_user(db, "admin", real_name="管理员B", student_id="A2")
    sub = make_submission(db, team)
    db.flush()
    assign_first_review(db, sub, team)
    db.commit()
    return team, s1, s2, a1, a2, sub


def _staff_review(db, sub, reviewer):
    return db.query(StaffReview).filter_by(submission_id=sub.id, reviewer_id=reviewer.id).one()


def test_full_pass_chain(db):
    team, s1, s2, a1, a2, sub = _setup(db)
    assert sub.status == "first_reviewing"

    tasks = submit_staff_review(db, sub, s1, True, "材料齐全")
    assert sub.status == "first_reviewing"
    assert db.get(User, s1.id).total_completed_count == 1

    tasks = submit_staff_review(db, sub, s2, True, "")
    assert sub.status == "admin_reviewing"
    assert sub.assigned_admin_id in (a1.id, a2.id)

    admin_id = sub.assigned_admin_id
    admin = db.get(User, admin_id)
    tasks = submit_admin_review(db, sub, admin, True, "同意", sub.version)
    db.commit()
    assert sub.status == "passed"
    ar = db.query(AdminReview).filter_by(submission_id=sub.id).one()
    assert ar.final_result is True
    assert admin.total_completed_count == 1
    assert any("已通过" in t["content"] for t in tasks)


def test_reject_requires_comment(db):
    team, s1, s2, a1, a2, sub = _setup(db)
    with pytest.raises(HTTPException):
        submit_staff_review(db, sub, s1, False, "")


def test_team_withdraw_rolls_back_counts(db):
    team, s1, s2, a1, a2, sub = _setup(db)
    submit_staff_review(db, sub, s1, True, "ok")
    # 进入终审
    submit_staff_review(db, sub, s2, True, "ok")
    admin = db.get(User, sub.assigned_admin_id)
    assert admin.current_pending_count == 1
    assert db.get(User, s1.id).total_completed_count == 1

    withdraw_submission(db, sub, team, sub.version)
    db.commit()
    assert sub.status == "withdrawn"
    assert sub.assigned_admin_id is None
    assert admin.current_pending_count == 0
    assert db.get(User, s1.id).total_completed_count == 0


def test_withdraw_blocked_when_intervention(db):
    team, s1, s2, a1, a2, sub = _setup(db)
    # 只有1名管理员 → 挂起
    a2.is_deleted = True
    db.flush()
    assign_admin_review(db, sub)
    db.commit()
    assert sub.status == "pending_admin_intervention"
    with pytest.raises(HTTPException) as e:
        withdraw_submission(db, sub, team, sub.version)
    assert e.value.status_code == 403


@freeze_time("2026-01-01 00:00:00")
def test_staff_withdraw_scenario_a_delay(db):
    team, s1, s2, a1, a2, sub = _setup(db)
    sr = _staff_review(db, sub, s1)
    # 仅s1提交（有效意见数<2）；将s1截止时间调到30分钟后
    submit_staff_review(db, sub, s1, True, "ok")
    sr.personal_deadline = __import__("app.utils", fromlist=["utcnow"]).utcnow() + timedelta(hours=1)
    db.commit()
    from freezegun import freeze_time as ft

    with ft("2026-01-01 00:30:00"):
        result = withdraw_staff_review(db, sub, s1)
    db.commit()
    assert "延长" in result["message"]
    assert _staff_review(db, sub, s1).delay_used is True


@freeze_time("2026-01-01 00:00:00")
def test_staff_withdraw_scenario_b_no_delay(db):
    team, s1, s2, a1, a2, sub = _setup(db)
    submit_staff_review(db, sub, s1, True, "ok")
    submit_staff_review(db, sub, s2, True, "ok")
    # 两位均提交 → 撤回时不延长
    from freezegun import freeze_time as ft

    with ft("2026-01-01 01:00:00"):
        result = withdraw_staff_review(db, sub, s1)
    db.commit()
    assert "二审已完成" in result["message"]
    assert _staff_review(db, sub, s1).delay_used is False


def test_force_finalize_rolls_back_admin_completed(db):
    team, s1, s2, a1, a2, sub = _setup(db)
    submit_staff_review(db, sub, s1, True, "ok")
    submit_staff_review(db, sub, s2, True, "ok")
    admin = db.get(User, sub.assigned_admin_id)
    submit_admin_review(db, sub, admin, True, "通过", sub.version)
    db.commit()
    assert admin.total_completed_count == 1

    super_op = make_user(db, "super_admin", real_name="超管", password_changed=True)
    force_finalize(db, sub, super_op, False, "补充说明", sub.version, "127.0.0.1", "test")
    db.commit()
    assert sub.status == "rejected"
    assert admin.total_completed_count == 0
    assert admin.system_forced_penalty == 1
    assert sub.reassign_history[-1] == -1
    assert sub.intervention_reset_count == 1
