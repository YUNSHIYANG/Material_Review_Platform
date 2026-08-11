"""文件下载（鉴权路由）：严格遵循文档第 9 章下载权限规则。"""
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user
from ..models import AdminReview, StaffReview, Submission, User

router = APIRouter(prefix="/api/files", tags=["files"])

settings = get_settings()


@router.get("/{submission_id}")
def download_file(submission_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sub = db.get(Submission, submission_id)
    if sub is None or not sub.file_path:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = os.path.join(settings.upload_dir, sub.file_path) if not os.path.isabs(sub.file_path) else sub.file_path
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="文件已被清理或不存在")

    # 已撤回工单：仅提交人（团队本人）和超管可下载
    if sub.status == "withdrawn":
        if user.role != "super_admin" and sub.team_id != user.id:
            raise HTTPException(status_code=403, detail="该工单已撤回，仅提交人可查看附件")
    else:
        if user.role == "super_admin":
            pass
        elif sub.team_id == user.id:
            pass
        elif user.role == "staff" and db.query(StaffReview).filter_by(
            submission_id=sub.id, reviewer_id=user.id
        ).first():
            pass
        elif user.role == "admin" and (
            sub.assigned_admin_id == user.id
            or db.query(AdminReview).filter_by(submission_id=sub.id, admin_id=user.id).first()
        ):
            pass
        else:
            raise HTTPException(status_code=403, detail="无权下载该文件")

    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=sub.file_stored_name or sub.file_original_name or "attachment",
    )
