"""初始化脚本：创建数据表并初始化超级管理员账号。

用法：
    python -m app.seed                 # 使用环境变量 SUPER_ADMIN_USERNAME/SUPER_ADMIN_PASSWORD
    python -m app.seed -u admin -p 'Admin@1234' --email admin@example.com
"""
import argparse
import os

from .config import get_settings
from .database import Base, SessionLocal, engine
from .models import User
from .security import set_user_password

settings = get_settings()


def init_db():
    Base.metadata.create_all(bind=engine)
    print("数据表创建完成")


def create_super_admin(username: str, password: str, email: str):
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            print(f"超级管理员 {username} 已存在，跳过")
            return
        user = User(
            username=username,
            role="super_admin",
            real_name="超级管理员",
            email=email or "",
            password_changed_at=None,  # 首次登录强制改密
        )
        set_user_password(user, password)
        db.add(user)
        db.commit()
        print(f"超级管理员 {username} 创建成功（首次登录需修改密码）")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="初始化数据库与超级管理员")
    parser.add_argument("-u", "--username", default=os.getenv("SUPER_ADMIN_USERNAME", "superadmin"))
    parser.add_argument("-p", "--password", default=os.getenv("SUPER_ADMIN_PASSWORD", "Admin@1234"))
    parser.add_argument("--email", default=os.getenv("SUPER_ADMIN_EMAIL", ""))
    args = parser.parse_args()

    init_db()
    create_super_admin(args.username, args.password, args.email)


if __name__ == "__main__":
    main()
