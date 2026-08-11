"""应用配置：全部可通过环境变量 / .env 覆盖。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "材料协同审核平台"
    # 安全
    secret_key: str = "CHANGE_ME__please_use_a_long_random_secret"
    token_expire_hours: int = 12
    cors_origins: str = "*"
    # 数据库 / Redis
    database_url: str = "postgresql+psycopg://review:review@localhost:5432/review"
    redis_url: str = "redis://localhost:6379/0"
    auto_create_tables: bool = True
    # 文件
    upload_dir: str = "uploads"
    max_file_size_mb: int = 50
    # 业务阈值
    timeout_hours: int = 72
    cycle_threshold: int = 3          # 同人循环 ≥ 3 次挂起
    global_reassign_threshold: int = 5  # 全局重分配 ≥ 5 次挂起
    assignment_pending_multiplier: float = 2.0  # 分配算法：待办数 < 平均待办数*此倍数 才参与本轮分配
    cron_interval_minutes: int = 5
    # 登录安全
    login_fail_limit: int = 5
    login_lock_minutes: int = 30
    # 邮件
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_ssl: bool = True
    mail_from: str = "review@example.com"
    site_base_url: str = "http://localhost:8000"
    # 锁
    lock_ttl: int = 30
    cron_lock_ttl: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
