"""审核员端路由：待办列表、审核操作、撤回初审结论。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_role
from ..email_service import dispatch_emails
from ..flows import submit_staff_review, withdraw_staff_review
from ..locking import submission_lock
from ..models import StaffReview, Submission, User
from ..schemas import StaffReviewIn
from ..utils import format_duration_remain, utcnow

router = APIRouter(prefix="/api/staff", tags=["staff"])


def _my_review(db: Session, submission_id: int, reviewer_id: int) -> StaffReview | None:
    return (
        db.query(StaffReview)
        .filter(StaffReview.submission_id == submission_id, StaffReview.reviewer_id == reviewer_id)
        .first()
    )


@router.get("/todos")
def todos(db: Session = Depends(get_db), reviewer: User = Depends(require_role("staff"))):
    now = utcnow()
    rows = (
        db.query(StaffReview, Submission)
        .join(Submission, StaffReview.submission_id == Submission.id)
        .filter(
            StaffReview.reviewer_id == reviewer.id,
            StaffReview.is_timeout.is_(False),
            StaffReview.is_withdrawn.is_(False),
            StaffReview.submitted_at.is_(None),
            Submission.status.in_(("first_reviewing", "admin_reviewing")),
        )
        .order_by(StaffReview.personal_deadline.asc())
        .all()
    )
    result = []
    for sr, sub in rows:
        result.append(
            {
                "submission_id": sub.id,
                "team_name": sub.team.real_name if sub.team else "未知团队",
                "submit_round": sub.submit_round,
                "created_at": sub.created_at.isoformat() if sub.created_at else None,
                "personal_deadline": sr.personal_deadline.isoformat(),
                "urgent": (sr.personal_deadline - now).total_seconds() < 12 * 3600,  # 距截止不足12h
            }
        )
    return result


@router.get("/submissions/{submission_id}")
def detail(submission_id: int, db: Session = Depends(get_db), reviewer: User = Depends(require_role("staff"))):
    sub = db.get(Submission, submission_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    sr = _my_review(db, submission_id, reviewer.id)
    if sr is None or sub.status not in ("first_reviewing", "admin_reviewing"):
        raise HTTPException(status_code=404, detail="您没有该工单的审核任务")
    return {
        "submission_id": sub.id,
        "team_name": sub.team.real_name if sub.team else "",
        "submit_round": sub.submit_round,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
        "remark": sub.remark,
        "file_original_name": sub.file_original_name,
        "file_stored_name": sub.file_stored_name,
        "personal_deadline": sr.personal_deadline.isoformat(),
        "withdrawn_banner": (
            f"您已撤回初审意见，请于 {format_duration_remain(sr.personal_deadline)} 内重新提交，否则将记为超时未审。"
            if sr.is_withdrawn
            else None
        ),
        "my_result": sr.result,
        "my_comment": sr.comment,
        "my_submitted": sr.submitted_at is not None and not sr.is_withdrawn,
        "is_timeout": sr.is_timeout,
        "version": sub.version,
    }


@router.post("/submissions/{submission_id}/review")
def review(
    submission_id: int, body: StaffReviewIn, db: Session = Depends(get_db), reviewer: User = Depends(require_role("staff"))
):
    with submission_lock(submission_id):
        sub = db.get(Submission, submission_id)
        if sub is None:
            raise HTTPException(status_code=404, detail="工单不存在")
        tasks = submit_staff_review(db, sub, reviewer, body.result, body.comment)
        db.commit()
    dispatch_emails(db, tasks)
    return {"message": "意见提交成功，已返回待办列表"}


@router.post("/submissions/{submission_id}/withdraw-review")
def withdraw_review(
    submission_id: int, db: Session = Depends(get_db), reviewer: User = Depends(require_role("staff"))
):
    with submission_lock(submission_id):
        sub = db.get(Submission, submission_id)
        if sub is None:
            raise HTTPException(status_code=404, detail="工单不存在")
        result = withdraw_staff_review(db, sub, reviewer)
        db.commit()
    return result
