"""提交人端路由：新建提交、进度看板、详情、撤回。"""
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func as sqla_func
from sqlalchemy.orm import Session

from ..assignment import ACTIVE_STATUSES, assign_admin_review, assign_first_review
from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user, require_role
from ..email_service import dispatch_emails
from ..flows import withdraw_submission
from ..locking import submission_lock
from ..models import AdminReview, StaffReview, Submission, User
from ..utils import add_hours, format_duration_remain, sanitize_dirname, sanitize_filename, utcnow

router = APIRouter(prefix="/api/team", tags=["team"])

settings = get_settings()

USER_STATUS_MAP = {
    "pending": "审核中",
    "first_reviewing": "审核中",
    "admin_reviewing": "审核中",
    "pending_admin_intervention": "加急处理中",
    "passed": "已通过",
    "rejected": "未通过",
    "withdrawn": "已撤回",
    "returned": "已打回",
}


def _serialize_submission(db: Session, sub: Submission, for_detail: bool = False) -> dict:
    data = {
        "id": sub.id,
        "submit_round": sub.submit_round,
        "status": sub.status,
        "user_status": USER_STATUS_MAP.get(sub.status, sub.status),
        "file_original_name": sub.file_original_name,
        "file_stored_name": sub.file_stored_name,
        "remark": sub.remark,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
        "withdrawn_at": sub.withdrawn_at.isoformat() if sub.withdrawn_at else None,
        "return_comment": sub.return_comment,
        "returned_at": sub.returned_at.isoformat() if sub.returned_at else None,
        "version": sub.version,
        # 通过后仍允许撤回重提（重走流程）
        "can_withdraw": sub.status in ("pending", "first_reviewing", "admin_reviewing", "passed"),
    }
    if for_detail:
        # 灰色小字透明度提示：仅 admin_reviewing + skip_reason 非空
        skip_hint = None
        if sub.status == "admin_reviewing" and sub.first_review_skip_reason:
            skip_hint = (
                "初审员审核超时，材料已转交管理员复核"
                if sub.first_review_skip_reason == "timeout"
                else "材料审核流程已启动，请耐心等待"
            )
        data["first_review_skip_hint"] = skip_hint
        data["pending_admin_intervention_note"] = (
            "系统正在加急处理，请耐心等待" if sub.status == "pending_admin_intervention" else None
        )
        data["returned_note"] = (
            f"材料已被打回，请按意见修改后重新提交。打回意见：{sub.return_comment}"
            if sub.status == "returned" and sub.return_comment
            else None
        )
        # 流程终结后展示完整意见链（姓名匿名：审核员甲/乙、管理员）
        chain = None
        if sub.status in ("passed", "rejected", "withdrawn", "returned"):
            chain = _build_anonymous_chain(db, sub)
        data["review_chain"] = chain
        data["parent_submission_id"] = sub.parent_submission_id
    return data


def _build_anonymous_chain(db: Session, sub: Submission) -> list[dict]:
    chain = []
    for i, sr in enumerate(sorted(sub.staff_reviews, key=lambda x: x.id)):
        if sr.is_withdrawn or sr.is_timeout:
            continue
        chain.append(
            {
                "reviewer_label": f"审核员{'甲' if i % 2 == 0 else '乙'}",
                "result": sr.result,
                "comment": sr.comment,
                "submitted_at": sr.submitted_at.isoformat() if sr.submitted_at else None,
            }
        )
    ar = db.query(AdminReview).filter(AdminReview.submission_id == sub.id).first()
    if ar:
        chain.append(
            {
                "reviewer_label": "管理员",
                "result": ar.final_result,
                "comment": ar.admin_comment,
                "submitted_at": ar.reviewed_at.isoformat() if ar.reviewed_at else None,
            }
        )
    return chain


@router.post("/submissions")
def create_submission(
    file: UploadFile = File(...),
    remark: str = Form(""),
    db: Session = Depends(get_db),
    team: User = Depends(require_role("team")),
):
    active = (
        db.query(Submission)
        .filter(Submission.team_id == team.id, Submission.status.in_(ACTIVE_STATUSES))
        .first()
    )
    if active:
        raise HTTPException(status_code=400, detail="您有工单正在审核中，请等待流程终结后再提交")

    # 提交序号
    max_round = db.query(sqla_func.max(Submission.submit_round)).filter(Submission.team_id == team.id).scalar()
    submit_round = (max_round or 0) + 1

    # 关联追溯：最近一条“未通过/已打回”的根工单（不考虑时间与次数）
    parent_id = None
    last_failed = (
        db.query(Submission)
        .filter(Submission.team_id == team.id, Submission.status.in_(("rejected", "returned")))
        .order_by(Submission.created_at.desc())
        .first()
    )
    if last_failed:
        root = last_failed
        while root.parent_submission_id:
            root = db.get(Submission, root.parent_submission_id)
        parent_id = root.id

    # 文件名处理与存储：目录按团队名称命名（无法使用的字符自动跳过），加 team_id 保证唯一
    original_name = sanitize_filename(file.filename or "file.zip")
    safe_name = sanitize_dirname(team.real_name, fallback=f"team_{team.id}")
    team_dir_name = f"{safe_name}_{team.id}"
    stored_name = f"round{submit_round}_{original_name}"
    team_dir = os.path.join(settings.upload_dir, team_dir_name)
    os.makedirs(team_dir, exist_ok=True)
    rel_path = os.path.join(team_dir_name, stored_name)
    abs_path = os.path.join(settings.upload_dir, rel_path)
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    total = 0
    try:
        with open(abs_path, "wb") as f:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail=f"文件大小超过限制（{settings.max_file_size_mb}MB）")
                f.write(chunk)
    except HTTPException:
        if os.path.exists(abs_path):
            os.remove(abs_path)
        raise

    now = utcnow()
    sub = Submission(
        team_id=team.id,
        submit_round=submit_round,
        parent_submission_id=parent_id,
        file_original_name=original_name,
        file_stored_name=stored_name,
        file_path=rel_path,
        remark=remark or None,
        status="pending",
        deadline_calculated_at=add_hours(now, settings.timeout_hours),
    )
    db.add(sub)
    db.flush()
    if parent_id:
        # 未通过/打回后的重新提交：按计划跳过初审，直接进入再审（管理员复核）
        tasks = assign_admin_review(db, sub)
    else:
        tasks = assign_first_review(db, sub, team)
    db.commit()
    dispatch_emails(db, tasks)
    return {"message": "提交成功", "submission_id": sub.id}


@router.get("/submissions")
def list_submissions(db: Session = Depends(get_db), team: User = Depends(require_role("team"))):
    subs = (
        db.query(Submission)
        .filter(Submission.team_id == team.id)
        .order_by(Submission.created_at.desc())
        .all()
    )
    return [_serialize_submission(db, s) for s in subs]


@router.get("/submissions/{submission_id}")
def submission_detail(
    submission_id: int, db: Session = Depends(get_db), team: User = Depends(require_role("team"))
):
    sub = db.get(Submission, submission_id)
    if sub is None or sub.team_id != team.id:
        raise HTTPException(status_code=404, detail="工单不存在")
    return _serialize_submission(db, sub, for_detail=True)


@router.post("/submissions/{submission_id}/withdraw")
def withdraw(
    submission_id: int,
    body: dict,
    db: Session = Depends(get_db),
    team: User = Depends(require_role("team")),
):
    with submission_lock(submission_id):
        sub = db.get(Submission, submission_id)
        if sub is None or sub.team_id != team.id:
            raise HTTPException(status_code=404, detail="工单不存在")
        withdraw_submission(db, sub, team, body.get("version"))
        db.commit()
    return {"message": "已撤回，审核意见已作废并留档"}
