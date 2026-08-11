"""认证路由：登录、登出、修改密码、当前用户。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..schemas import ChangePasswordIn, LoginIn, LoginOut
from ..security import (
    check_login_lock,
    create_access_token,
    record_login_failure,
    set_user_password,
    unlock_user,
    validate_password_complexity,
    verify_password,
)
from ..utils import utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if user is None or user.is_deleted:
        # 统一错误信息，避免枚举用户名
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    check_login_lock(user)
    if not verify_password(data.password, user.password_hash):
        record_login_failure(user)
        db.commit()
        if user.locked_until and user.locked_until > utcnow():
            raise HTTPException(status_code=423, detail="连续登录失败次数过多，账户已锁定30分钟")
        raise HTTPException(status_code=400, detail="用户名或密码错误")

    unlock_user(user)
    db.commit()
    token = create_access_token(user.id, user.role)
    return LoginOut(
        access_token=token,
        role=user.role,
        username=user.username,
        real_name=user.real_name or user.username,
        need_password_change=user.password_changed_at is None,
    )


@router.post("/change-password")
def change_password(data: ChangePasswordIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    validate_password_complexity(data.new_password)
    if data.old_password == data.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    set_user_password(user, data.new_password)
    user.password_changed_at = utcnow()
    db.commit()
    return {"message": "密码修改成功"}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "real_name": user.real_name or user.username,
        "email": user.email,
        "need_password_change": user.password_changed_at is None,
        "current_pending_count": user.current_pending_count,
        "total_completed_count": user.total_completed_count,
    }
