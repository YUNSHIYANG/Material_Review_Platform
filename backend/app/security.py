"""密码哈希、Token、密码复杂度与登录锁定逻辑。"""
import re
from datetime import datetime

import bcrypt
import jwt
from fastapi import HTTPException

from .config import get_settings
from .utils import utcnow

settings = get_settings()

COMPLEXITY_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{8,}$")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def set_user_password(user, plaintext: str) -> None:
    """统一写入口：更新哈希，并保留明文用于超管导出账密。"""
    user.password_hash = hash_password(plaintext)
    user.plain_password = plaintext


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def validate_password_complexity(password: str):
    if not COMPLEXITY_RE.match(password or ""):
        raise HTTPException(
            status_code=400,
            detail="密码长度不少于8位，且须同时包含大写字母、小写字母、数字和特殊字符",
        )


def generate_temp_password(length: int = 8) -> str:
    """生成含大小写字母+数字+特殊字符的 8 位临时密码。"""
    import random
    import string

    lower = random.choice(string.ascii_lowercase)
    upper = random.choice(string.ascii_uppercase)
    digit = random.choice(string.digits)
    special = random.choice("!@#$%^&*")
    rest = "".join(
        random.choices(string.ascii_letters + string.digits + "!@#$%^&*", k=length - 4)
    )
    chars = list(lower + upper + digit + special + rest)
    random.shuffle(chars)
    return "".join(chars)


def create_access_token(user_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": datetime.fromtimestamp(utcnow().timestamp() + settings.token_expire_hours * 3600),
        "iat": utcnow(),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")


def check_login_lock(user) -> None:
    """锁定期间的所有登录尝试：返回锁定错误，且不更新任何计数字段。"""
    if user.locked_until and user.locked_until > utcnow():
        raise HTTPException(status_code=423, detail="账户已锁定，请30分钟后再试")


def record_login_failure(user) -> None:
    user.login_fail_count += 1
    if user.login_fail_count >= settings.login_fail_limit:
        user.locked_until = datetime.fromtimestamp(
            utcnow().timestamp() + settings.login_lock_minutes * 60
        )


def unlock_user(user) -> None:
    user.login_fail_count = 0
    user.locked_until = None
