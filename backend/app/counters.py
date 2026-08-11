"""计数器维护：严格遵循文档 6.2 节，所有扣减前置校验 >0。"""
from sqlalchemy.orm import Session

from .models import User


def incr_pending(user: User) -> None:
    user.current_pending_count += 1


def decr_pending(user: User, n: int = 1) -> bool:
    """扣减待办，前置校验 >0；返回是否执行。"""
    if user and user.current_pending_count >= n:
        user.current_pending_count -= n
        return True
    return False


def incr_completed(user: User) -> None:
    user.total_completed_count += 1


def decr_completed(user: User, n: int = 1) -> bool:
    """回退已完成工作量（仅当 is_counted=TRUE 时调用）。"""
    if user and user.total_completed_count >= n:
        user.total_completed_count -= n
        return True
    return False


def apply_timeout_penalty(user: User) -> None:
    """超时加权移动平均：timeout_count = timeout_count * 0.8 + 1。"""
    user.timeout_count = user.timeout_count * 0.8 + 1.0


def decay_timeout_count(user: User) -> None:
    """每日衰减：timeout_count = timeout_count * 0.95。"""
    user.timeout_count = round(user.timeout_count * 0.95, 4)
