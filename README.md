# 材料协同审核平台（Material Review Platform）

基于《材料协同审核平台 产品设计文档》实现的一套**多角色在线材料协同审核系统**，适用于需要“多人分工初审 + 管理员终审 + 结果邮件反馈”的审核场景（如报销材料、申报材料等）。

**核心流程**：提交人上传材料 → 双人随机初审（72h 超时自动跳过）→ 管理员智能派发终审（72h 超时自动换人 + 双阈值兜底）→ 邮件反馈结果。

**设计亮点**：
- 双盲独立初审，审核员互不可见、同团队自动回避（学工号优先、姓名兜底）；
- 双重排序分配算法实现负载均衡，超时人员自动降权；
- 终审环节提供“同人循环 ≥3 次 / 全局重分配 ≥5 次 / 交替循环检测”双阈值兜底，杜绝无限循环死锁；
- 全部写操作采用“Redis 分布式锁 + 乐观锁 + 行锁”三重并发保护。

---

## 1. 技术栈

| 层 | 技术 |
| :--- | :--- |
| 后端 | Python 3.12+ / FastAPI / SQLAlchemy 2.0 |
| 数据库 | PostgreSQL（推荐）或 SQLite（本地开发/测试） |
| 缓存与分布式锁 | Redis（`SET NX`，不可用时自动降级进程内锁） |
| 任务调度 | APScheduler（每 5 分钟超时扫描 + 邮件重试 + 每日衰减） |
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + Pinia + Vue Router |
| 认证 | JWT（Bearer Token） + bcrypt 密码哈希 |

## 2. 目录结构

```
review-platform/
├── backend/
│   ├── app/                     # FastAPI 应用
│   │   ├── main.py              # 入口（含强制改密中间件、CORS、Cron 启动）
│   │   ├── config.py            # 配置（环境变量/.env）
│   │   ├── database.py          # 引擎与会话
│   │   ├── models.py            # 6+1 张表模型
│   │   ├── security.py          # 密码/Token/登录锁定
│   │   ├── locking.py           # Redis 分布式锁 + 本地锁降级
│   │   ├── assignment.py        # 双重排序分配算法
│   │   ├── flows.py             # 状态机核心操作（提交/审核/撤回/干预/超时判定）
│   │   ├── timeout_scanner.py   # Cron 定时任务
│   │   ├── email_service.py     # 邮件模板/发送/重试/超管告警横幅
│   │   ├── config_store.py      # 系统配置存取（业务阈值可后台修改）
│   │   ├── audit.py             # 超管操作审计快照
│   │   ├── routers/             # 四角色 API 路由
│   │   └── seed.py              # 初始化数据库 + 超级管理员
│   ├── alembic/                 # Alembic 迁移脚手架
│   └── tests/                   # 29 个核心业务/API 单测
├── frontend/                    # Vue3 前端（开发端口 5173，/api 代理到 8000）
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## 3. 快速开始

### 3.1 Docker 一键部署（推荐）

```bash
# 1. 复制环境变量并修改 SECRET_KEY / 超管密码 / SMTP
cp .env.example .env

# 2. 启动（自动建表 + 初始化超级管理员 + 启动前后端）
docker compose up -d --build

# 3. 访问
#    前端与后端同源: http://<服务器IP>:8000
```

首次登录超管账号（默认 `superadmin / Admin@1234`）会被强制修改密码。

> 若仅用于本地体验，可不配置 SMTP；系统会把邮件标记为失败并进入重试队列，超管端显示黄色提示，不影响核心审核流程。

### 3.2 本地开发

后端：

```bash
cd backend
pip install -r requirements.txt

# 使用 PostgreSQL（推荐）：
#   docker run -d -p 5432:5432 -e POSTGRES_USER=review -e POSTGRES_PASSWORD=review -e POSTGRES_DB=review postgres:16
#   docker run -d -p 6379:6379 redis:7
export DATABASE_URL=postgresql+psycopg://review:review@localhost:5432/review
export REDIS_URL=redis://localhost:6379/0
export SMTP_HOST=... SMTP_USER=... SMTP_PASSWORD=...   # 可选，不配置则邮件发送失败自动进重试队列

# 不使用 PostgreSQL 时可用 SQLite 快速体验（无行锁，仅开发）：
#   export DATABASE_URL=sqlite:///./dev.db

python -m app.seed -u superadmin -p 'Admin@1234' --email admin@example.com   # 建表 + 超管
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 （/api 已代理到 8000）
```

### 3.3 运行测试

```bash
cd backend
python -m pytest tests -v     # 29 个用例：分配算法/状态机/超时兜底/API 链路
```

## 4. 角色与登录

| 角色 | 登录后首页 | 权限 |
| :--- | :--- | :--- |
| 提交人（团队） | `/team` | 提交材料、进度看板、撤回、查看反馈 |
| 审核员 | `/staff` | 初审待办、通过/不通过、撤回重审（含补时逻辑） |
| 管理员 | `/admin` | 终审待办、初审意见墙、最终裁定 |
| 超级管理员 | `/super` | 用户管理、密码重置、工单干预、邮件日志、系统配置、负载监控、审计 |

**账号安全**：首次登录强制改密（密码≥8位且含大小写字母+数字+特殊字符）；连续 5 次登录失败锁定 30 分钟；超管敏感操作需二次输入自身密码确认。

**用户批量导入/导出（超管端）**：
- **导入**：超管在“用户管理”页下载 Excel 模板 → 按模板逐行填写（角色取值 `team/staff/admin/super_admin`；提交人须附成员姓名/学工号 JSON 数组）→ 上传导入，逐行校验并返回成功/失败明细（失败行不影响其他行）。
- **导出账密**：超管可一键导出全部用户账号与密码（.xlsx）。系统会保留最近一次由系统/超管设置（或用户自行修改）的密码明文（`users.plain_password`），供超管发放/恢复账号；导出操作记录审计日志，请妥善保管导出文件。

所有账号由超管在后台预置，不开放注册。

## 5. 核心业务规则速览

- **状态机**：`pending → first_reviewing → admin_reviewing → passed/rejected`，可撤回至 `withdrawn`；异常挂起至 `pending_admin_intervention`（提交人端显示“加急处理中”，撤回按钮隐藏且后端强制 403 拦截）。
- **提交限制**：同一团队存在未终结工单时不可再次提交；最近一次提交为“未通过”时自动关联父工单，管理员端可展开查看全部历史驳回记录。
- **初审**：双重排序算法（待办最少 → 虚拟完成数最少 → id 最小）分配 2 人，优先按学工号、降级按标准化姓名排除同团队成员；候选池不足 2 人自动跳过并邮件告警（含排除明细）。
- **终审**：独占派发 1 名管理员；72h 未处理自动换人（原管理员降权、`total_reassign_count+1`）；同人循环≥3 次 / 全局重分配≥5 次 / 交替循环（重分配≥3 且去重管理员≤2）→ 自动挂起待超管介入，超管后台红色横幅逐条告警。
- **超管干预**：强制通过/驳回（工作量归零 + `system_forced_penalty+1`；若管理员已提交终审则回退其完成数-1）、重新派发（重置计数器并追加 `-1` 标记）、补充初审（仅 `insufficient_staff` 且未派发终审管理员时可操作）。所有干预记录完整前后快照审计。
- **撤回**：提交人可在终结前撤回（挂起状态禁止）；审核员可在管理员终审前撤回初审结论，场景 A（有效意见<2）可补时 3 小时（消耗 `delay_used` 额度），场景 B（双人已提交）不补时。
- **邮件**：模板严格按文档 5.5；失败自动重试（间隔 5 分钟，最多 3 次），仍失败仅通知超管；超管邮箱也失败则前端全局红色横幅持续提示直至手动标记已处理。
- **并发安全**：所有写操作 = Redis 分布式锁（`lock:submission:{id}`，TTL 30s）+ 乐观锁（`version`）+ 数据库事务行锁；Cron 使用独立分布式锁防多实例重复执行。

## 6. 环境变量说明

见 [.env.example](./.env.example)。关键项：`SECRET_KEY`（务必修改）、`DATABASE_URL`、`REDIS_URL`、`SMTP_*`、`UPLOAD_DIR`、`MAX_FILE_SIZE_MB`（默认 50MB）、`TIMEOUT_HOURS`（默认 72）、`CYCLE_THRESHOLD`/`GLOBAL_REASSIGN_THRESHOLD`（默认 3/5，亦可在超管后台修改，仅对新派发工单生效）。

### 6.1 邮件服务配置（SMTP）

系统所有通知（任务指派、审核结果、超管告警）均通过 SMTP 发送。**若未配置，邮件将全部发送失败**：邮件日志标记为 `failed`（原因“SMTP_HOST 为空”），Cron 每 5 分钟自动重试，仍失败后仅向超管告警；若超管邮箱同样不可达，则前端出现红色横幅，且超管后台概览页会显示“邮件服务未配置”黄色提示。

请**单独为系统申请一个发信邮箱**（任选其一），并在服务器 `.env` 中配置：

| 邮箱类型 | SMTP_HOST | SMTP_PORT | 说明 |
| :--- | :--- | :--- | :--- |
| QQ 邮箱 | `smtp.qq.com` | `465` | 在 QQ 邮箱“设置→账号→开启 SMTP”后获取 16 位**授权码**作为密码 |
| 163 邮箱 | `smtp.163.com` | `465` | 开启“SMTP 服务”后获取**授权码** |
| 企业微信/腾讯企业邮箱 | `smtp.exmail.qq.com` | `465` | 管理员在后台开通 SMTP，使用账号密码或授权码 |
| 阿里云/腾讯云邮件推送 | 参考云厂商文档 | `465`/`587` | 注意默认云服务器 25 端口可能被封，务必使用 465(SSL) |

```dotenv
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=your_account@qq.com
SMTP_PASSWORD=你的授权码（非登录密码）
SMTP_USE_SSL=true
MAIL_FROM=your_account@qq.com
```

配置完成后重启服务：`docker compose up -d --build`。可在超管端“邮件日志”页查看发送状态与失败原因。

## 7. 生产部署建议

- 使用 `docker compose up -d --build` 部署到阿里云/腾讯云，安全组开放 `8000` 端口（或前置 Nginx 反代 + HTTPS）。
- 持久化卷：`pgdata`（数据库）、`uploads`（附件）。上传目录按 `SHA256(团队名)[:16]` 分目录隔离，文件名前缀 `{hash}_team{id}_round{n}_`。
- 单机单实例即可满足本类项目规模；如需多实例，Redis 锁 + Cron 锁已保证不冲突。
- 迁移：开发期 `auto_create_tables=True` 自动建表；如需 Alembic 管理：`cd backend && alembic revision --autogenerate -m init && alembic upgrade head`。

## 8. 与文档约定的两处实现说明

1. **提交人撤回时释放未提交审核员的待办**：文档 5.1.3 仅列明回退已提交意见者的 `total_completed_count`；为保证分配算法公平，实现中对“已分配但尚未提交、未超时、未撤回”的初审员同时释放其 `current_pending_count`（否则其待办将虚增）。
2. **强制终结允许对已终结工单改判**：文档“管理员已提交终审”回退分支（完成数-1、惩罚+1）在“管理员提交后工单已终结”的场景下同样适用，故 `force_finalize` 亦接受 `passed/rejected` 状态，用于超管纠错改判。

## 9. 开源与贡献

本项目以 [MIT](./LICENSE) 协议开源，欢迎 Star、Issue 与 Pull Request。

- **提交 Issue**：请描述复现步骤、期望行为与实际行为、日志/截图。
- **代码规范**：后端遵循 PEP 8，前端遵循 Vue3 `<script setup>` 组合式写法；新增/修改功能请补充对应单测（`backend/tests/`）。
- **安全报告**：发现安全问题请勿公开提交 Issue，请先通过仓库管理员邮箱私下联系。

**声明**：仓库已剥离真实业务数据与凭据，仅保留通用业务逻辑；`uploads/`、`dev.db`、`*.dump`、`.env` 等均不在版本控制范围内（见 [.gitignore](./.gitignore)）。
