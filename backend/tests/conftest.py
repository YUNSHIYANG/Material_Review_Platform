"""测试基座：SQLite 内存库 + 禁用 Redis/SMTP，直接使用业务函数做单元测试。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "")
os.environ.setdefault("AUTO_CREATE_TABLES", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-jwt-sha256-0123456789abcdef")
os.environ.setdefault("SMTP_HOST", "")
os.environ.setdefault("UPLOAD_DIR", "test_uploads")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app
from app.models import Submission, User
from app.security import hash_password


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    s = TestingSessionLocal()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db):
    from app.database import get_db

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def make_user(
    db,
    role="staff",
    username=None,
    real_name=None,
    student_id=None,
    email="user@example.com",
    member_names=None,
    member_student_ids=None,
    password="Passw0rd!x",
    password_changed=True,
):
    u = User(
        username=username or f"{role}_{real_name or 'u'}_{id(object())}",
        password_hash=hash_password(password),
        role=role,
        real_name=real_name,
        student_id=student_id,
        email=email,
        member_names=member_names,
        member_student_ids=member_student_ids,
        password_changed_at=__import__("app.utils", fromlist=["utcnow"]).utcnow() if password_changed else None,
    )
    db.add(u)
    db.flush()
    if role == "team":
        u.team_id = u.id
    return u


def make_submission(db, team, **kwargs):
    submit_round = kwargs.pop("submit_round", 1)
    status = kwargs.pop("status", "pending")
    sub = Submission(team_id=team.id, submit_round=submit_round, status=status, **kwargs)
    db.add(sub)
    db.flush()
    return sub
