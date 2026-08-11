"""业务流程（状态机核心操作）：提交/撤回/审核/终结/干预。

所有写操作在调用方持有的 submission 分布式锁 + version 乐观锁校验后进行；
事务末尾统一调用 check_and_handle_timeout 作为 Cron 兜底。
"""
from datetime import timedelta

from fastapi import HTTPException

from sqlalchemy.orm import Session

from .assignment import assign_admin_review
from .audit import build_snapshot, write_audit
from .config_store import get_effective_timeout
from .counters import apply_timeout_penalty, decr_completed, decr_pending, incr_completed, incr_pending
from .email_service import (
    build_admin_short_alert,
    build_assignment_email,
    build_passed_email,
    build_rejected_email,
    build_returned_email,
)
from .models import AdminReview, StaffReview, Submission, User
from .utils import add_hours, utcnow


def check_version(submission: Submission, version: int | None) -> None:
    if version is not None and submission.version != version:
        raise HTTPException(status_code=409, detail="工单状态已变化，请刷新页面重试")


def valid_opinions(submission: Submission) -> list[StaffReview]:
    return [
        sr
        for sr in submission.staff_reviews
        if not sr.is_withdrawn and not sr.is_timeout and sr.submitted_at is not None
    ]


# ---------------------------------------------------------------- 初审
def submit_staff_review(
    db: Session, submission: Submission, reviewer: User, result: bool, comment: str
) -> list[dict]:
    now = utcnow()
    sr = next((s for s in submission.staff_reviews if s.reviewer_id == reviewer.id), None)
    if sr is None:
        raise HTTPException(status_code=403, detail="您未被分配该工单的初审任务")
    if sr.is_timeout or (sr.personal_deadline and now > sr.personal_deadline):
        raise HTTPException(status_code=400, detail="该任务已超时，请刷新页面")
    if submission.status not in ("first_reviewing", "admin_reviewing"):
        raise HTTPException(status_code=400, detail="当前工单状态不允许提交初审意见")
    if not result and not (comment or "").strip():
        raise HTTPException(status_code=400, detail="不通过必须填写意见内容")

    sr.result = result
    sr.comment = comment
    sr.submitted_at = now
    sr.is_withdrawn = False
    sr.is_counted = True
    decr_pending(reviewer)
    incr_completed(reviewer)

    tasks: list[dict] = []
    if submission.status == "first_reviewing" and len(valid_opinions(submission)) >= 2:
        # 两位均提交 → 进入终审（若为超管补审场景，需清空 skip 原因并重置计数器）
        if submission.first_review_skip_reason == "insufficient_staff":
            submission.first_review_skip_reason = None
            submission.cycle_count = 0
            submission.total_reassign_count = 0
            hist = list(submission.reassign_history or [])
            hist.append(-1)
            submission.reassign_history = hist
            submission.intervention_reset_count += 1
        tasks += assign_admin_review(db, submission, now=now)
    submission.version += 1
    db.flush()
    tasks += check_and_handle_timeout(db, submission, now=now)
    return tasks


def withdraw_staff_review(db: Session, submission: Submission, reviewer: User) -> dict:
    now = utcnow()
    sr = next((s for s in submission.staff_reviews if s.reviewer_id == reviewer.id), None)
    if sr is None or sr.submitted_at is None or sr.is_withdrawn:
        raise HTTPException(status_code=400, detail="没有可撤回的初审意见")
    if db.query(AdminReview).filter(AdminReview.submission_id == submission.id).first():
        raise HTTPException(status_code=400, detail="管理员已提交终审意见，无法撤回")
    if now > sr.personal_deadline:
        raise HTTPException(status_code=400, detail="任务已超时，无法撤回")

    # 场景判定：有效意见数（撤回前，含本人）
    valid_before = len(valid_opinions(submission))
    if sr.is_counted:
        decr_completed(reviewer)
    sr.is_withdrawn = True
    sr.withdrawn_at = now
    sr.is_counted = False

    if valid_before < 2:
        # 场景A：可补时（仅撤回者本人 +3小时，消耗 delay_used 额度）
        remain = sr.personal_deadline - now
        if timedelta(0) < remain < timedelta(hours=3):
            if not sr.delay_used:
                sr.personal_deadline = add_hours(sr.personal_deadline, 3)
                sr.delay_used = True
                message = "已为您延长3小时补时额度"
            else:
                message = "延时额度已用完，请尽快提交，逾期将记为超时"
        else:
            message = "撤回成功，请在截止时间前重新提交"
    else:
        # 场景B：两位均已提交，截止时间不再后移
        message = "二审已完成，撤回后请尽快重新提交，超时将记为未审"

    submission.version += 1
    db.flush()
    check_and_handle_timeout(db, submission, now=now)
    return {"message": message, "personal_deadline": sr.personal_deadline}


# ---------------------------------------------------------------- 提交人撤回
def withdraw_submission(db: Session, submission: Submission, team: User, version: int | None) -> None:
    now = utcnow()
    check_version(submission, version)
    if submission.team_id != team.id:
        raise HTTPException(status_code=403, detail="无权操作该工单")
    if submission.status == "pending_admin_intervention":
        raise HTTPException(status_code=403, detail="该工单处于加急处理中，无法撤回")
    if submission.status in ("rejected", "withdrawn"):
        raise HTTPException(status_code=400, detail="工单已终结，无法撤回")

    submission.status = "withdrawn"
    submission.withdrawn_at = now

    # 管理员占用与工作量处理（与打回共用同一规则）：
    # - 终审已提交（非强制终结）：待办在提交终审时已扣减，此处仅回退工作量
    # - 终审未提交：按 is_admin_pending_deducted 决定是否释放待办
    if submission.assigned_admin_id:
        admin = db.get(User, submission.assigned_admin_id)
        ar = db.query(AdminReview).filter(AdminReview.submission_id == submission.id).first()
        if admin:
            if ar is not None and not ar.is_system_forced:
                decr_completed(admin)
            elif ar is None and not submission.is_admin_pending_deducted:
                decr_pending(admin)
                submission.is_admin_pending_deducted = True
        submission.assigned_admin_id = None

    # 审核意见作废：回退已计工作量；未提交审核员的待办一并释放（保证算法公平）
    for sr in submission.staff_reviews:
        if sr.is_counted:
            decr_completed(db.get(User, sr.reviewer_id))
            sr.is_counted = False
        if not sr.is_withdrawn and not sr.is_timeout and sr.submitted_at is None:
            decr_pending(db.get(User, sr.reviewer_id))
            sr.is_withdrawn = True
            sr.withdrawn_at = now

    submission.version += 1
    db.flush()


# ---------------------------------------------------------------- 超管打回已通过材料
def return_passed_submission(
    db: Session,
    submission: Submission,
    operator: User,
    comment: str,
    version: int | None,
    ip: str | None,
    ua: str | None,
) -> list[dict]:
    now = utcnow()
    check_version(submission, version)
    if submission.status != "passed":
        raise HTTPException(status_code=400, detail="仅已通过状态的工单可打回")
    if not (comment or "").strip():
        raise HTTPException(status_code=400, detail="打回必须填写意见")

    before = build_snapshot(db, submission)

    # 管理员工作量/占用回退（规则与撤回一致）
    if submission.assigned_admin_id:
        admin = db.get(User, submission.assigned_admin_id)
        ar = db.query(AdminReview).filter(AdminReview.submission_id == submission.id).first()
        if admin:
            if ar is not None and not ar.is_system_forced:
                decr_completed(admin)
            elif ar is None and not submission.is_admin_pending_deducted:
                decr_pending(admin)
                submission.is_admin_pending_deducted = True
        submission.assigned_admin_id = None

    # 初审意见作废：回退已计工作量
    for sr in submission.staff_reviews:
        if sr.is_counted:
            decr_completed(db.get(User, sr.reviewer_id))
            sr.is_counted = False
        if not sr.is_withdrawn and not sr.is_timeout and sr.submitted_at is None:
            decr_pending(db.get(User, sr.reviewer_id))
            sr.is_withdrawn = True
            sr.withdrawn_at = now

    submission.status = "returned"
    submission.return_comment = comment
    submission.returned_at = now
    submission.version += 1
    db.flush()

    after = build_snapshot(db, submission)
    write_audit(
        db,
        operator.id,
        "RETURN_PASSED",
        target_submission_id=submission.id,
        snapshot_before=before,
        snapshot_after=after,
        remark=f"超管打回已通过材料，意见：{comment}",
        ip_address=ip,
        user_agent=ua,
    )
    return [build_returned_email(submission, comment)]


# ---------------------------------------------------------------- 终审
def submit_admin_review(
    db: Session, submission: Submission, admin: User, final_result: bool, comment: str, version: int | None
) -> list[dict]:
    now = utcnow()
    check_version(submission, version)
    if submission.status != "admin_reviewing" or submission.assigned_admin_id != admin.id:
        raise HTTPException(status_code=403, detail="该工单未派发给您或状态已变化")
    if not final_result and not (comment or "").strip():
        raise HTTPException(status_code=400, detail="驳回必须填写终审意见")

    decr_pending(admin)
    incr_completed(admin)
    db.add(
        AdminReview(
            submission_id=submission.id,
            admin_id=admin.id,
            final_result=final_result,
            admin_comment=comment,
            reviewed_at=now,
            is_reassigned=submission.total_reassign_count > 0,
        )
    )
    submission.status = "passed" if final_result else "rejected"
    submission.version += 1  # admin_assigned_at 不更新（避免无效刷新）
    db.flush()

    tasks = [build_passed_email(submission) if final_result else build_rejected_email(submission, comment)]
    return tasks


# ---------------------------------------------------------------- 超管强制终结
def force_finalize(
    db: Session,
    submission: Submission,
    operator: User,
    final_result: bool,
    comment: str,
    version: int | None,
    ip: str | None,
    ua: str | None,
) -> list[dict]:
    now = utcnow()
    check_version(submission, version)
    # 允许对已终结（passed/rejected）工单强制改判，此时命中“管理员已提交终审”回退分支
    if submission.status not in (
        "pending_admin_intervention",
        "admin_reviewing",
        "first_reviewing",
        "pending",
        "passed",
        "rejected",
    ):
        raise HTTPException(status_code=400, detail="该工单状态不支持强制终结")

    affected_admin = db.get(User, submission.assigned_admin_id) if submission.assigned_admin_id else None
    before = build_snapshot(db, submission, admin=affected_admin)

    existing = db.query(AdminReview).filter(AdminReview.submission_id == submission.id).first()
    if existing:
        # 管理员已提交终审：工作量回退 -1，惩罚 +1；待办在提交时已扣减，不再重复扣
        ar_admin = db.get(User, existing.admin_id)
        if ar_admin:
            decr_completed(ar_admin)
            ar_admin.system_forced_penalty += 1
    else:
        # 管理员未提交终审：工作量不计入任何人；按 is_admin_pending_deducted 决定是否释放待办
        if affected_admin and not submission.is_admin_pending_deducted:
            decr_pending(affected_admin)
            submission.is_admin_pending_deducted = True
        if affected_admin:
            affected_admin.system_forced_penalty += 1

    if existing is None:
        db.add(
            AdminReview(
                submission_id=submission.id,
                admin_id=(affected_admin.id if affected_admin else operator.id),
                final_result=final_result,
                admin_comment=comment,
                reviewed_at=now,
                is_system_forced=True,
            )
        )

    # 重置循环计数器并追加 -1 标记，intervention_reset_count +1
    submission.cycle_count = 0
    submission.total_reassign_count = 0
    hist = list(submission.reassign_history or [])
    hist.append(-1)
    submission.reassign_history = hist
    submission.intervention_reset_count += 1
    submission.status = "passed" if final_result else "rejected"
    submission.assigned_admin_id = None
    submission.version += 1
    db.flush()

    after = build_snapshot(db, submission)
    write_audit(
        db,
        operator.id,
        "FORCE_PASS" if final_result else "FORCE_REJECT",
        target_submission_id=submission.id,
        snapshot_before=before,
        snapshot_after=after,
        remark=f"超管强制终结；工作量归零快照已记录。意见：{comment}",
        ip_address=ip,
        user_agent=ua,
    )
    tasks = [build_passed_email(submission) if final_result else build_rejected_email(submission, comment)]
    return tasks


# ---------------------------------------------------------------- 超管重新派发
def reassign_from_intervention(
    db: Session,
    submission: Submission,
    operator: User,
    version: int | None,
    ip: str | None,
    ua: str | None,
    force_admin_id: int | None = None,
) -> list[dict]:
    now = utcnow()
    check_version(submission, version)
    if submission.status != "pending_admin_intervention":
        raise HTTPException(status_code=400, detail="仅待超管介入状态的工单可重新派发")

    from .assignment import get_active_users

    admins = get_active_users(db, "admin")
    if len(admins) < 2:
        raise HTTPException(status_code=400, detail="普通管理员数量不足2人，无法重新派发")

    before = build_snapshot(db, submission)
    # 必须重置计数器、追加 -1、递增 intervention_reset_count
    submission.cycle_count = 0
    submission.total_reassign_count = 0
    hist = list(submission.reassign_history or [])
    hist.append(-1)
    submission.reassign_history = hist
    submission.intervention_reset_count += 1

    target = next((a for a in admins if a.id == force_admin_id), None) if force_admin_id else None
    old_id = submission.assigned_admin_id
    tasks = []
    if target is not None:
        submission.cycle_count = 0
        hist.append(target.id)
        submission.reassign_history = hist
        submission.assigned_admin_id = target.id
        submission.admin_assigned_at = now
        submission.deadline_calculated_at = add_hours(now, get_effective_timeout(db))
        submission.is_admin_pending_deducted = False
        submission.status = "admin_reviewing"
        incr_pending(target)
        tasks.append(build_assignment_email(submission, target, "超管已介入重新派发本工单。"))
    else:
        tasks = assign_admin_review(db, submission, now=now, old_admin_id=old_id)

    submission.version += 1
    db.flush()
    after = build_snapshot(db, submission)
    write_audit(
        db,
        operator.id,
        "REASSIGN_FROM_INTERVENTION",
        target_submission_id=submission.id,
        snapshot_before=before,
        snapshot_after=after,
        remark=f"超管重新派发，新管理员ID: {submission.assigned_admin_id}",
        ip_address=ip,
        user_agent=ua,
    )
    return tasks


# ---------------------------------------------------------------- 超管补充初审
def supplement_first_review(
    db: Session,
    submission: Submission,
    operator: User,
    staff_ids: list[int],
    version: int | None,
    ip: str | None,
    ua: str | None,
) -> list[dict]:
    now = utcnow()
    check_version(submission, version)
    if submission.first_review_skip_reason != "insufficient_staff":
        raise HTTPException(status_code=400, detail="仅初审员不足跳过的工单可补充初审")
    if submission.assigned_admin_id is not None:
        raise HTTPException(status_code=400, detail="该工单已派发终审管理员，无法补充初审")
    if len(staff_ids) != 2 or len(set(staff_ids)) != 2:
        raise HTTPException(status_code=400, detail="请指定2名不同的审核员")

    from .assignment import get_active_users

    staffs = {u.id: u for u in get_active_users(db, "staff")}
    picked = [staffs.get(i) for i in staff_ids]
    if any(p is None for p in picked):
        raise HTTPException(status_code=400, detail="所选审核员无效")

    before = build_snapshot(db, submission)
    timeout_h = get_effective_timeout(db)
    submission.status = "first_reviewing"
    submission.deadline_calculated_at = add_hours(now, timeout_h)
    tasks = []
    for s in picked:
        incr_pending(s)
        db.add(
            StaffReview(
                submission_id=submission.id,
                reviewer_id=s.id,
                assigned_at=now,
                personal_deadline=add_hours(now, timeout_h),
            )
        )
        tasks.append(build_assignment_email(submission, s, "超管已指定您补充初审本工单。"))
    submission.version += 1
    db.flush()

    after = build_snapshot(db, submission)
    write_audit(
        db,
        operator.id,
        "FORCE_SUPPLEMENT_FIRST_REVIEW",
        target_submission_id=submission.id,
        snapshot_before=before,
        snapshot_after=after,
        remark=f"超管补充初审，指定审核员: {staff_ids}",
        ip_address=ip,
        user_agent=ua,
    )
    return tasks


# ---------------------------------------------------------------- 超时判定（Cron 兜底，亦被写操作事务末尾调用）
def _staff_timeout_scan(db: Session, submission: Submission, now) -> list[dict]:
    tasks: list[dict] = []
    timed_out = [
        sr
        for sr in submission.staff_reviews
        if not sr.is_timeout and not sr.is_withdrawn and sr.submitted_at is None and now > sr.personal_deadline
    ]
    for sr in timed_out:
        sr.is_timeout = True
        reviewer = db.get(User, sr.reviewer_id)
        if reviewer:
            decr_pending(reviewer)
            apply_timeout_penalty(reviewer)
    if timed_out and submission.status == "first_reviewing":
        submission.status = "admin_reviewing"
        submission.first_review_skip_reason = "timeout"
        submission.deadline_calculated_at = add_hours(now, get_effective_timeout(db))
        if submission.assigned_admin_id is None:
            tasks += assign_admin_review(db, submission, now=now)
    return tasks


def _admin_timeout_scan(db: Session, submission: Submission, now) -> list[dict]:
    if submission.status != "admin_reviewing" or not submission.assigned_admin_id or not submission.admin_assigned_at:
        return []
    if now <= add_hours(submission.admin_assigned_at, get_effective_timeout(db)):
        return []
    return _reassign_admin_after_timeout(db, submission, now)


def _reassign_admin_after_timeout(db: Session, submission: Submission, now) -> list[dict]:
    from .assignment import get_active_users, sort_key
    from .config_store import get_effective_cycle_threshold, get_effective_global_threshold

    old_id = submission.assigned_admin_id
    old_admin = db.get(User, old_id) if old_id else None
    if old_admin:
        if not submission.is_admin_pending_deducted:
            decr_pending(old_admin)  # 仅此处扣减一次
            submission.is_admin_pending_deducted = True
        apply_timeout_penalty(old_admin)

    hist = list(submission.reassign_history or [])
    if old_id:
        hist.append(old_id)
    submission.reassign_history = hist
    submission.total_reassign_count += 1
    submission.assigned_admin_id = None

    admins = get_active_users(db, "admin")
    if len(admins) < 2:
        submission.status = "pending_admin_intervention"
        write_audit(
            db, 0, "ADMIN_INTERVENTION_TRIGGERED",
            target_submission_id=submission.id,
            remark="终审超时重分配时发现管理员不足，工单挂起",
        )
        return [build_admin_short_alert(submission, "管理员不足")]

    new = sorted(admins, key=sort_key)[0]
    if new.id == old_id:
        submission.cycle_count += 1
    else:
        submission.cycle_count = 0

    distinct = len({x for x in hist if x != -1})
    cycle_th = get_effective_cycle_threshold(db)
    global_th = get_effective_global_threshold(db)

    if submission.total_reassign_count >= 3 and distinct <= 2:
        submission.status = "pending_admin_intervention"
        write_audit(
            db, 0, "TIMEOUT_CYCLE_ALERT",
            target_submission_id=submission.id,
            remark=f"交替循环检测触发：total_reassign_count={submission.total_reassign_count}，去重管理员数={distinct}",
        )
        return [build_admin_short_alert(submission, "交替循环")]

    if submission.cycle_count >= cycle_th or submission.total_reassign_count >= global_th:
        submission.status = "pending_admin_intervention"
        write_audit(
            db, 0, "TIMEOUT_CYCLE_ALERT",
            target_submission_id=submission.id,
            remark=f"双阈值兜底触发：cycle_count={submission.cycle_count}(≥{cycle_th}) 或 "
            f"total_reassign_count={submission.total_reassign_count}(≥{global_th})",
        )
        return [build_admin_short_alert(submission, "同人循环/全局重分配超限")]

    hist.append(new.id)
    submission.reassign_history = hist
    submission.assigned_admin_id = new.id
    submission.admin_assigned_at = now
    submission.deadline_calculated_at = add_hours(now, get_effective_timeout(db))
    submission.is_admin_pending_deducted = False
    submission.status = "admin_reviewing"
    incr_pending(new)
    prev = [db.get(User, x).real_name for x in hist if x != -1 and x != new.id and db.get(User, x)]
    note = ""
    if prev:
        note = "历史派发记录说明：" + "、".join(prev) + " 曾先后收到该工单但均未及时处理。\n"
    return [build_assignment_email(submission, new, note)]


def check_and_handle_timeout(db: Session, submission: Submission, now=None) -> list[dict]:
    """所有涉及截止时间比较的写操作事务末尾强制调用；Cron 亦复用。"""
    now = now or utcnow()
    tasks = _staff_timeout_scan(db, submission, now)
    tasks += _admin_timeout_scan(db, submission, now)
    if tasks:
        db.flush()
    return tasks
