"""超管操作审计：统一快照结构与写审计。"""
from sqlalchemy.orm import Session

from .models import AdminAuditLog, Submission, User


def build_snapshot(db: Session, submission: Submission, admin: User | None = None, staff: User | None = None) -> dict:
    return {
        "submission": {
            "status": submission.status,
            "assigned_admin_id": submission.assigned_admin_id,
            "is_admin_pending_deducted": submission.is_admin_pending_deducted,
            "cycle_count": submission.cycle_count,
            "total_reassign_count": submission.total_reassign_count,
            "reassign_history": list(submission.reassign_history or []),
            "intervention_reset_count": submission.intervention_reset_count,
            "version": submission.version,
        },
        "admin": (
            {
                "current_pending_count": admin.current_pending_count,
                "total_completed_count": admin.total_completed_count,
                "system_forced_penalty": admin.system_forced_penalty,
            }
            if admin
            else None
        ),
        "staff": (
            {
                "current_pending_count": staff.current_pending_count,
                "total_completed_count": staff.total_completed_count,
            }
            if staff
            else None
        ),
    }


def write_audit(
    db: Session,
    operator_id: int,
    operation_type: str,
    target_user_id: int | None = None,
    target_submission_id: int | None = None,
    snapshot_before: dict | None = None,
    snapshot_after: dict | None = None,
    remark: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    db.add(
        AdminAuditLog(
            operator_id=operator_id,
            operation_type=operation_type,
            target_user_id=target_user_id,
            target_submission_id=target_submission_id,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after,
            remark=remark,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    )
    db.flush()
