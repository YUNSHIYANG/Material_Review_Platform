"""管理员端路由：独占派发待办、再审详情（完全透明）、终审裁定。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_role
from ..email_service import dispatch_emails
from ..flows import submit_admin_review
from ..locking import submission_lock
from ..models import AdminReview, Submission, User
from ..schemas import AdminReviewIn
from ..utils import utcnow

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/todos")
def todos(
    sort: str = "desc",
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    now = utcnow()
    q = db.query(Submission).filter(
        Submission.status == "admin_reviewing", Submission.assigned_admin_id == admin.id
    )
    q = q.order_by(Submission.created_at.desc()) if sort == "desc" else q.order_by(Submission.created_at.asc())
    result = []
    for sub in q.all():
        first_review_marker = None
        if sub.first_review_skip_reason == "timeout":
            first_review_marker = "超时跳过"
        elif sub.first_review_skip_reason == "insufficient_staff":
            first_review_marker = "人数不足跳过"
        else:
            first_review_marker = (
                sub.staff_reviews[-1].submitted_at.isoformat() if sub.staff_reviews and sub.staff_reviews[-1].submitted_at else None
            )
        result.append(
            {
                "submission_id": sub.id,
                "team_name": sub.team.real_name if sub.team else "",
                "submit_round": sub.submit_round,
                "created_at": sub.created_at.isoformat() if sub.created_at else None,
                "first_review_marker": first_review_marker,
                "version": sub.version,
                "urgent": (
                    sub.admin_assigned_at and (now - sub.admin_assigned_at).total_seconds() > 60 * 3600
                ),
            }
        )
    return result


@router.get("/submissions/{submission_id}")
def detail(submission_id: int, db: Session = Depends(get_db), admin: User = Depends(require_role("admin"))):
    sub = db.get(Submission, submission_id)
    if sub is None or sub.assigned_admin_id != admin.id or sub.status != "admin_reviewing":
        raise HTTPException(status_code=404, detail="该工单未派发给您或已处理")

    # 初审意见墙（真实姓名；被撤回意见完全隐藏）
    wall = []
    completed = 0
    timed_out_name = None
    for sr in sub.staff_reviews:
        if sr.is_withdrawn:
            wall.append({"reviewer_name": sr.reviewer.real_name, "hidden": True})
            continue
        if sr.is_timeout:
            timed_out_name = sr.reviewer.real_name
            wall.append({"reviewer_name": sr.reviewer.real_name, "timeout": True})
            continue
        if sr.submitted_at:
            completed += 1
        wall.append(
            {
                "reviewer_name": sr.reviewer.real_name,
                "result": sr.result,
                "comment": sr.comment,
                "submitted_at": sr.submitted_at.isoformat() if sr.submitted_at else None,
            }
        )

    completion = "2/2"
    if sub.first_review_skip_reason == "timeout":
        completion = f"1/2（{timed_out_name} 超时未审）" if completed == 1 else "超时自动跳过"
    elif sub.first_review_skip_reason == "insufficient_staff":
        completion = "初审员不足，自动转终审"
    elif completed < 2:
        completion = f"{completed}/2"

    # 历史驳回记录（关联追溯）
    parent_history = []
    if sub.parent_submission_id:
        rejected_subs = (
            db.query(Submission)
            .filter(Submission.team_id == sub.team_id, Submission.status == "rejected")
            .order_by(Submission.created_at.desc())
            .all()
        )
        for rs in rejected_subs:
            ar = db.query(AdminReview).filter(AdminReview.submission_id == rs.id).first()
            parent_history.append(
                {
                    "id": rs.id,
                    "rejected_at": (ar.reviewed_at.isoformat() if ar and ar.reviewed_at else None),
                    "admin_comment": ar.admin_comment if ar else None,
                    "submit_round": rs.submit_round,
                }
            )

    return {
        "submission_id": sub.id,
        "team_name": sub.team.real_name if sub.team else "",
        "submit_round": sub.submit_round,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
        "remark": sub.remark,
        "file_original_name": sub.file_original_name,
        "file_stored_name": sub.file_stored_name,
        "wall": wall,
        "completion": completion,
        "parent_submission_id": sub.parent_submission_id,
        "parent_history": parent_history,
        "admin_assigned_at": sub.admin_assigned_at.isoformat() if sub.admin_assigned_at else None,
        "version": sub.version,
    }


@router.post("/submissions/{submission_id}/review")
def review(
    submission_id: int,
    body: AdminReviewIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    with submission_lock(submission_id):
        sub = db.get(Submission, submission_id)
        if sub is None:
            raise HTTPException(status_code=404, detail="工单不存在")
        tasks = submit_admin_review(db, sub, admin, body.final_result, body.admin_comment, body.version)
        db.commit()
    dispatch_emails(db, tasks)
    return {"message": "裁定成功，工单已终结"}
