# TUP Image Generation Optimizer / TUP 图片生成优化器

TUP is a local-first AI image generation and creative workspace. It uses a FastAPI backend and a React/Vite frontend to analyze prompts, generate images through OpenAI-compatible providers, score visual results, and iterate prompts toward better outputs.

> 中文：TUP 是一个本地优先的 AI 图片生成与创作工作台。后端使用 FastAPI，前端使用 React/Vite，可分析提示词、调用 OpenAI 兼容模型生成图片、进行视觉评分，并通过迭代优化提示词与结果。

## Features / 功能概览

- **Image optimization loop**: prompt pre-evaluation, optional prompt rewriting, image generation, visual scoring, and automatic iteration.
  - 中文：图片生成优化流水线，包括提示词预评估、可选改写、图片生成、视觉评分和自动迭代。
- **Project and canvas workspace**: projects, canvases, nodes, edges, branch operations, repair versions, image batches, and final submission preview.
  - 中文：项目与画布工作台，支持项目、画布节点/边、分支操作、修复版本、候选图批次和最终提交预览。
- **Multimedia generation**: image generation, image editing, and video generation; local mock modes are available for development without external model calls.
  - 中文：支持图片生成、图片编辑和视频生成；本地开发可启用 mock 模式，避免调用外部模型。
- **Prompt intelligence**: prompt optimization, reference analysis, pattern insights, Prompt Skill, and conversation-based prompt refinement.
  - 中文：提供提示词优化、参考分析、模式洞察、Prompt Skill，以及会话内提示词优化。
- **Accounts and credits**: registration, login, session cookies, credit balances, transaction history, and optional admin bootstrap.
  - 中文：提供注册、登录、会话 Cookie、额度余额、交易记录，以及可选管理员初始化。
- **Admin console APIs**: model settings, users, tasks, and asset review queues.
  - 中文：管理接口支持模型配置、用户、任务和素材审核队列。
- **Local persistence**: SQLite is used by default for accounts, projects, assets, and task state.
  - 中文：默认使用 SQLite 保存账号、项目、素材和任务状态。

## Tech Stack / 技术栈

- Backend: Python 3.11+, FastAPI, Pydantic, httpx, Uvicorn, SQLite
- Frontend: React 19, Vite 6, Ant Design, lucide-react
- Tests: pytest, pytest-asyncio
- Model APIs: OpenAI-compatible image, evaluation, prompt drafting, and video endpoints

> 中文：后端为 Python/FastAPI，前端为 React/Vite，测试使用 pytest，模型接口遵循 OpenAI 兼容协议。

## Quick Start / 快速开始

### 1. Install dependencies / 安装依赖

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
npm install
```

### 2. Configure environment variables / 配置环境变量

Copy the template:

```bash
cp .env.example .env
```

For local development without external model calls, enable mock mode:

```env
USE_MOCK_IMAGES=true
USE_MOCK_VIDEOS=true
```

For real model providers, configure an OpenAI-compatible key and model names:

```env
OPENAI_API_KEY=...
OPENAI_IMAGE_MODEL=gpt-image-2
OPENAI_EVALUATOR_MODEL=gpt-4.1-mini
OPENAI_PROMPT_DRAFT_MODEL=gpt-5.5
```

> 中文：复制 `.env.example` 为 `.env`。本地无外部模型时建议开启 `USE_MOCK_IMAGES=true` 和 `USE_MOCK_VIDEOS=true`；接入真实模型时填写 OpenAI 兼容 Key 和模型名。

### 3. Start development servers / 启动开发服务

```bash
npm run dev
```

This starts both services:

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5173` / `http://localhost:5173`

You can also start them separately:

```bash
npm run dev:backend
npm run dev:frontend
```

> 中文：`npm run dev` 会同时启动后端和前端；也可以用 `dev:backend` 与 `dev:frontend` 分开启动。

## Commands / 命令参考

<!-- AUTO-GENERATED:COMMANDS START -->
| Command | Description |
| --- | --- |
| `npm run dev` | Start the FastAPI backend and Vite frontend together; child processes are cleaned up on exit. / 同时启动 FastAPI 后端和 Vite 前端，退出时清理子进程。 |
| `npm run dev:backend` | Start `src.main:app` with hot reload limited to Python files under `src`, avoiding repeated reloads from `.venv`, `node_modules`, and frontend build artifacts. / 启动后端并只监听 `src` 下 Python 文件热重载，避免依赖目录和前端产物触发重启。 |
| `npm run dev:frontend` | Start the Vite dev server from the frontend workspace on port `5173`. / 在 frontend workspace 启动 Vite 开发服务器，端口为 `5173`。 |
| `npm run build` | Build the frontend workspace into `frontend/dist`. / 构建前端，产物输出到 `frontend/dist`。 |
| `npm run preview` | Preview the production frontend build on port `4173`. / 在端口 `4173` 预览前端生产构建。 |
| `.venv/bin/python -m pytest` | Run the backend test suite. / 运行后端测试套件。 |
| `.venv/bin/python -m pytest tests/test_api.py` | Run API boundary tests only. / 仅运行 API 边界测试。 |
<!-- AUTO-GENERATED:COMMANDS END -->

There are currently no configured lint, formatter, frontend test, or TypeScript typecheck scripts in `package.json`.

> 中文：当前 `package.json` 未配置 lint、formatter、前端测试或 TypeScript typecheck 脚本。

## Environment Variables / 环境变量

<!-- AUTO-GENERATED:ENV START -->
| Variable | Required | Description | Example / Default |
| --- | --- | --- | --- |
| `USE_MOCK_IMAGES` | No / 否 | Use local SVG mock image generation when `true`. / 为 `true` 时图片生成走本地 SVG mock。 | `true` |
| `USE_MOCK_VIDEOS` | No / 否 | Use mock video generation when `true`. / 为 `true` 时视频生成走 mock。 | `true` |
| `PROMPT_PASS_THRESHOLD` | No / 否 | Prompt evaluation pass threshold. / 提示词评分通过阈值。 | `6.0` |
| `VISUAL_PASS_THRESHOLD` | No / 否 | Visual evaluation pass threshold. / 视觉评分通过阈值。 | `8.0` |
| `MAX_ITERATIONS` | No / 否 | Maximum image optimization iterations. / 图片优化流水线最大迭代次数。 | `3` |
| `REQUEST_TIMEOUT_SECONDS` | No / 否 | External model request timeout in seconds. / 外部模型请求超时时间，单位秒。 | `60` |
| `MODEL_REQUEST_RETRIES` | No / 否 | Retry count for failed model requests. / 外部模型请求失败后的重试次数。 | `2` |
| `AUTH_REQUIRED` | No / 否 | Force authentication for high-cost endpoints; when empty, `API_KEY` enables auth automatically. / 是否强制高成本接口鉴权；留空时设置 `API_KEY` 会自动启用。 | empty / `true` |
| `ALLOW_PUBLIC_REGISTRATION` | No / 否 | Allow public registration when auth is enabled. / 鉴权开启时是否允许公开注册。 | `false` |
| `API_KEY` | Recommended in production / 生产建议 | Bearer token or `X-API-Key` for high-cost endpoints. / 高成本接口的 Bearer Token 或 `X-API-Key`。 | empty / 空 |
| `RATE_LIMIT_REQUESTS` | No / 否 | Maximum requests per caller in each rate-limit window. / 单个调用方在限流窗口内最多请求次数。 | `30` |
| `RATE_LIMIT_WINDOW_SECONDS` | No / 否 | Rate-limit window length in seconds. / 限流窗口长度，单位秒。 | `60` |
| `OPENAI_BASE_URL` | No / 否 | Default OpenAI-compatible API base URL. / 默认 OpenAI 兼容 API 地址。 | `https://api.openai.com/v1` |
| `OPENAI_IMAGE_BASE_URL` | No / 否 | Image model API base URL; falls back to `OPENAI_BASE_URL`. / 图片模型专用 API 地址；留空使用 `OPENAI_BASE_URL`。 | empty / 空 |
| `OPENAI_EVALUATOR_BASE_URL` | No / 否 | Evaluation model API base URL; falls back to `OPENAI_BASE_URL`. / 评分/分析模型专用 API 地址；留空使用 `OPENAI_BASE_URL`。 | empty / 空 |
| `OPENAI_PROMPT_DRAFT_BASE_URL` | No / 否 | Prompt drafting API base URL; falls back to evaluator settings. / 提示词改写模型专用 API 地址；留空使用评分模型地址。 | empty / 空 |
| `OPENAI_API_KEY` | Required for real models / 真实模型必填 | Shared OpenAI-compatible API key used as fallback for dedicated keys. / 通用 OpenAI 兼容 Key，专用 Key 留空时作为兜底。 | empty / 空 |
| `OPENAI_IMAGE_API_KEY` | No / 否 | Dedicated image model API key. / 图片模型专用 Key。 | empty / 空 |
| `OPENAI_IMAGE_MODEL` | Required for real image generation / 真实图片模型必填 | Image generation model name. / 图片生成模型名。 | `gpt-image-2` |
| `OPENAI_EVALUATOR_API_KEY` | No / 否 | Dedicated evaluator model API key. / 文本分析/视觉评估模型专用 Key。 | empty / 空 |
| `OPENAI_EVALUATOR_MODEL` | Required for real evaluation / 真实评估必填 | Text analysis and visual evaluation model name. / 文本分析、视觉氛围评估模型名。 | `gpt-4.1-mini` |
| `OPENAI_PROMPT_DRAFT_MODEL` | Required for real prompt drafting / 真实草稿必填 | Prompt rewriting and copy drafting model name. / AI 提示词改写/文案草稿模型名。 | `gpt-5.5` |
| `MODEL_BASE_URL_ALLOWED_HOSTS` | No / 否 | Allowed host allowlist for model Base URLs saved in admin settings; comma-separated. / 管理后台允许保存的模型 Base URL 主机白名单，多个用英文逗号分隔。 | empty / 空 |
| `ASSET_UPLOAD_DIR` | No / 否 | Storage directory for uploads and generated assets. / 图片、视频和生成资产存储目录。 | `uploads` |
| `ASSET_UPLOAD_MAX_BYTES` | No / 否 | Single upload size limit in bytes. / 单个上传文件大小限制，单位字节。 | `8388608` |
| `DATABASE_PATH` | No / 否 | SQLite database path. / SQLite 数据库路径。 | `data/app.db` |
| `SESSION_MAX_AGE_SECONDS` | No / 否 | Login session lifetime in seconds. / 登录会话有效期。 | `604800` |
| `SECURE_SESSION_COOKIES` | No / 否 | Set to `true` for HTTPS deployment; keep `false` for local HTTP development. / HTTPS 部署时设为 `true`，本地 HTTP 开发保持 `false`。 | `false` |
| `ADMIN_USERNAME` | No / 否 | Bootstrap admin username; must be provided together with email and password. / 初始化管理员用户名；与邮箱、密码三项必须同时填写。 | empty / 空 |
| `ADMIN_EMAIL` | No / 否 | Bootstrap admin email; must be provided together with username and password. / 初始化管理员邮箱；与用户名、密码三项必须同时填写。 | empty / 空 |
| `ADMIN_PASSWORD` | No / 否 | Bootstrap admin password; must be provided together with username and email. / 初始化管理员密码；与用户名、邮箱三项必须同时填写。 | empty / 空 |
| `VIDEO_BASE_URL` | No / 否 | Video model API base URL. / 视频模型 API 地址。 | `https://api.openai.com/v1` |
| `VIDEO_API_KEY` | Required for real video generation / 真实视频模型必填 | Video model API key. / 视频模型 API Key。 | empty / 空 |
| `VIDEO_MODEL` | Required for real video generation / 真实视频模型必填 | Video generation model name. / 视频生成模型名。 | `video-generation` |
| `VIDEO_GENERATE_ENDPOINT` | No / 否 | Video generation endpoint path. / 视频生成接口路径。 | `/videos/generations` |
<!-- AUTO-GENERATED:ENV END -->

## API Overview / API 概览

<!-- AUTO-GENERATED:API START -->
| Module | Main Endpoints |
| --- | --- |
| Image optimization / 图片优化 | `POST /api/generate`, `GET /api/task/{task_id}`, `GET /api/task/{task_id}/history`, `GET /api/models`, `POST /api/assets/upload` |
| References and prompts / 参考与提示词 | `GET /api/reference`, `POST /api/reference/analyze`, `GET /api/reference/patterns`, `POST /api/reference/draft`, `POST /api/reference/draft/stream`, `POST /api/prompt/optimize` |
| Authentication / 认证 | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout` |
| Account credits / 账户额度 | `GET /api/account/credits`, `GET /api/account/transactions` |
| Projects / 项目 | `GET /api/projects`, `POST /api/projects`, `GET /api/projects/{project_id}`, `POST /api/projects/{project_id}/assets/upload`, `GET /api/projects/{project_id}/assets`, `GET /api/projects/{project_id}/tasks` |
| Project generation tasks / 项目生成任务 | `POST /api/projects/{project_id}/generate/image`, `POST /api/projects/{project_id}/generate/image-edit`, `POST /api/projects/{project_id}/generate/video`, `GET /api/tasks/{task_id}`, `GET /api/tasks/{task_id}/history` |
| Canvas / 画布 | `GET/POST /api/projects/{project_id}/canvases`, `GET /api/canvases/{canvas_id}`, plus node/edge mutations, position updates, compilation, branch operations, repair versions, media approval, and final submission. / 另含节点/边增删改、位置更新、编译、分支操作、修复版本、媒体审批和最终提交等接口。 |
| Conversations / 会话 | `POST /api/projects/{project_id}/conversations`, `GET /api/projects/{project_id}/conversations`, `GET /api/conversations/{conversation_id}`, `POST /api/conversations/{conversation_id}/messages`, `POST /api/conversations/{conversation_id}/prompt/optimize` |
| Admin / 管理后台 | `GET/POST /api/admin/model-settings`, `GET /api/admin/users`, `GET /api/admin/tasks`, `GET /api/admin/assets/review-queue`, `POST /api/admin/assets/{asset_id}/review` |
<!-- AUTO-GENERATED:API END -->

High-cost endpoints are protected by `AUTH_REQUIRED` / `API_KEY` and rate-limit settings. API keys can be sent with `Authorization: Bearer <token>` or `X-API-Key: <token>`. Login-based flows also support the HttpOnly `session` cookie.

> 中文：高成本接口受 `AUTH_REQUIRED` / `API_KEY` 和限流配置保护。API Key 可通过 `Authorization: Bearer <token>` 或 `X-API-Key: <token>` 传递；登录态接口也支持 HttpOnly `session` Cookie。

## Build and Deployment / 构建与部署

Build the frontend:

```bash
npm run build
```

When `frontend/dist` exists, FastAPI mounts it at `/`, so one backend process can serve both the API and the static frontend.

The repository includes `docker-compose.yml` with Postgres and n8n services for historical or extended workflows. The current default backend uses SQLite and does not require Postgres or n8n for local development.

> 中文：`npm run build` 会生成 `frontend/dist`，存在时 FastAPI 会将其挂载到 `/`。仓库中的 `docker-compose.yml` 包含 Postgres 和 n8n，主要用于历史或扩展工作流；当前默认使用 SQLite，本地开发不依赖 Postgres 或 n8n。

## Testing / 测试

```bash
.venv/bin/python -m pytest
```

Pytest settings are defined in `pyproject.toml`:

- `asyncio_mode = "auto"`
- `pythonpath = ["."]`
- `testpaths = ["tests"]`

> 中文：测试使用 pytest，配置位于 `pyproject.toml`。本项目当前的推送策略是不将 `tests/` 目录推送到远程仓库，但本地开发仍可保留并运行测试。

## Repository Push Policy / 仓库推送策略

The following paths are local-only and should not be pushed:

- `tests/`
- `docs/`
- `CLAUDE.md`
- `next.md`

They are ignored by `.gitignore` and may still exist locally for development notes, private instructions, or local verification.

> 中文：以上路径仅保留在本地，不推送到远程仓库；它们已写入 `.gitignore`。

## Troubleshooting / 常见问题

### `python: command not found`

macOS may not provide a `python` command by default. Use `python3` or the virtual environment Python instead:

```bash
python3 --version
.venv/bin/python --version
```

> 中文：macOS 默认可能没有 `python` 命令，请使用 `python3` 或 `.venv/bin/python`。

### `API key is not configured for model: openai`

`USE_MOCK_IMAGES=true` is not enabled, and no usable `OPENAI_API_KEY` or `OPENAI_IMAGE_API_KEY` is configured. For local development, enable mock mode first.

> 中文：未启用 `USE_MOCK_IMAGES=true`，也没有配置可用的 `OPENAI_API_KEY` 或 `OPENAI_IMAGE_API_KEY`。本地调试建议先启用 mock。

### `Invalid or missing API key`

`API_KEY` or `AUTH_REQUIRED=true` is configured, but the request does not include credentials. For local frontend debugging, leave `API_KEY` empty; direct API calls should include `Authorization: Bearer ...` or `X-API-Key`.

> 中文：`.env` 中设置了 `API_KEY` 或启用了 `AUTH_REQUIRED=true`，但请求没有携带鉴权信息。本地前端调试可先留空 `API_KEY`；直接调用 API 时传 `Authorization: Bearer ...` 或 `X-API-Key`。

### Upload failed / 上传文件失败

Only PNG, JPEG, WebP images and MP4, WebM, MOV videos are supported. The size limit is controlled by `ASSET_UPLOAD_MAX_BYTES` and defaults to 8 MiB.

> 中文：仅支持 PNG、JPEG、WebP 图片和 MP4、WebM、MOV 视频。大小限制由 `ASSET_UPLOAD_MAX_BYTES` 控制，默认 8 MiB。

### Frontend cannot reach backend / 前端无法访问后端

Make sure both backend and frontend processes are running through `npm run dev`. The Vite frontend uses relative `/api/...` URLs by default, and the local development address is usually `http://127.0.0.1:5173`.

> 中文：确认 `npm run dev` 中后端和前端都已启动。Vite 默认使用相对 `/api/...` 调用后端，本地开发地址通常是 `http://127.0.0.1:5173`。
