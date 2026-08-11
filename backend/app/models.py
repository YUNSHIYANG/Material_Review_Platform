"""数据模型：严格遵循产品设计文档第 8 节表结构。"""
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    # 最近一次由系统/超管设置（或用户自行修改）的明文密码，用于超管批量导出账密；
    # 为满足“超管有权知晓所有密码”的业务要求而保留，切勿对外泄露该字段。
    plain_password = Column(String(100), nullable=True)
    role = Column(String(20), nullable=False)  # team / staff / admin / super_admin
    real_name = Column(String(50))  # team=团队名称；staff/admin=个人姓名
    student_id = Column(String(20), nullable=True)  # 学工号（staff/admin 之间唯一）
    member_names = Column(JSON, default=list)  # 团队成员姓名（标准化后）
    member_names_raw = Column(JSON, default=list)  # 原始录入值（审计备查）
    member_student_ids = Column(JSON, default=list)  # 与 member_names 一一对应
    team_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 仅 team 自引用
    email = Column(String(100))
    # 负载与工作量（super_admin 恒为 0）
    current_pending_count = Column(Integer, default=0, nullable=False)
    total_completed_count = Column(Integer, default=0, nullable=False)
    timeout_count = Column(Float, default=0.0, nullable=False)
    system_forced_penalty = Column(Integer, default=0, nullable=False)
    # 登录安全
    login_fail_count = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)
    password_changed_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    submissions = relationship("Submission", foreign_keys="Submission.team_id", back_populates="team")


class Submission(Base):
    __tablename__ = "submissions"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    submit_round = Column(Integer, default=1, nullable=False)
    parent_submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=True)
    file_original_name = Column(String(255))
    file_stored_name = Column(String(255))
    file_path = Column(String(500))
    remark = Column(Text)
    status = Column(String(30), default="pending", nullable=False)
    first_review_skip_reason = Column(String(50), nullable=True)  # timeout / insufficient_staff / NULL
    first_assigned_at = Column(DateTime, nullable=True)  # 仅写一次，永不覆盖
    deadline_calculated_at = Column(DateTime, nullable=True)  # 工单级展示用截止时间
    assigned_admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    admin_assigned_at = Column(DateTime, nullable=True)
    cycle_count = Column(Integer, default=0, nullable=False)
    total_reassign_count = Column(Integer, default=0, nullable=False)
    reassign_history = Column(JSON, default=list)
    intervention_reset_count = Column(Integer, default=0, nullable=False)
    is_admin_pending_deducted = Column(Boolean, default=False, nullable=False)
    version = Column(Integer, default=0, nullable=False)  # 乐观锁
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    withdrawn_at = Column(DateTime, nullable=True)
    return_comment = Column(Text, nullable=True)  # 超管打回已通过材料的意见
    returned_at = Column(DateTime, nullable=True)

    team = relationship("User", foreign_keys=[team_id], back_populates="submissions")
    parent = relationship("Submission", foreign_keys=[parent_submission_id], remote_side=[id])
    staff_reviews = relationship("StaffReview", back_populates="submission")
    admin_review = relationship("AdminReview", back_populates="submission", uselist=False)

    __table_args__ = (
        Index("idx_submissions_status_deadline", "status", "deadline_calculated_at"),
        Index("idx_submissions_admin_assigned", "assigned_admin_id", "status"),
        Index("idx_submissions_team_id", "team_id"),
        Index("idx_submissions_status_created", "status", "created_at"),
    )


class StaffReview(Base):
    __tablename__ = "staff_reviews"
    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    result = Column(Boolean, nullable=True)
    comment = Column(Text)
    submitted_at = Column(DateTime, nullable=True)
    assigned_at = Column(DateTime, nullable=False)
    personal_deadline = Column(DateTime, nullable=False)
    is_timeout = Column(Boolean, default=False, nullable=False)
    is_withdrawn = Column(Boolean, default=False, nullable=False)
    withdrawn_at = Column(DateTime, nullable=True)
    delay_used = Column(Boolean, default=False, nullable=False)
    is_counted = Column(Boolean, default=False, nullable=False)

    submission = relationship("Submission", back_populates="staff_reviews")
    reviewer = relationship("User")

    __table_args__ = (
        UniqueConstraint("submission_id", "reviewer_id", name="uq_staff_review_sub_reviewer"),
        Index("idx_staff_reviews_personal_deadline", "personal_deadline", "is_withdrawn", "is_timeout"),
    )


class AdminReview(Base):
    __tablename__ = "admin_reviews"
    id = Column(Integer, primary_key=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False, unique=True)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    final_result = Column(Boolean, nullable=False)
    admin_comment = Column(Text)
    reviewed_at = Column(DateTime, default=func.now(), nullable=False)
    is_reassigned = Column(Boolean, default=False, nullable=False)
    is_system_forced = Column(Boolean, default=False, nullable=False)

    submission = relationship("Submission", back_populates="admin_review")
    admin = relationship("User")


class EmailLog(Base):
    __tablename__ = "email_logs"
    id = Column(Integer, primary_key=True)
    recipient = Column(String(100), nullable=False)
    subject = Column(String(200))
    content = Column(Text)
    status = Column(String(20), default="pending", nullable=False)  # pending / success / failed
    retry_count = Column(Integer, default=0, nullable=False)
    last_error = Column(Text)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    sent_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (Index("idx_email_logs_submission", "submission_id"),)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    id = Column(Integer, primary_key=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    operation_type = Column(String(30), nullable=False)
    target_user_id = Column(Integer, nullable=True)
    target_submission_id = Column(Integer, nullable=True)
    snapshot_before = Column(JSON)
    snapshot_after = Column(JSON)
    remark = Column(Text)
    ip_address = Column(String(45))
    user_agent = Column(String(255))
    created_at = Column(DateTime, default=func.now(), nullable=False)


class SystemConfig(Base):
    """系统配置（键值对）。"""
    __tablename__ = "system_config"
    id = Column(Integer, primary_key=True)
    key = Column(String(50), unique=True, nullable=False)
    value = Column(JSON)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    updated_by = Column(Integer, nullable=True)
