"""FastAPI 依赖：鉴权与角色校验。"""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .security import decode_access_token

TOKEN_COOKIE = "access_token"


def _token_from_request(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get(TOKEN_COOKIE, "")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="未登录或登录已失效")
    payload = decode_access_token(token)
    user = db.get(User, int(payload["sub"]))
    if user is None or user.is_deleted:
        raise HTTPException(status_code=401, detail="账号不存在或已停用")
    return user


def require_role(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="没有操作权限")
        return user

    return checker
