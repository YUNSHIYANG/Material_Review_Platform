"""Pydantic 请求/响应模型。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str
    real_name: str
    need_password_change: bool


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


class UserIn(BaseModel):
    username: str
    role: str  # team / staff / admin / super_admin
    real_name: Optional[str] = None
    student_id: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None  # 不填则由系统生成临时密码
    member_names: Optional[list[str]] = None
    member_student_ids: Optional[list[str]] = None
    is_deleted: Optional[bool] = False


class UserUpdate(UserIn):
    username: Optional[str] = None
    role: Optional[str] = None


class ConfirmAction(BaseModel):
    password: str  # 超管自身登录密码二次确认


class StaffReviewIn(BaseModel):
    result: bool
    comment: str = ""
    version: int


class AdminReviewIn(BaseModel):
    final_result: bool
    admin_comment: str = ""
    version: int


class InterveneIn(BaseModel):
    action: str  # force_pass / force_reject / reassign / supplement_first_review
    version: int
    password: str
    comment: str = ""
    staff_ids: Optional[list[int]] = None
    new_admin_id: Optional[int] = None


class ReturnPassedIn(BaseModel):
    password: str  # 超管自身登录密码二次确认
    version: Optional[int] = None
    comment: str = ""  # 打回意见（必填）


class ConfigUpdateIn(BaseModel):
    timeout_hours: Optional[int] = None
    cycle_threshold: Optional[int] = None
    global_reassign_threshold: Optional[int] = None
    assignment_pending_multiplier: Optional[float] = None
    password: str
