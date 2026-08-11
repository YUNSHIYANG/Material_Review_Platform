"""通用工具函数。"""
import re
import unicodedata
from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    """统一使用无时区信息的 UTC 时间。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def add_hours(dt: datetime, hours: int) -> datetime:
    return dt + timedelta(hours=hours)


def normalize_name(name: str) -> str:
    """姓名标准化：去首尾空格、全半角统一（NFKC）、去内部空格。"""
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name.strip())
    return re.sub(r"\s+", "", s)


# 危险字符：../ 、\ 、空字符等一律移除；仅保留 字母/数字/中文/下划线/连字符/点号
_SAFE_FILENAME_RE = re.compile(r"[^\w\u4e00-\u9fff.\-]", re.UNICODE)


def sanitize_filename(name: str) -> str:
    if not name:
        return "file"
    name = name.replace("\\", "/").split("/")[-1]
    name = _SAFE_FILENAME_RE.sub("_", name)
    name = name.strip(" .")
    return name or "file"


# 目录名安全化：移除 Windows 保留字符与控制字符（"无法使用的字符自动跳过"），
# 允许中文/字母/数字/下划线/连字符/空格等常规字符。
_DIRNAME_INVALID_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_dirname(name: str, fallback: str = "team") -> str:
    if not name:
        return fallback
    cleaned = _DIRNAME_INVALID_RE.sub("", name)
    cleaned = cleaned.strip(" .")
    return cleaned or fallback


def format_duration_remain(deadline: datetime) -> str:
    """返回 'X 小时 X 分' 剩余时间文案。"""
    remain = deadline - utcnow()
    if remain <= timedelta(0):
        return "0 小时 0 分"
    total_minutes = int(remain.total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours} 小时 {minutes} 分"
