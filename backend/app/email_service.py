"""邮件提醒模块：模板（文档 5.5）+ 发送 + 失败重试（间隔5分钟，最多3次）+ 超管告警横幅。"""
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

from sqlalchemy.orm import Session

from .config import get_settings
from .config_store import get_config, set_config
from .models import EmailLog, Submission, User
from .utils import utcnow
from datetime import datetime, timezone, timedelta

settings = get_settings()

# 邮件落款统一使用北京时间（UTC+8），不随容器时区（默认 UTC）变化
CST_TZ = timezone(timedelta(hours=8))

RETRY_MAX_ATTEMPTS = 4  # 首次 + 最多3次重试


# ---------------------------------------------------------------- 模板
def build_assignment_email(submission: Submission, recipient_user: User, history_note: str = "") -> dict:
    team = submission.team
    date_str = datetime.now(CST_TZ).strftime("%Y年%m月%d日%H:%M")
    body = (
        "您好，根据安排，现交给你一份材料审核任务"
        f"（工单#{submission.id}，团队【{team.real_name}】第{submission.submit_round}次提交），"
        f"请于{settings.timeout_hours}小时内在系统上完成审核，有不懂的地方请随时与负责人沟通。\n"
        f"{history_note}\n{date_str}"
    )
    return {
        "recipient": recipient_user.email or "",
        "subject": f"【审核任务通知】工单#{submission.id}",
        "content": body,
        "submission_id": submission.id,
    }


def build_passed_email(submission: Submission) -> dict:
    date_str = datetime.now(CST_TZ).strftime("%Y年%m月%d日%H:%M")
    body = (
        "您好：\n\n来件收悉。你提交的报销材料"
        f"（工单#{submission.id}，第{submission.submit_round}次提交）审核结果如下：\n"
        "审核状态：已通过\n\n材料审核组\n"
        f"{date_str}"
    )
    return {
        "recipient": submission.team.email or "",
        "subject": f"【审核已通过】工单#{submission.id}",
        "content": body,
        "submission_id": submission.id,
    }


def build_rejected_email(submission: Submission, admin_comment: str) -> dict:
    date_str = datetime.now(CST_TZ).strftime("%Y年%m月%d日%H:%M")
    body = (
        "您好：\n\n来件收悉。你提交的报销材料"
        f"（工单#{submission.id}，第{submission.submit_round}次提交）审核结果如下：\n"
        "审核状态：未通过\n\n审核意见：\n"
        f"{admin_comment}\n\n"
        "请你根据以上说明核查并补齐材料，再次登录系统提交最新版材料，重新提交后团队会尽快复核。\n"
        "如有疑问可在负责人群聊内沟通。\n辛苦你配合，谢谢！\n\n材料审核组\n"
        f"{date_str}"
    )
    return {
        "recipient": submission.team.email or "",
        "subject": f"【审核未通过】工单#{submission.id}",
        "content": body,
        "submission_id": submission.id,
    }


def build_returned_email(submission: Submission, comment: str) -> dict:
    date_str = datetime.now(CST_TZ).strftime("%Y年%m月%d日%H:%M")
    body = (
        "您好：\n\n你提交的报销材料"
        f"（工单#{submission.id}，第{submission.submit_round}次提交）在复核中发现了新的问题，现予打回：\n"
        "打回意见：\n"
        f"{comment}\n\n"
        "请你根据以上说明核查并补齐材料，再次登录系统提交最新版材料，重新提交后团队会尽快复核。\n"
        "如有疑问可在负责人群聊内沟通。\n辛苦你配合，谢谢！\n\n材料审核组\n"
        f"{date_str}"
    )
    return {
        "recipient": submission.team.email or "",
        "subject": f"【审核被打回】工单#{submission.id}",
        "content": body,
        "submission_id": submission.id,
    }


def build_insufficient_staff_alert(submission, candidates, excluded_sid, excluded_name) -> dict:
    """初审候选池不足告警（含排除明细）。"""
    detail = (
        f"工单 #{submission.id} 初审候选池不足2人。候选池原始人数：{len(candidates) + len(excluded_sid) + len(excluded_name)}人；"
        f"被排除审核员（学工号匹配）：{_fmt(excluded_sid)}；"
        f"被排除审核员（姓名匹配）：{_fmt(excluded_name)}；"
        f"剩余候选池：{_fmt(candidates)}（仅{len(candidates)}人）。已自动跳转终审，请人工确认。"
    )
    return {
        "recipient": "",
        "subject": f"【告警】工单#{submission.id} 初审候选池不足",
        "content": detail,
        "submission_id": submission.id,
    }


def build_admin_short_alert(submission, reason: str) -> dict:
    return {
        "recipient": "",
        "subject": f"【告警】工单#{submission.id} 已挂起等待超管介入",
        "content": f"工单 #{submission.id} 因{reason}已被挂起，请立即补充管理员或人工强制完成。",
        "submission_id": submission.id,
    }


def _fmt(users) -> str:
    if not users:
        return "[]"
    return "[" + ", ".join(f"{u.real_name or u.username}({u.student_id or '-'})" for u in users) + "]"


# ---------------------------------------------------------------- 发送
def _smtp_send(recipient: str, subject: str, content: str) -> None:
    if not settings.smtp_host:
        raise RuntimeError("邮件服务器未配置（SMTP_HOST 为空）")
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("报销审核系统", "utf-8")), settings.mail_from))
    msg["To"] = recipient
    if settings.smtp_use_ssl:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
    try:
        if not settings.smtp_use_ssl:
            server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.mail_from, [recipient], msg.as_string())
    finally:
        server.quit()


def _attempt(log: EmailLog) -> bool:
    try:
        _smtp_send(log.recipient, log.subject or "", log.content or "")
        log.status = "success"
        log.sent_at = utcnow()
        log.last_error = None
        return True
    except Exception as e:  # noqa: BLE001
        log.status = "failed"
        log.last_error = str(e)[:500]
        return False


def dispatch_emails(db: Session, tasks: list[dict]) -> None:
    """业务事务提交后调用；同步发送，失败记录待重试。

    收件人为空的任务视为“超管告警”（初审候选池不足/工单挂起），
    路由给所有超管账号；超管也收不到时置前端红色横幅。
    """
    for t in tasks:
        recipient = t.get("recipient") or ""
        if not recipient:
            message = f"{t.get('subject', '')}\n{t.get('content', '')}"
            if not _send_to_super_admins(db, message):
                set_config(db, "mail_service_banner", True)
            continue
        log = EmailLog(
            recipient=recipient,
            subject=t.get("subject"),
            content=t.get("content"),
            submission_id=t.get("submission_id"),
            status="pending",
        )
        db.add(log)
        db.flush()
        _attempt(log)
        log.retry_count = 1
        db.flush()
    db.commit()


def retry_failed_emails(db: Session) -> None:
    """Cron 调用：重试 failed 且重试次数 <4 且距上次尝试超过5分钟的邮件。"""
    now = utcnow()
    import datetime as dt

    cutoff = now - dt.timedelta(minutes=5)
    logs = (
        db.query(EmailLog)
        .filter(
            EmailLog.status == "failed",
            EmailLog.retry_count < RETRY_MAX_ATTEMPTS,
            EmailLog.updated_at < cutoff,
        )
        .all()
    )
    for log in logs:
        ok = _attempt(log)
        log.retry_count += 1
        if not ok and log.retry_count >= RETRY_MAX_ATTEMPTS:
            # 3次重试后仍失败 → 仅向所有超管发送告警
            alert_ok = _send_to_super_admins(
                db, f"工单#{log.submission_id} 的通知邮件发送失败，请线下通知相关方"
            )
            if not alert_ok:
                set_config(db, "mail_service_banner", True)
    db.commit()


def _send_to_super_admins(db: Session, message: str) -> bool:
    super_admins = [u for u in db.query(User).filter(User.role == "super_admin", User.is_deleted == False)]
    if not super_admins:
        return False
    all_ok = True
    for u in super_admins:
        if not u.email:
            all_ok = False
            continue
        log = EmailLog(
            recipient=u.email,
            subject="【告警】系统邮件服务异常",
            content=message,
            status="pending",
        )
        db.add(log)
        db.flush()
        if not _attempt(log):
            all_ok = False
        log.retry_count = 1
        db.flush()
    return all_ok


def mail_banner_active(db: Session) -> bool:
    return bool(get_config(db, "mail_service_banner", False))
