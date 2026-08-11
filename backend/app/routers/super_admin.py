"""超级管理员端：用户管理、密码重置、工单管理、干预、邮件日志、系统配置、负载监控、审计。"""
import os
import zipfile
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import user_io
from ..assignment import ACTIVE_STATUSES, recommend_supplement_staff
from ..audit import build_snapshot, write_audit
from ..config import get_settings
from ..config_store import config_snapshot, get_config, get_effective_timeout, set_config
from ..database import get_db
from ..deps import require_role
from ..email_service import _attempt, dispatch_emails, mail_banner_active
from ..flows import force_finalize, reassign_from_intervention, return_passed_submission, supplement_first_review
from ..locking import submission_lock
from ..models import AdminAuditLog, AdminReview, EmailLog, StaffReview, Submission, User
from ..schemas import ConfirmAction, ConfigUpdateIn, InterveneIn, ReturnPassedIn, UserIn, UserUpdate
from ..security import (
    generate_temp_password,
    set_user_password,
    unlock_user,
    validate_password_complexity,
    verify_password,
)
from ..utils import normalize_name, sanitize_dirname, utcnow

router = APIRouter(prefix="/api/super", tags=["super_admin"])

settings = get_settings()

SuperAdmin = require_role("super_admin")


def _verify_super_password(user: User, password: str):
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=403, detail="身份确认失败：登录密码错误")


def _client_meta(request) -> tuple[str | None, str | None]:
    return request.client.host if request.client else None, request.headers.get("User-Agent")


# ---------------------------------------------------------------- 仪表盘
@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)):
    pending_intervention = (
        db.query(Submission)
        .filter(Submission.status == "pending_admin_intervention")
        .order_by(Submission.updated_at.desc())
        .all()
    )
    name_map = {
        u.id: (u.real_name or u.username)
        for u in db.query(User).filter(User.role.in_(("staff", "admin")), User.is_deleted.is_(False)).all()
    }
    from collections import Counter

    counts = Counter(
        s.status for s in db.query(Submission.status).all()
    )
    return {
        "smtp_configured": bool(settings.smtp_host),
        "mail_banner": mail_banner_active(db),
        "pending_intervention": [
            {
                "id": s.id,
                "team_name": s.team.real_name if s.team else "",
                "submit_round": s.submit_round,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "total_reassign_count": s.total_reassign_count,
                "cycle_count": s.cycle_count,
                "reassign_history": list(s.reassign_history or []),
                "reassign_history_names": [
                    "超管介入重置" if x == -1 else name_map.get(x, f"#ID {x}") for x in (s.reassign_history or [])
                ],
                "version": s.version,
            }
            for s in pending_intervention
        ],
        "status_counts": dict(counts),
    }


@router.post("/emails/banner/dismiss")
def dismiss_banner(db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)):
    set_config(db, "mail_service_banner", False, operator.id)
    db.commit()
    return {"message": "已处理"}


# ---------------------------------------------------------------- 用户管理
def _validate_user_data(db: Session, data: UserIn | UserUpdate, exclude_id: int | None = None):
    username = data.username
    if username:
        dup = db.query(User).filter(User.username == username).first()
        if dup and dup.id != exclude_id:
            raise HTTPException(status_code=400, detail=f"用户名 {username} 已存在")

    role = data.role
    if role in ("staff", "admin") and not data.real_name:
        raise HTTPException(status_code=400, detail="审核员/管理员必须填写真实姓名 real_name")
    if role in ("staff", "admin") and not data.student_id:
        raise HTTPException(status_code=400, detail="审核员/管理员必须填写学工号 student_id")
    if role in ("staff", "admin") and data.student_id:
        dup = (
            db.query(User)
            .filter(
                User.role.in_(("staff", "admin")),
                User.student_id == data.student_id,
                User.is_deleted.is_(False),
                User.id != exclude_id,
            )
            .first()
        )
        if dup:
            raise HTTPException(status_code=400, detail=f"学工号 {data.student_id} 已被其他审核员/管理员使用")

    if role == "team":
        if not data.real_name:
            raise HTTPException(status_code=400, detail="团队必须填写团队名称 real_name")
        names = data.member_names or []
        sids = data.member_student_ids or []
        if not names or not sids:
            raise HTTPException(status_code=400, detail="团队必须录入成员名单与学工号")
        if not (0 < len(names) <= 12 and len(names) == len(sids)):
            raise HTTPException(status_code=400, detail="成员名单与学工号须一一对应且不超过12人")


def _build_user(data: UserIn, password: str) -> User:
    """按角色构造 User（含明文密码留档，供超管导出账密）。"""
    if data.role == "team":
        normalized = [normalize_name(x) for x in data.member_names]
        user = User(
            username=data.username,
            role="team",
            real_name=data.real_name,
            email=data.email,
            member_names=normalized,
            member_names_raw=data.member_names,
            member_student_ids=data.member_student_ids,
            password_changed_at=None,  # 首次登录强制改密
        )
    else:
        user = User(
            username=data.username,
            role=data.role,
            real_name=data.real_name,
            student_id=data.student_id,
            email=data.email,
            password_changed_at=None,
        )
    set_user_password(user, password)
    return user


@router.get("/users")
def list_users(role: str | None = None, db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)):
    q = db.query(User).filter(User.is_deleted.is_(False))
    if role:
        q = q.filter(User.role == role)
    return [
        {
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "real_name": u.real_name,
            "student_id": u.student_id,
            "email": u.email,
            "member_names": u.member_names,
            "member_student_ids": u.member_student_ids,
            "current_pending_count": u.current_pending_count,
            "total_completed_count": u.total_completed_count,
            "timeout_count": u.timeout_count,
            "system_forced_penalty": u.system_forced_penalty,
            "login_fail_count": u.login_fail_count,
            "locked_until": u.locked_until.isoformat() if u.locked_until else None,
            "is_deleted": u.is_deleted,
        }
        for u in q.order_by(User.id).all()
    ]


@router.post("/users")
def create_user(data: UserIn, db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)):
    _validate_user_data(db, data)
    if not data.email:
        raise HTTPException(status_code=400, detail="必须填写邮箱（用于邮件通知）")
    if data.password:
        validate_password_complexity(data.password)
        password = data.password
    else:
        password = generate_temp_password()

    user = _build_user(data, password)
    db.add(user)
    db.flush()
    if data.role == "team":
        user.team_id = user.id  # 自引用
    db.commit()
    return {"id": user.id, "message": "创建成功", "temp_password": password if not data.password else None}


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/users/template")
def download_template(db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)):
    content = user_io.build_template()
    return Response(
        content,
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": "attachment; filename*=UTF-8''%E7%94%A8%E6%88%B7%E5%AF%BC%E5%85%A5%E6%A8%A1%E6%9D%BF.xlsx"},
    )


@router.get("/users/export")
def export_accounts(db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)):
    """批量导出全部用户账密（含明文密码），仅超管可用。"""
    users = db.query(User).filter(User.is_deleted.is_(False)).order_by(User.id).all()
    content = user_io.export_users(users)
    filename = f"账号密码导出_{utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    write_audit(db, operator.id, "EXPORT_ACCOUNTS", remark=f"批量导出 {len(users)} 个用户账密")
    db.commit()
    return Response(
        content,
        media_type=_XLSX_MIME,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.post("/users/import")
def import_users(
    file: UploadFile = File(...), db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)
):
    """批量导入用户（Excel 模板），逐行校验，返回成功/失败明细。"""
    try:
        content = file.file.read()
        records = user_io.parse_import_rows(content)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Excel 解析失败：{e}")
    if not records:
        raise HTTPException(status_code=400, detail="文件中没有可导入的数据行")

    created, errors = [], []
    seen = set()
    for rec in records:
        row, username = rec["row"], rec["用户名"]
        try:
            if not username:
                raise ValueError("用户名不能为空")
            if username in seen or db.query(User).filter(User.username == username).first():
                raise ValueError(f"用户名 {username} 已存在")
            role = user_io.ROLE_ALIAS.get(rec["角色"])
            if role is None:
                raise ValueError(f"角色取值无效：{rec['角色'] or '空'}（可选 team/staff/admin/super_admin）")
            password = rec["初始密码（留空自动生成）"] or None
            if password:
                validate_password_complexity(password)
            data = UserIn(
                username=username,
                role=role,
                real_name=rec["姓名/团队名称"] or None,
                student_id=rec["学工号"] or None,
                email=rec["邮箱"] or None,
                password=password,
                member_names=user_io._parse_json_or_split(rec["成员姓名(JSON数组)"]),
                member_student_ids=user_io._parse_json_or_split(rec["成员学工号(JSON数组)"]),
            )
            _validate_user_data(db, data)
            if not data.email:
                raise ValueError("必须填写邮箱（用于邮件通知）")
            user = _build_user(data, password or generate_temp_password())
            db.add(user)
            db.flush()
            if role == "team":
                user.team_id = user.id
            seen.add(username)
            created.append({"row": row, "username": username, "temp_password": password or user.plain_password})
        except HTTPException as e:
            errors.append({"row": row, "username": username, "error": e.detail})
        except ValueError as e:
            errors.append({"row": row, "username": username, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            errors.append({"row": row, "username": username, "error": f"未知错误：{e}"})
    db.commit()
    write_audit(
        db, operator.id, "IMPORT_USERS",
        remark=f"批量导入用户：成功 {len(created)} 行，失败 {len(errors)} 行", target_submission_id=None,
    )
    db.commit()
    return {"created_count": len(created), "created": created, "errors": errors}


@router.put("/users/{user_id}")
def update_user(
    user_id: int, data: UserUpdate, db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)
):
    user = db.get(User, user_id)
    if user is None or user.is_deleted:
        raise HTTPException(status_code=404, detail="用户不存在")
    _validate_user_data(db, data, exclude_id=user_id)
    if data.username:
        user.username = data.username
    if data.role:
        user.role = data.role
    if data.real_name is not None:
        user.real_name = data.real_name
    if data.student_id is not None:
        user.student_id = data.student_id
    if data.email is not None:
        user.email = data.email
    if data.member_names is not None and data.member_student_ids is not None:
        user.member_names = [normalize_name(x) for x in data.member_names]
        user.member_names_raw = data.member_names
        user.member_student_ids = data.member_student_ids
    db.commit()
    return {"message": "更新成功"}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)):
    if user_id == operator.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    user = db.get(User, user_id)
    if user is None or user.is_deleted:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "super_admin":
        active_supers = db.query(User).filter(User.role == "super_admin", User.is_deleted.is_(False)).count()
        if active_supers <= 1:
            raise HTTPException(status_code=400, detail="至少保留一名超级管理员")
    if user.role == "admin":
        active_admins = db.query(User).filter(User.role == "admin", User.is_deleted.is_(False)).count()
        if active_admins <= 2:
            raise HTTPException(status_code=400, detail="普通管理员数量不得少于2人")
    user.is_deleted = True  # 软删除
    db.commit()
    return {"message": "已删除（软删除，历史工单关联保留）"}


@router.post("/users/{user_id}/unlock")
def unlock(user_id: int, db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    unlock_user(user)
    db.commit()
    write_audit(db, operator.id, "INTERVENE", target_user_id=user_id, remark="手动解锁账号")
    db.commit()
    return {"message": "已解锁并重置登录失败计数"}


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: int, body: ConfirmAction, request: Request, db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)
):
    _verify_super_password(operator, body.password)  # 二次输入自身密码确认
    user = db.get(User, user_id)
    if user is None or user.is_deleted:
        raise HTTPException(status_code=404, detail="用户不存在")
    temp = generate_temp_password()
    set_user_password(user, temp)
    user.password_changed_at = None  # 强制下次登录改密
    ip, ua = _client_meta(request)
    write_audit(
        db, operator.id, "RESET_PWD", target_user_id=user_id,
        remark=f"重置用户 {user.username} 密码", ip_address=ip, user_agent=ua,
    )
    db.commit()
    return {"message": "密码已重置", "temp_password": temp}


# ---------------------------------------------------------------- 工单管理
@router.get("/submissions")
def list_submissions(
    status: str | None = None,
    team_id: int | None = None,
    db: Session = Depends(get_db),
    operator: User = Depends(SuperAdmin),
):
    q = db.query(Submission)
    if status:
        q = q.filter(Submission.status == status)
    if team_id:
        q = q.filter(Submission.team_id == team_id)
    result = []
    for s in q.order_by(Submission.created_at.desc()).all():
        result.append(
            {
                "id": s.id,
                "team_name": s.team.real_name if s.team else "",
                "team_id": s.team_id,
                "submit_round": s.submit_round,
                "status": s.status,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "assigned_admin_id": s.assigned_admin_id,
                "first_review_skip_reason": s.first_review_skip_reason,
                "cycle_count": s.cycle_count,
                "total_reassign_count": s.total_reassign_count,
                "version": s.version,
            }
        )
    return result


@router.get("/submissions/download")
def download_materials(
    status: str | None = None,
    db: Session = Depends(get_db),
    operator: User = Depends(SuperAdmin),
):
    """一键下载所有队伍材料：按状态筛选（默认全部阶段），每支队伍仅取最新一次提交；
    zip 内目录按团队名称命名（与后台存储端规则一致：团队名_id，无法使用的字符自动跳过）。"""
    q = db.query(Submission)
    if status:
        q = q.filter(Submission.status == status)
    subs = q.order_by(Submission.created_at.desc()).all()

    # 每支队伍仅保留最新一次提交（最新 version）
    latest: dict[int, Submission] = {}
    for s in subs:
        cur = latest.get(s.team_id)
        if cur is None or s.created_at > cur.created_at:
            latest[s.team_id] = s
    picked = sorted(latest.values(), key=lambda s: s.team_id)

    export_dir = os.path.join(settings.upload_dir, "export")
    os.makedirs(export_dir, exist_ok=True)
    # 清理历史导出包，避免磁盘堆积
    for f in os.listdir(export_dir):
        if f.endswith(".zip"):
            try:
                os.remove(os.path.join(export_dir, f))
            except OSError:
                pass

    filename = f"materials_{utcnow().strftime('%Y%m%d_%H%M%S')}.zip"
    zip_path = os.path.join(export_dir, filename)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for s in picked:
            if not s.file_path:
                continue
            path = os.path.join(settings.upload_dir, s.file_path) if not os.path.isabs(s.file_path) else s.file_path
            if not os.path.exists(path):
                continue
            # 与后台存储端命名一致：团队名_id（id 后缀保证唯一，非法字符自动跳过）
            team_name = sanitize_dirname(s.team.real_name if s.team else "", fallback=f"team_{s.team_id}")
            folder = f"{team_name}_{s.team_id}"
            arc_name = f"{folder}/{s.file_stored_name or s.file_original_name or f'round{s.submit_round}'}"
            zf.write(path, arcname=arc_name)

    write_audit(
        db,
        operator.id,
        "EXPORT_MATERIALS",
        remark=f"批量下载材料：状态筛选={status or '全部'}，覆盖队伍数={len(picked)}",
    )
    db.commit()
    return FileResponse(zip_path, media_type="application/zip", filename=filename)


@router.get("/submissions/{submission_id}")
def submission_detail(
    submission_id: int, db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)
):
    s = db.get(Submission, submission_id)
    if s is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    wall = []
    for sr in s.staff_reviews:
        wall.append(
            {
                "reviewer_id": sr.reviewer_id,
                "reviewer_name": sr.reviewer.real_name if sr.reviewer else "",
                "result": sr.result,
                "comment": sr.comment,
                "submitted_at": sr.submitted_at.isoformat() if sr.submitted_at else None,
                "assigned_at": sr.assigned_at.isoformat() if sr.assigned_at else None,
                "personal_deadline": sr.personal_deadline.isoformat() if sr.personal_deadline else None,
                "is_timeout": sr.is_timeout,
                "is_withdrawn": sr.is_withdrawn,
                "delay_used": sr.delay_used,
            }
        )
    ar = db.query(AdminReview).filter(AdminReview.submission_id == s.id).first()
    assigned_admin = db.get(User, s.assigned_admin_id) if s.assigned_admin_id else None
    name_map = {
        u.id: (u.real_name or u.username)
        for u in db.query(User).filter(User.role.in_(("staff", "admin")), User.is_deleted.is_(False)).all()
    }
    return {
        "id": s.id,
        "team_id": s.team_id,
        "team_name": s.team.real_name if s.team else "",
        "submit_round": s.submit_round,
        "status": s.status,
        "remark": s.remark,
        "file_original_name": s.file_original_name,
        "file_stored_name": s.file_stored_name,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        "first_review_skip_reason": s.first_review_skip_reason,
        "first_assigned_at": s.first_assigned_at.isoformat() if s.first_assigned_at else None,
        "assigned_admin_id": s.assigned_admin_id,
        "assigned_admin_name": assigned_admin.real_name if assigned_admin else "",
        "admin_assigned_at": s.admin_assigned_at.isoformat() if s.admin_assigned_at else None,
        "cycle_count": s.cycle_count,
        "total_reassign_count": s.total_reassign_count,
        "reassign_history": list(s.reassign_history or []),
        "reassign_history_names": [
            "超管介入重置" if x == -1 else name_map.get(x, f"#ID {x}") for x in (s.reassign_history or [])
        ],
        "admin_names": name_map,
        "intervention_reset_count": s.intervention_reset_count,
        "is_admin_pending_deducted": s.is_admin_pending_deducted,
        "version": s.version,
        "return_comment": s.return_comment,
        "returned_at": s.returned_at.isoformat() if s.returned_at else None,
        "parent_submission_id": s.parent_submission_id,
        "staff_reviews": wall,
        "admin_review": (
            {
                "admin_id": ar.admin_id,
                "admin_name": ar.admin.real_name if ar.admin else "",
                "final_result": ar.final_result,
                "admin_comment": ar.admin_comment,
                "reviewed_at": ar.reviewed_at.isoformat() if ar.reviewed_at else None,
                "is_system_forced": ar.is_system_forced,
            }
            if ar
            else None
        ),
        "can_supplement": (
            s.first_review_skip_reason == "insufficient_staff" and s.assigned_admin_id is None
        ),
    }


@router.get("/submissions/{submission_id}/recommend-staff")
def recommend_staff(
    submission_id: int, db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)
):
    s = db.get(Submission, submission_id)
    if s is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    return {"recommended_ids": recommend_supplement_staff(db, s.team)}


@router.post("/submissions/{submission_id}/intervene")
def intervene(
    submission_id: int, body: InterveneIn, request: Request, db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)
):
    _verify_super_password(operator, body.password)
    ip, ua = _client_meta(request)
    with submission_lock(submission_id):
        sub = db.get(Submission, submission_id)
        if sub is None:
            raise HTTPException(status_code=404, detail="工单不存在")
        if body.action in ("force_pass", "force_reject"):
            tasks = force_finalize(
                db, sub, operator, body.action == "force_pass", body.comment, body.version, ip, ua
            )
        elif body.action == "reassign":
            tasks = reassign_from_intervention(
                db, sub, operator, body.version, ip, ua, force_admin_id=body.new_admin_id
            )
        elif body.action == "supplement_first_review":
            tasks = supplement_first_review(
                db, sub, operator, body.staff_ids or [], body.version, ip, ua
            )
        else:
            raise HTTPException(status_code=400, detail="未知干预动作")
        db.commit()
    dispatch_emails(db, tasks)
    return {"message": "干预成功"}


@router.post("/submissions/{submission_id}/return")
def return_passed(
    submission_id: int,
    body: ReturnPassedIn,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(SuperAdmin),
):
    """打回已通过材料：附打回意见，团队需重新提交并重走流程。"""
    _verify_super_password(operator, body.password)
    ip, ua = _client_meta(request)
    with submission_lock(submission_id):
        sub = db.get(Submission, submission_id)
        if sub is None:
            raise HTTPException(status_code=404, detail="工单不存在")
        tasks = return_passed_submission(db, sub, operator, body.comment, body.version, ip, ua)
        db.commit()
    dispatch_emails(db, tasks)
    return {"message": "已打回，团队将收到打回意见并需重新提交"}


# ---------------------------------------------------------------- 邮件日志
@router.get("/emails")
def list_emails(submission_id: int | None = None, db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)):
    q = db.query(EmailLog)
    if submission_id:
        q = q.filter(EmailLog.submission_id == submission_id)
    return [
        {
            "id": e.id,
            "recipient": e.recipient,
            "subject": e.subject,
            "status": e.status,
            "retry_count": e.retry_count,
            "last_error": e.last_error,
            "submission_id": e.submission_id,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "sent_at": e.sent_at.isoformat() if e.sent_at else None,
        }
        for e in q.order_by(EmailLog.created_at.desc()).limit(500).all()
    ]


@router.post("/emails/{email_id}/resend")
def resend_email(email_id: int, db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)):
    log = db.get(EmailLog, email_id)
    if log is None:
        raise HTTPException(status_code=404, detail="邮件记录不存在")
    ok = _attempt(log)
    log.retry_count += 1
    db.commit()
    return {"message": "重发成功" if ok else "重发失败，已记录错误", "ok": ok}


# ---------------------------------------------------------------- 系统配置
@router.get("/config")
def get_sys_config(db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)):
    return config_snapshot(db)


@router.put("/config")
def update_sys_config(
    body: ConfigUpdateIn, request: Request, db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)
):
    _verify_super_password(operator, body.password)
    before = config_snapshot(db)
    if body.timeout_hours is not None:
        set_config(db, "timeout_hours", body.timeout_hours, operator.id)
    if body.cycle_threshold is not None:
        set_config(db, "cycle_threshold", body.cycle_threshold, operator.id)
    if body.global_reassign_threshold is not None:
        set_config(db, "global_reassign_threshold", body.global_reassign_threshold, operator.id)
    if body.assignment_pending_multiplier is not None:
        set_config(db, "assignment_pending_multiplier", body.assignment_pending_multiplier, operator.id)
    after = config_snapshot(db)
    ip, ua = _client_meta(request)
    write_audit(
        db, operator.id, "CONFIG_UPDATE", remark=f"配置修改：{before} → {after}",
        snapshot_before={"config": before}, snapshot_after={"config": after}, ip_address=ip, user_agent=ua,
    )
    db.commit()
    return {"message": "配置已更新（仅对新派发工单生效）", "config": after}


# ---------------------------------------------------------------- 负载监控 / 审计
@router.get("/load")
def load_monitor(db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)):
    # 负载监控须覆盖全部审核员（staff）与管理员（admin）
    users = (
        db.query(User)
        .filter(User.role.in_(("staff", "admin")), User.is_deleted.is_(False))
        .order_by(User.role, User.id)
        .all()
    )
    return [
        {
            "id": u.id,
            "role": u.role,
            "real_name": u.real_name,
            "current_pending_count": u.current_pending_count,
            "total_completed_count": u.total_completed_count,
            "timeout_count": u.timeout_count,
            "system_forced_penalty": u.system_forced_penalty,
        }
        for u in users
    ]


@router.get("/audit-logs")
def audit_logs(db: Session = Depends(get_db), operator: User = Depends(SuperAdmin)):
    return [
        {
            "id": a.id,
            "operator_id": a.operator_id,
            "operation_type": a.operation_type,
            "target_user_id": a.target_user_id,
            "target_submission_id": a.target_submission_id,
            "remark": a.remark,
            "snapshot_before": a.snapshot_before,
            "snapshot_after": a.snapshot_after,
            "ip_address": a.ip_address,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in db.query(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(200).all()
    ]
