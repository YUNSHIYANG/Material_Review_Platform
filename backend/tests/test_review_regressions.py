"""回归覆盖：重复审核、撤回待办、终审纠错、父链和截止时间快照。"""
import io
from datetime import timedelta

import pytest
from fastapi import HTTPException
from freezegun import freeze_time

from app.assignment import assign_admin_review
from app.config_store import set_config
from app.flows import force_finalize, submit_admin_review, submit_staff_review, withdraw_staff_review
from app.models import AdminAuditLog, AdminReview, StaffReview, Submission, User
from app.timeout_scanner import scan_timeouts
from app.utils import utcnow

from conftest import make_submission, make_user


def _login(client, username):
    response = client.post("/api/auth/login", json={"username": username, "password": "Passw0rd!x"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload(client, headers, filename="material.zip"):
    response = client.post(
        "/api/team/submissions",
        headers=headers,
        data={"remark": "回归"},
        files={"file": (filename, io.BytesIO(b"PK\x03\x04 regression"), "application/zip")},
    )
    assert response.status_code == 200, response.text
    return response.json()["submission_id"]


def _setup(db):
    team = make_user(db, "team", real_name="回归团队")
    staff = [make_user(db, "staff", real_name=f"审核员{i}", student_id=f"S{i}") for i in range(2)]
    admins = [make_user(db, "admin", real_name=f"管理员{i}", student_id=f"A{i}") for i in range(2)]
    sub = make_submission(db, team)
    from app.assignment import assign_first_review

    assign_first_review(db, sub, team)
    db.commit()
    return team, staff, admins, sub


def _staff_row(db, sub, user):
    return db.query(StaffReview).filter_by(submission_id=sub.id, reviewer_id=user.id).one()


def test_staff_review_version_duplicate_and_withdraw_resubmit(db):
    _, staff, _, sub = _setup(db)
    reviewer = staff[0]
    first_version = sub.version

    submit_staff_review(db, sub, reviewer, True, "原意见", first_version)
    with pytest.raises(HTTPException) as stale:
        submit_staff_review(db, sub, reviewer, True, "过期意见", first_version)
    assert stale.value.status_code == 409
    with pytest.raises(HTTPException) as duplicate:
        submit_staff_review(db, sub, reviewer, True, "重复意见", sub.version)
    assert duplicate.value.status_code == 400

    withdraw_staff_review(db, sub, reviewer)
    submit_staff_review(db, sub, reviewer, False, "修订意见", sub.version)
    db.commit()

    row = _staff_row(db, sub, reviewer)
    assert row.comment == "修订意见"
    assert row.is_withdrawn is False
    assert db.get(User, reviewer.id).total_completed_count == 1


def test_force_finalize_updates_unique_review_and_snapshots_old_review(db):
    _, staff, admins, sub = _setup(db)
    submit_staff_review(db, sub, staff[0], True, "ok")
    submit_staff_review(db, sub, staff[1], True, "ok")
    admin = db.get(User, sub.assigned_admin_id)
    submit_admin_review(db, sub, admin, True, "原终审", sub.version)
    db.commit()

    operator = make_user(db, "super_admin", real_name="超管")
    force_finalize(db, sub, operator, False, "第一次强制", sub.version, "127.0.0.1", "test")
    db.commit()
    row = db.query(AdminReview).filter_by(submission_id=sub.id).one()
    row_id = row.id
    assert row.admin_id == operator.id
    assert row.final_result is False
    assert row.admin_comment == "第一次强制"
    assert row.is_system_forced is True
    assert admin.total_completed_count == 0
    assert admin.system_forced_penalty == 1
    audit = db.query(AdminAuditLog).filter_by(target_submission_id=sub.id, operation_type="FORCE_REJECT").one()
    assert audit.snapshot_before["admin_review"]["admin_id"] == admin.id
    assert audit.snapshot_before["admin_review"]["final_result"] is True

    force_finalize(db, sub, operator, True, "第二次强制", sub.version, "127.0.0.1", "test")
    db.commit()
    row = db.query(AdminReview).filter_by(submission_id=sub.id).one()
    assert row.id == row_id
    assert row.admin_id == operator.id
    assert row.final_result is True
    assert row.admin_comment == "第二次强制"
    assert admin.total_completed_count == 0
    assert admin.system_forced_penalty == 1


@freeze_time("2026-01-01 00:00:00")
def test_admin_timeout_uses_persisted_deadline_after_config_change(db):
    team, _, admins, sub = _setup(db)
    # The setup assignment captures the default 72h deadline.
    for row in sub.staff_reviews:
        row.is_timeout = True
    sub.status = "admin_reviewing"
    sub.assigned_admin_id = admins[0].id
    sub.admin_assigned_at = utcnow()
    sub.deadline_calculated_at = utcnow() + timedelta(hours=72)
    db.get(User, admins[0].id).current_pending_count = 1
    set_config(db, "timeout_hours", 1)
    db.commit()

    with freeze_time("2026-01-01 02:00:00"):
        scan_timeouts(db)
    assert sub.assigned_admin_id == admins[0].id

    fresh = make_submission(db, team, status="pending")
    tasks = assign_admin_review(db, fresh)
    db.commit()
    assert fresh.deadline_calculated_at == __import__("app.utils", fromlist=["add_hours"]).add_hours(
        utcnow(), 1
    )
    assert "1小时" in tasks[0]["content"]


def test_staff_api_stale_duplicate_withdraw_todo_and_team_withdraw_counts(client, db):
    team = make_user(db, "team", username="api_team_reg", real_name="API回归团队")
    reviewer = make_user(db, "staff", username="api_staff_reg", real_name="审核员", student_id="API-S")
    make_user(db, "staff", username="api_staff_reg2", real_name="审核员2", student_id="API-S2")
    make_user(db, "admin", username="api_admin_reg", real_name="管理员", student_id="API-A")
    make_user(db, "admin", username="api_admin_reg2", real_name="管理员2", student_id="API-A2")
    db.commit()

    team_headers = _login(client, team.username)
    sub = db.get(Submission, _upload(client, team_headers))
    staff_headers = _login(client, reviewer.username)
    original_version = sub.version

    response = client.post(
        f"/api/staff/submissions/{sub.id}/review",
        headers=staff_headers,
        json={"result": True, "comment": "原意见", "version": original_version},
    )
    assert response.status_code == 200, response.text
    db.refresh(sub)
    response = client.post(
        f"/api/staff/submissions/{sub.id}/review",
        headers=staff_headers,
        json={"result": True, "comment": "旧版本", "version": original_version},
    )
    assert response.status_code == 409
    response = client.post(
        f"/api/staff/submissions/{sub.id}/review",
        headers=staff_headers,
        json={"result": True, "comment": "重复", "version": sub.version},
    )
    assert response.status_code == 400

    response = client.post(f"/api/staff/submissions/{sub.id}/withdraw-review", headers=staff_headers)
    assert response.status_code == 200, response.text
    db.refresh(sub)
    todos = client.get("/api/staff/todos", headers=staff_headers)
    assert todos.status_code == 200
    assert any(row["submission_id"] == sub.id for row in todos.json())
    db.refresh(reviewer)
    assert reviewer.current_pending_count == 1

    response = client.post(
        f"/api/staff/submissions/{sub.id}/review",
        headers=staff_headers,
        json={"result": False, "comment": "修订意见", "version": sub.version},
    )
    assert response.status_code == 200, response.text
    db.refresh(reviewer)
    assert reviewer.total_completed_count == 1
    assert reviewer.current_pending_count == 0

    # Team withdrawal after a staff retraction must release that restored todo.
    response = client.post(f"/api/staff/submissions/{sub.id}/withdraw-review", headers=staff_headers)
    assert response.status_code == 200, response.text
    db.refresh(reviewer)
    assert reviewer.current_pending_count == 1
    db.refresh(sub)
    response = client.post(
        f"/api/team/submissions/{sub.id}/withdraw",
        headers=team_headers,
        json={"version": sub.version},
    )
    assert response.status_code == 200, response.text
    db.refresh(reviewer)
    assert reviewer.current_pending_count == 0


@pytest.mark.parametrize("state,is_timeout", [
    ("passed", False), ("rejected", False), ("withdrawn", False),
    ("returned", False), ("first_reviewing", True),
])
def test_staff_cannot_withdraw_terminal_or_timed_out_opinion(db, state, is_timeout):
    _, staff, _, sub = _setup(db)
    reviewer = staff[0]
    submit_staff_review(db, sub, reviewer, True, "原意见")
    row = _staff_row(db, sub, reviewer)
    sub.status = state
    row.is_timeout = is_timeout
    with pytest.raises(HTTPException) as rejected:
        withdraw_staff_review(db, sub, reviewer)
    assert rejected.value.status_code == 400
    assert row.is_withdrawn is False


@freeze_time("2026-02-01 00:00:00")
def test_withdrawn_staff_todo_is_timeout_scanned(client, db):
    team = make_user(db, "team", username="cron_team_reg", real_name="Cron回归团队")
    reviewer = make_user(db, "staff", username="cron_staff_reg", real_name="审核员", student_id="CRON-S")
    make_user(db, "staff", username="cron_staff_reg2", real_name="审核员2", student_id="CRON-S2")
    make_user(db, "admin", username="cron_admin_reg", real_name="管理员", student_id="CRON-A")
    make_user(db, "admin", username="cron_admin_reg2", real_name="管理员2", student_id="CRON-A2")
    db.commit()
    team_headers = _login(client, team.username)
    sub_id = _upload(client, team_headers, "cron.zip")
    sub = db.get(Submission, sub_id)
    staff_headers = _login(client, reviewer.username)
    response = client.post(
        f"/api/staff/submissions/{sub.id}/review",
        headers=staff_headers,
        json={"result": True, "comment": "待撤回", "version": sub.version},
    )
    assert response.status_code == 200, response.text
    db.refresh(sub)
    response = client.post(f"/api/staff/submissions/{sub.id}/withdraw-review", headers=staff_headers)
    assert response.status_code == 200, response.text
    row = _staff_row(db, sub, reviewer)
    row.personal_deadline = utcnow() - timedelta(minutes=1)
    db.commit()

    scan_timeouts(db)
    db.refresh(row)
    db.refresh(reviewer)
    assert row.is_timeout is True
    assert reviewer.current_pending_count == 0


def test_latest_submission_controls_parent_link_and_new_round_starts_first_review(client, db):
    team = make_user(db, "team", username="parent_team_reg", real_name="父链回归团队")
    staff = [
        make_user(db, "staff", username="parent_staff_reg1", real_name="审核员1", student_id="P-S1"),
        make_user(db, "staff", username="parent_staff_reg2", real_name="审核员2", student_id="P-S2"),
    ]
    admins = [
        make_user(db, "admin", username="parent_admin_reg1", real_name="管理员1", student_id="P-A1"),
        make_user(db, "admin", username="parent_admin_reg2", real_name="管理员2", student_id="P-A2"),
    ]
    db.commit()
    team_headers = _login(client, team.username)

    first_id = _upload(client, team_headers, "round1.zip")
    first = db.get(Submission, first_id)
    for user in staff:
        headers = _login(client, user.username)
        response = client.post(
            f"/api/staff/submissions/{first.id}/review",
            headers=headers,
            json={"result": False, "comment": "需要补充", "version": first.version},
        )
        assert response.status_code == 200, response.text
        db.refresh(first)
    admin = next(user for user in admins if user.id == first.assigned_admin_id)
    response = client.post(
        f"/api/admin/submissions/{first.id}/review",
        headers=_login(client, admin.username),
        json={"final_result": False, "admin_comment": "未通过", "version": first.version},
    )
    assert response.status_code == 200, response.text
    db.refresh(first)
    assert first.status == "rejected"

    second_id = _upload(client, team_headers, "round2.zip")
    second = db.get(Submission, second_id)
    assert second.parent_submission_id == first.id
    assert second.status == "admin_reviewing"
    admin2 = next(user for user in admins if user.id == second.assigned_admin_id)
    response = client.post(
        f"/api/admin/submissions/{second.id}/review",
        headers=_login(client, admin2.username),
        json={"final_result": True, "admin_comment": "通过", "version": second.version},
    )
    assert response.status_code == 200, response.text
    db.refresh(second)
    assert second.status == "passed"

    third_id = _upload(client, team_headers, "round3.zip")
    third = db.get(Submission, third_id)
    assert third.parent_submission_id is None
    assert third.status == "first_reviewing"
    assert len(third.staff_reviews) == 2
