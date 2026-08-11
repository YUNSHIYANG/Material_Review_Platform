"""FastAPI 应用入口。"""
import logging
import os
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import Base, engine, get_db
from .deps import TOKEN_COOKIE
from .models import User
from .routers import admin_router, auth, files, staff, super_admin, team
from .timeout_scanner import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")


def _setup_file_logging() -> None:
    """把应用与 uvicorn 的日志同时写入 LOG_DIR/app.log（配合持久卷挂载，容器重建不丢日志）。

    日志按 10MB 轮转、保留 5 份；stdout 输出保持原样（docker compose logs 仍可用）。
    """
    log_dir = os.environ.get("LOG_DIR", "/app/logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        handler = RotatingFileHandler(
            os.path.join(log_dir, "app.log"), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        formatter.converter = lambda ts: time.gmtime(ts + 8 * 3600)  # 文件日志统一使用东八区时间
        handler.setFormatter(formatter)
        for name in ("", "uvicorn", "uvicorn.access", "uvicorn.error", "app"):
            logging.getLogger(name).addHandler(handler)
        logger.info("文件日志已启用：%s/app.log", log_dir)
    except Exception as e:  # noqa: BLE001 日志目录不可写时不影响服务启动
        logger.warning("文件日志初始化失败（忽略）：%s", e)


_setup_file_logging()

settings = get_settings()

EXEMPT_PATHS = {"/api/auth/login", "/api/auth/change-password", "/api/auth/me", "/health"}


def _extract_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get(TOKEN_COOKIE, "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:
        # 持久卷升级：先补齐旧表缺失列（create_all 不会给已有表加列），再建缺失的新表
        from .database import sync_missing_columns

        sync_missing_columns(engine, Base)
        Base.metadata.create_all(bind=engine)
        logger.info("数据表已就绪（auto_create_tables=True）")
    if not settings.smtp_host:
        logger.warning(
            "SMTP_HOST 未配置：系统邮件将全部发送失败（记录为 failed 并进入重试队列）。"
            "请在环境变量中配置 SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/MAIL_FROM 后重启。"
        )
    scheduler = start_scheduler()
    yield
    if scheduler:
        scheduler.shutdown()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(",") if getattr(settings, "cors_origins", None) else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_first_login_password_change(request: Request, call_next):
    """首次登录强制改密：未改密用户仅可访问登录/改密/我的信息接口。"""
    path = request.url.path
    if path in EXEMPT_PATHS or not path.startswith("/api/"):
        return await call_next(request)
    token = _extract_token(request)
    if token:
        try:
            from .security import decode_access_token

            payload = decode_access_token(token)
            # 使用应用级 get_db 依赖（测试中会被 override 指向同一连接）
            get_db_fn = request.app.dependency_overrides.get(get_db, get_db)
            own_session = get_db_fn is get_db
            db = next(get_db_fn())
            try:
                user = db.get(User, int(payload["sub"]))
                if user and not user.is_deleted and user.password_changed_at is None:
                    return JSONResponse(status_code=403, content={"detail": "NEED_PASSWORD_CHANGE"})
            finally:
                if own_session:
                    db.close()
        except Exception:
            pass
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(team.router)
app.include_router(staff.router)
app.include_router(admin_router.router)
app.include_router(super_admin.router)
app.include_router(files.router)

# ---- 前端静态资源（Docker 构建时拷贝到 static/，实现前后端同源） ----
STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))
_ASSETS_DIR = os.path.join(STATIC_DIR, "assets")


@app.middleware("http")
async def cache_control_middleware(request: Request, call_next):
    """SPA 缓存策略：index.html 必须每次重新校验（no-cache），避免重建后浏览器沿用旧壳；
    带内容哈希的资源文件可长期缓存（immutable），哈希变化即视为新 URL。"""
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path == "/" or path.endswith("index.html"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def _serve_static(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    file_path = os.path.join(STATIC_DIR, full_path)
    if full_path and os.path.isfile(file_path):
        return FileResponse(file_path)
    index = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index):
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Not Found")


if os.path.isdir(_ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")

if os.path.isdir(STATIC_DIR):
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        return _serve_static(full_path)
