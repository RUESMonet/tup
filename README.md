# TUP 图片生成优化器

TUP 是一个本地优先的 AI 图片生成与创作工作台。后端使用 FastAPI，前端使用 React/Vite。它可以对提示词进行分析和优化，调用 OpenAI 兼容的图片/视频模型，保存项目、画布、素材和生成任务，并通过评分与迭代流程帮助获得更稳定的生成结果。

## 功能概览

- **图片生成优化**：提交提示词后自动执行提示词预评估、可选提示词改写、图片生成、视觉评分和迭代优化。
- **项目与画布工作台**：支持项目、画布节点、边、分支操作、修复版本、候选图批次、最终提交预览等工作流。
- **多媒体生成**：支持图片生成、图片编辑和视频生成；本地开发可使用 mock 图片/视频避免外部模型调用。
- **提示词能力**：包含提示词优化、参考案例、模式洞察、Prompt Skill、会话内提示词优化等接口。
- **账号与额度**：提供注册、登录、会话 Cookie、账户额度和交易记录；可通过环境变量初始化管理员。
- **管理后台**：支持模型配置、用户/任务/素材审核队列等管理接口。
- **本地持久化**：默认使用 SQLite（`data/app.db`）保存账号、项目、资产和任务状态。

## 技术栈

- Backend：Python 3.11+、FastAPI、Pydantic、httpx、Uvicorn、SQLite
- Frontend：React 19、Vite 6、Ant Design、lucide-react
- Tests：pytest、pytest-asyncio
- Model API：OpenAI 兼容的图片、评估、提示词草稿和视频接口

## 快速开始

### 1. 安装依赖

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
npm install
```

### 2. 配置环境变量

复制环境变量模板：

```bash
cp .env.example .env
```

本地无外部模型调试时，建议先使用 mock：

```env
USE_MOCK_IMAGES=true
USE_MOCK_VIDEOS=true
```

接入真实模型时，至少需要配置可用的 OpenAI 兼容 Key 和模型名，例如：

```env
OPENAI_API_KEY=...
OPENAI_IMAGE_MODEL=gpt-image-2
OPENAI_EVALUATOR_MODEL=gpt-4.1-mini
OPENAI_PROMPT_DRAFT_MODEL=gpt-5.5
```

### 3. 启动开发服务

```bash
npm run dev
```

该命令会同时启动：

- 后端：`http://127.0.0.1:8000`
- 前端：`http://127.0.0.1:5173` / `http://localhost:5173`

也可以分开启动：

```bash
npm run dev:backend
npm run dev:frontend
```

## 命令参考

<!-- AUTO-GENERATED:COMMANDS START -->
| 命令 | 说明 |
| --- | --- |
| `npm run dev` | 同时启动 FastAPI 后端和 Vite 前端，退出时清理后台子进程。 |
| `npm run dev:backend` | 启动 `src.main:app`，只监听 `src` 下的 Python 文件热重载，避免 `.venv`、`node_modules` 和前端构建产物触发重启。 |
| `npm run dev:frontend` | 在 frontend workspace 启动 Vite 开发服务器，端口固定为 `5173`。 |
| `npm run build` | 构建 frontend workspace，产物输出到 `frontend/dist`。 |
| `npm run preview` | 在端口 `4173` 预览前端生产构建。 |
| `.venv/bin/python -m pytest` | 运行后端测试套件。 |
| `.venv/bin/python -m pytest tests/test_api.py` | 只运行 API 边界相关测试。 |
<!-- AUTO-GENERATED:COMMANDS END -->

> 当前 `package.json` 未配置 lint、formatter、前端测试或 TypeScript typecheck 脚本。

## 环境变量

<!-- AUTO-GENERATED:ENV START -->
| 变量 | 必填 | 说明 | 示例/默认值 |
| --- | --- | --- | --- |
| `USE_MOCK_IMAGES` | 否 | 为 `true` 时图片生成走本地 SVG mock，便于无外部模型调试。 | `true` |
| `USE_MOCK_VIDEOS` | 否 | 为 `true` 时视频生成走 mock，便于调试完整项目流程。 | `true` |
| `PROMPT_PASS_THRESHOLD` | 否 | 提示词评分通过阈值。 | `6.0` |
| `VISUAL_PASS_THRESHOLD` | 否 | 视觉评分通过阈值。 | `8.0` |
| `MAX_ITERATIONS` | 否 | 图片优化流水线最大迭代次数。 | `3` |
| `REQUEST_TIMEOUT_SECONDS` | 否 | 外部模型请求超时时间，单位秒。 | `60` |
| `MODEL_REQUEST_RETRIES` | 否 | 外部模型请求失败后的重试次数。 | `2` |
| `AUTH_REQUIRED` | 否 | 是否强制高成本接口鉴权；留空时设置 `API_KEY` 会自动启用。 | 空 / `true` |
| `ALLOW_PUBLIC_REGISTRATION` | 否 | 鉴权开启时是否允许公开注册。 | `false` |
| `API_KEY` | 生产建议 | 高成本接口的 Bearer Token 或 `X-API-Key`。 | 空 |
| `RATE_LIMIT_REQUESTS` | 否 | 单个调用方在限流窗口内最多请求次数。 | `30` |
| `RATE_LIMIT_WINDOW_SECONDS` | 否 | 限流窗口长度，单位秒。 | `60` |
| `OPENAI_BASE_URL` | 否 | 默认 OpenAI 兼容 API 地址。 | `https://api.openai.com/v1` |
| `OPENAI_IMAGE_BASE_URL` | 否 | 图片模型专用 API 地址；留空使用 `OPENAI_BASE_URL`。 | 空 |
| `OPENAI_EVALUATOR_BASE_URL` | 否 | 评分/分析模型专用 API 地址；留空使用 `OPENAI_BASE_URL`。 | 空 |
| `OPENAI_PROMPT_DRAFT_BASE_URL` | 否 | 提示词改写模型专用 API 地址；留空使用评分模型地址。 | 空 |
| `OPENAI_API_KEY` | 真实模型必填 | 通用 OpenAI 兼容 Key，专用 Key 留空时作为兜底。 | 空 |
| `OPENAI_IMAGE_API_KEY` | 否 | 图片模型专用 Key。 | 空 |
| `OPENAI_IMAGE_MODEL` | 真实图片模型必填 | 图片生成模型名。 | `gpt-image-2` |
| `OPENAI_EVALUATOR_API_KEY` | 否 | 文本分析/视觉评估模型专用 Key。 | 空 |
| `OPENAI_EVALUATOR_MODEL` | 真实评估必填 | 文本分析、视觉氛围评估模型名。 | `gpt-4.1-mini` |
| `OPENAI_PROMPT_DRAFT_MODEL` | 真实草稿必填 | AI 提示词改写/文案草稿模型名。 | `gpt-5.5` |
| `MODEL_BASE_URL_ALLOWED_HOSTS` | 否 | 管理后台允许保存的模型 Base URL 主机白名单，多个用英文逗号分隔。 | 空 |
| `ASSET_UPLOAD_DIR` | 否 | 图片、视频和生成资产存储目录。 | `uploads` |
| `ASSET_UPLOAD_MAX_BYTES` | 否 | 单个上传文件大小限制，单位字节。 | `8388608` |
| `DATABASE_PATH` | 否 | SQLite 数据库路径。 | `data/app.db` |
| `SESSION_MAX_AGE_SECONDS` | 否 | 登录会话有效期。 | `604800` |
| `SECURE_SESSION_COOKIES` | 否 | HTTPS 部署时设为 `true`，本地 HTTP 开发保持 `false`。 | `false` |
| `ADMIN_USERNAME` | 否 | 初始化管理员用户名；与邮箱、密码三项必须同时填写。 | 空 |
| `ADMIN_EMAIL` | 否 | 初始化管理员邮箱；与用户名、密码三项必须同时填写。 | 空 |
| `ADMIN_PASSWORD` | 否 | 初始化管理员密码；与用户名、邮箱三项必须同时填写。 | 空 |
| `VIDEO_BASE_URL` | 否 | 视频模型 API 地址。 | `https://api.openai.com/v1` |
| `VIDEO_API_KEY` | 真实视频模型必填 | 视频模型 API Key。 | 空 |
| `VIDEO_MODEL` | 真实视频模型必填 | 视频生成模型名。 | `video-generation` |
| `VIDEO_GENERATE_ENDPOINT` | 否 | 视频生成接口路径。 | `/videos/generations` |
<!-- AUTO-GENERATED:ENV END -->

## API 概览

<!-- AUTO-GENERATED:API START -->
| 模块 | 主要接口 |
| --- | --- |
| 图片优化 | `POST /api/generate`、`GET /api/task/{task_id}`、`GET /api/task/{task_id}/history`、`GET /api/models`、`POST /api/assets/upload` |
| 参考与提示词 | `GET /api/reference`、`POST /api/reference/analyze`、`GET /api/reference/patterns`、`POST /api/reference/draft`、`POST /api/reference/draft/stream`、`POST /api/prompt/optimize` |
| 认证 | `POST /api/auth/register`、`POST /api/auth/login`、`GET /api/auth/me`、`POST /api/auth/logout` |
| 账户额度 | `GET /api/account/credits`、`GET /api/account/transactions` |
| 项目 | `GET /api/projects`、`POST /api/projects`、`GET /api/projects/{project_id}`、`POST /api/projects/{project_id}/assets/upload`、`GET /api/projects/{project_id}/assets`、`GET /api/projects/{project_id}/tasks` |
| 项目生成任务 | `POST /api/projects/{project_id}/generate/image`、`POST /api/projects/{project_id}/generate/image-edit`、`POST /api/projects/{project_id}/generate/video`、`GET /api/tasks/{task_id}`、`GET /api/tasks/{task_id}/history` |
| 画布 | `GET/POST /api/projects/{project_id}/canvases`、`GET /api/canvases/{canvas_id}`、节点/边增删改、位置更新、编译、分支操作、修复版本、媒体审批、最终提交等接口。 |
| 会话 | `POST /api/projects/{project_id}/conversations`、`GET /api/projects/{project_id}/conversations`、`GET /api/conversations/{conversation_id}`、`POST /api/conversations/{conversation_id}/messages`、`POST /api/conversations/{conversation_id}/prompt/optimize` |
| 管理后台 | `GET/POST /api/admin/model-settings`、`GET /api/admin/users`、`GET /api/admin/tasks`、`GET /api/admin/assets/review-queue`、`POST /api/admin/assets/{asset_id}/review` |
<!-- AUTO-GENERATED:API END -->

高成本接口受 `AUTH_REQUIRED` / `API_KEY` 和限流配置保护。API Key 可通过 `Authorization: Bearer <token>` 或 `X-API-Key: <token>` 传递；登录态接口也支持 HttpOnly `session` Cookie。

## 构建与部署

构建前端：

```bash
npm run build
```

`frontend/dist` 存在时，FastAPI 会把它挂载到 `/`，因此可以由同一个后端进程提供 API 和静态前端页面。

仓库包含 `docker-compose.yml`，其中定义了 Postgres 和 n8n 服务，主要用于历史/扩展工作流；当前默认后端使用 SQLite，启动本地开发服务不依赖 Postgres 或 n8n。

## 测试

```bash
.venv/bin/python -m pytest
```

Pytest 配置位于 `pyproject.toml`：

- `asyncio_mode = "auto"`
- `pythonpath = ["."]`
- `testpaths = ["tests"]`

按边界定位测试：

- API 与鉴权：`tests/test_api.py`、`tests/test_auth.py`
- 项目/画布/生成任务：`tests/test_projects.py`、`tests/test_canvas_routes.py`、`tests/test_video_router.py`
- 模型路由与流水线：`tests/test_model_router.py`、`tests/test_pipeline.py`
- 提示词、参考案例和视觉评估：`tests/test_prompt_evaluator.py`、`tests/test_prompt_optimizer.py`、`tests/test_prompt_skill_agent.py`
- 账户与管理：`tests/test_billing.py`、`tests/test_admin_model_settings.py`、`tests/test_admin_operations.py`

## 常见问题

### `python: command not found`

macOS 默认可能没有 `python` 命令，请使用：

```bash
python3 --version
.venv/bin/python --version
```

### `API key is not configured for model: openai`

没有开启 `USE_MOCK_IMAGES=true`，也没有配置可用的 `OPENAI_API_KEY` 或 `OPENAI_IMAGE_API_KEY`。本地调试建议先启用 mock。

### `Invalid or missing API key`

`.env` 中设置了 `API_KEY` 或启用了 `AUTH_REQUIRED=true`，但请求没有携带鉴权信息。前端本地调试时可先留空 `API_KEY`；API 调用需要传 `Authorization: Bearer ...` 或 `X-API-Key`。

### 上传文件失败

仅支持 PNG、JPEG、WebP 图片和 MP4、WebM、MOV 视频。大小限制由 `ASSET_UPLOAD_MAX_BYTES` 控制，默认 8 MiB。

### 前端页面访问不到后端

确认 `npm run dev` 中后端和前端都已启动；Vite 默认使用相对 `/api/...` 调用后端，本地开发地址通常是 `http://127.0.0.1:5173`。
