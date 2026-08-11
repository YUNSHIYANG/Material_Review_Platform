"""核心分配算法（文档第 6 章）：双重排序负载均衡 + 同团队规避 + 超时降权 + 确定性兜底。

优先级：
1) current_pending_count 最小
2) total_completed_count + system_forced_penalty*100 最小；若 timeout_count>0 再 + 1000+timeout_count*100（垫底）
3) id 最小（确定性终选）
"""
from sqlalchemy.orm import Session

from .audit import write_audit
from .config_store import get_effective_pending_multiplier, get_effective_timeout
from .counters import incr_pending
from .database import supports_row_lock
from .email_service import (
    build_admin_short_alert,
    build_assignment_email,
    build_insufficient_staff_alert,
)
from .models import StaffReview, Submission, User
from .utils import add_hours, normalize_name, utcnow

ACTIVE_STATUSES = ("pending", "first_reviewing", "admin_reviewing", "pending_admin_intervention")


def sort_key(user: User) -> tuple:
    virtual = user.total_completed_count + user.system_forced_penalty * 100
    if user.timeout_count > 0:
        virtual += 1000 + user.timeout_count * 100
    return (user.current_pending_count, virtual, user.id)


def get_active_users(db: Session, role: str) -> list[User]:
    q = db.query(User).filter(User.role == role, User.is_deleted.is_(False))
    return q.all()


def is_team_collision(staff: User, team: User) -> bool:
    """初审同团队规避：优先学工号匹配，未命中降级为标准姓名匹配。"""
    member_ids = [str(x).strip() for x in (team.member_student_ids or [])]
    member_names = {normalize_name(x) for x in (team.member_names or []) if normalize_name(x)}
    sid = (staff.student_id or "").strip()
    name = normalize_name(staff.real_name or "")
    if sid:
        if sid in member_ids:
            return True
        # 学工号未命中 → 降级姓名匹配
        if name and name in member_names:
            return True
    else:
        if name and name in member_names:
            return True
    return False


def assigned_total(u: User) -> int:
    """历史接单总量 = 已完成 + 当前待办。"""
    return u.total_completed_count + u.current_pending_count


def pick_best(db: Session, users: list[User], n: int, excluded_ids: set[int] | None = None) -> list[User]:
    """四级优先级分配（参数倍数由超管前端配置）：

    1) 候选过滤：待办数 < 平均待办数 * 倍数（默认 2）才参与本轮分配
    2) 按历史接单总量升序（接得越少越靠前）
    3) 总量持平时，待办数少者优先
    4) 仍并列则随机
    """
    import random

    candidates = [u for u in users if not excluded_ids or u.id not in excluded_ids]
    if not candidates:
        return []

    avg = sum(u.current_pending_count for u in candidates) / len(candidates)
    threshold = avg * get_effective_pending_multiplier(db)
    pool = [u for u in candidates if u.current_pending_count < threshold]
    if not pool:
        # 兜底：全部被阈值排除时退化为全量候选，避免无人可派
        pool = candidates

    def key(u: User) -> tuple:
        return (assigned_total(u), u.current_pending_count)

    pool.sort(key=key)
    result: list[User] = []
    i = 0
    while i < len(pool) and len(result) < n:
        j = i
        while j < len(pool) and key(pool[j]) == key(pool[i]):
            j += 1
        group = pool[i:j]
        random.shuffle(group)
        result.extend(group)
        i = j
    return result[:n]


def _active_submissions(db: Session, submission_id: int) -> Submission:
    # 事务内重新读取并加行锁（PG/MySQL 生效；SQLite 测试跳过）
    q = db.query(Submission).filter(Submission.id == submission_id)
    if supports_row_lock(db):
        q = q.with_for_update()
    return q.one()


def assign_first_review(db: Session, submission: Submission, team: User) -> list[dict]:
    """分配2名初审员；候选池不足2人 → 跳过初审进入终审并告警。返回邮件任务列表。"""
    now = utcnow()
    timeout_h = get_effective_timeout(db)
    staffs = get_active_users(db, "staff")
    excluded = [s for s in staffs if is_team_collision(s, team)]
    excluded_ids = {s.id for s in excluded}
    candidates = [s for s in staffs if s.id not in excluded_ids]

    if len(candidates) < 2:
        submission.first_review_skip_reason = "insufficient_staff"
        submission.deadline_calculated_at = add_hours(now, timeout_h)
        tasks = [build_insufficient_staff_alert(submission, candidates, excluded, [])]
        tasks += assign_admin_review(db, submission, now=now)
        return tasks

    picks = pick_best(db, staffs, 2, excluded_ids)
    submission.status = "first_reviewing"
    if submission.first_assigned_at is None:
        submission.first_assigned_at = now  # 仅写一次，永不覆盖
    submission.deadline_calculated_at = add_hours(now, timeout_h)
    tasks = []
    for s in picks:
        incr_pending(s)
        db.add(
            StaffReview(
                submission_id=submission.id,
                reviewer_id=s.id,
                assigned_at=now,
                personal_deadline=add_hours(now, timeout_h),
            )
        )
        tasks.append(build_assignment_email(submission, s))
    return tasks


def assign_admin_review(db: Session, submission: Submission, now=None, old_admin_id: int | None = None) -> list[dict]:
    """终审独占派发1名管理员。候选池 <2 → 直接挂起待超管介入。返回邮件任务列表。"""
    now = now or utcnow()
    timeout_h = get_effective_timeout(db)
    admins = get_active_users(db, "admin")

    if len(admins) < 2:
        # 候选池预检：不进入重分配循环，直接挂起
        submission.status = "pending_admin_intervention"
        submission.assigned_admin_id = None
        write_audit(
            db, 0, "ADMIN_INTERVENTION_TRIGGERED",
            target_submission_id=submission.id,
            remark="终审候选池普通管理员不足2人，工单挂起",
        )
        return [build_admin_short_alert(submission, "管理员不足")]

    new = pick_best(db, admins, 1)[0]
    if old_admin_id is not None:
        if new.id == old_admin_id:
            submission.cycle_count += 1
        else:
            submission.cycle_count = 0
    else:
        submission.cycle_count = 0

    history = list(submission.reassign_history or [])
    history.append(new.id)
    submission.reassign_history = history
    submission.assigned_admin_id = new.id
    submission.admin_assigned_at = now
    submission.deadline_calculated_at = add_hours(now, timeout_h)
    submission.is_admin_pending_deducted = False
    submission.status = "admin_reviewing"
    incr_pending(new)

    note = ""
    if old_admin_id is not None:
        prev_names = [
            (u.real_name or u.username) for u in admins if u.id in history and u.id != -1 and u.id != new.id
        ]
        if prev_names:
            note = "历史派发记录说明：" + "、".join(prev_names) + " 曾先后收到该工单但均未及时处理。\n"
    return [build_assignment_email(submission, new, note)]


def recommend_supplement_staff(db: Session, team: User, n: int = 2) -> list[int]:
    """超管补审时按双重排序算法推荐审核员（超管可覆盖）。"""
    staffs = [s for s in get_active_users(db, "staff") if not is_team_collision(s, team)]
    return [u.id for u in pick_best(db, staffs, n)]
