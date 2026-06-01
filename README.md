# TUP Image Generation Optimizer

[中文文档](README.zh-CN.md)

TUP is a local-first AI image generation and creative workspace. It uses a FastAPI backend and a React/Vite frontend to analyze prompts, generate images through OpenAI-compatible providers, score visual results, and iterate prompts toward better outputs.

## Features

- **Image optimization loop**: prompt pre-evaluation, optional prompt rewriting, image generation, visual scoring, and automatic iteration.
- **Project and canvas workspace**: projects, canvases, nodes, edges, branch operations, repair versions, image batches, and final submission preview.
- **Multimedia generation**: image generation, image editing, and video generation; local mock modes are available for development without external model calls.
- **Prompt intelligence**: prompt optimization, reference analysis, pattern insights, Prompt Skill, and conversation-based prompt refinement.
- **Accounts and credits**: registration, login, session cookies, credit balances, transaction history, and optional admin bootstrap.
- **Admin console APIs**: model settings, users, tasks, and asset review queues.
- **Local persistence**: SQLite is used by default for accounts, projects, assets, and task state.

## Tech Stack

- Backend: Python 3.11+, FastAPI, Pydantic, httpx, Uvicorn, SQLite
- Frontend: React 19, Vite 6, Ant Design, lucide-react
- Tests: pytest, pytest-asyncio
- Model APIs: OpenAI-compatible image, evaluation, prompt drafting, and video endpoints

## Quick Start

### 1. Install dependencies

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
npm install
```

### 2. Configure environment variables

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

### 3. Start development servers

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

## Commands

<!-- AUTO-GENERATED:COMMANDS START -->
| Command | Description |
| --- | --- |
| `npm run dev` | Start the FastAPI backend and Vite frontend together; child processes are cleaned up on exit. |
| `npm run dev:backend` | Start `src.main:app` with hot reload limited to Python files under `src`, avoiding repeated reloads from `.venv`, `node_modules`, and frontend build artifacts. |
| `npm run dev:frontend` | Start the Vite dev server from the frontend workspace on port `5173`. |
| `npm run build` | Build the frontend workspace into `frontend/dist`. |
| `npm run preview` | Preview the production frontend build on port `4173`. |
| `.venv/bin/python -m pytest` | Run the backend test suite. |
| `.venv/bin/python -m pytest tests/test_api.py` | Run API boundary tests only. |
<!-- AUTO-GENERATED:COMMANDS END -->

There are currently no configured lint, formatter, frontend test, or TypeScript typecheck scripts in `package.json`.

## Environment Variables

<!-- AUTO-GENERATED:ENV START -->
| Variable | Required | Description | Example / Default |
| --- | --- | --- | --- |
| `USE_MOCK_IMAGES` | No | Use local SVG mock image generation when `true`. | `true` |
| `USE_MOCK_VIDEOS` | No | Use mock video generation when `true`. | `true` |
| `PROMPT_PASS_THRESHOLD` | No | Prompt evaluation pass threshold. | `6.0` |
| `VISUAL_PASS_THRESHOLD` | No | Visual evaluation pass threshold. | `8.0` |
| `MAX_ITERATIONS` | No | Maximum image optimization iterations. | `3` |
| `REQUEST_TIMEOUT_SECONDS` | No | External model request timeout in seconds. | `60` |
| `MODEL_REQUEST_RETRIES` | No | Retry count for failed model requests. | `2` |
| `AUTH_REQUIRED` | No | Force authentication for high-cost endpoints; when empty, `API_KEY` enables auth automatically. | empty / `true` |
| `ALLOW_PUBLIC_REGISTRATION` | No | Allow public registration when auth is enabled. | `false` |
| `API_KEY` | Recommended in production | Bearer token or `X-API-Key` for high-cost endpoints. | empty |
| `RATE_LIMIT_REQUESTS` | No | Maximum requests per caller in each rate-limit window. | `30` |
| `RATE_LIMIT_WINDOW_SECONDS` | No | Rate-limit window length in seconds. | `60` |
| `OPENAI_BASE_URL` | No | Default OpenAI-compatible API base URL. | `https://api.openai.com/v1` |
| `OPENAI_IMAGE_BASE_URL` | No | Image model API base URL; falls back to `OPENAI_BASE_URL`. | empty |
| `OPENAI_EVALUATOR_BASE_URL` | No | Evaluation model API base URL; falls back to `OPENAI_BASE_URL`. | empty |
| `OPENAI_PROMPT_DRAFT_BASE_URL` | No | Prompt drafting API base URL; falls back to evaluator settings. | empty |
| `OPENAI_API_KEY` | Required for real models | Shared OpenAI-compatible API key used as fallback for dedicated keys. | empty |
| `OPENAI_IMAGE_API_KEY` | No | Dedicated image model API key. | empty |
| `OPENAI_IMAGE_MODEL` | Required for real image generation | Image generation model name. | `gpt-image-2` |
| `OPENAI_EVALUATOR_API_KEY` | No | Dedicated evaluator model API key. | empty |
| `OPENAI_EVALUATOR_MODEL` | Required for real evaluation | Text analysis and visual evaluation model name. | `gpt-4.1-mini` |
| `OPENAI_PROMPT_DRAFT_MODEL` | Required for real prompt drafting | Prompt rewriting and copy drafting model name. | `gpt-5.5` |
| `MODEL_BASE_URL_ALLOWED_HOSTS` | No | Allowed host allowlist for model Base URLs saved in admin settings; comma-separated. | empty |
| `ASSET_UPLOAD_DIR` | No | Storage directory for uploads and generated assets. | `uploads` |
| `ASSET_UPLOAD_MAX_BYTES` | No | Single upload size limit in bytes. | `8388608` |
| `DATABASE_PATH` | No | SQLite database path. | `data/app.db` |
| `SESSION_MAX_AGE_SECONDS` | No | Login session lifetime in seconds. | `604800` |
| `SECURE_SESSION_COOKIES` | No | Set to `true` for HTTPS deployment; keep `false` for local HTTP development. | `false` |
| `ADMIN_USERNAME` | No | Bootstrap admin username; must be provided together with email and password. | empty |
| `ADMIN_EMAIL` | No | Bootstrap admin email; must be provided together with username and password. | empty |
| `ADMIN_PASSWORD` | No | Bootstrap admin password; must be provided together with username and email. | empty |
| `VIDEO_BASE_URL` | No | Video model API base URL. | `https://api.openai.com/v1` |
| `VIDEO_API_KEY` | Required for real video generation | Video model API key. | empty |
| `VIDEO_MODEL` | Required for real video generation | Video generation model name. | `video-generation` |
| `VIDEO_GENERATE_ENDPOINT` | No | Video generation endpoint path. | `/videos/generations` |
<!-- AUTO-GENERATED:ENV END -->

## API Overview

<!-- AUTO-GENERATED:API START -->
| Module | Main Endpoints |
| --- | --- |
| Image optimization | `POST /api/generate`, `GET /api/task/{task_id}`, `GET /api/task/{task_id}/history`, `GET /api/models`, `POST /api/assets/upload` |
| References and prompts | `GET /api/reference`, `POST /api/reference/analyze`, `GET /api/reference/patterns`, `POST /api/reference/draft`, `POST /api/reference/draft/stream`, `POST /api/prompt/optimize` |
| Authentication | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout` |
| Account credits | `GET /api/account/credits`, `GET /api/account/transactions` |
| Projects | `GET /api/projects`, `POST /api/projects`, `GET /api/projects/{project_id}`, `POST /api/projects/{project_id}/assets/upload`, `GET /api/projects/{project_id}/assets`, `GET /api/projects/{project_id}/tasks` |
| Project generation tasks | `POST /api/projects/{project_id}/generate/image`, `POST /api/projects/{project_id}/generate/image-edit`, `POST /api/projects/{project_id}/generate/video`, `GET /api/tasks/{task_id}`, `GET /api/tasks/{task_id}/history` |
| Canvas | `GET/POST /api/projects/{project_id}/canvases`, `GET /api/canvases/{canvas_id}`, plus node/edge mutations, position updates, compilation, branch operations, repair versions, media approval, and final submission. |
| Conversations | `POST /api/projects/{project_id}/conversations`, `GET /api/projects/{project_id}/conversations`, `GET /api/conversations/{conversation_id}`, `POST /api/conversations/{conversation_id}/messages`, `POST /api/conversations/{conversation_id}/prompt/optimize` |
| Admin | `GET/POST /api/admin/model-settings`, `GET /api/admin/users`, `GET /api/admin/tasks`, `GET /api/admin/assets/review-queue`, `POST /api/admin/assets/{asset_id}/review` |
<!-- AUTO-GENERATED:API END -->

High-cost endpoints are protected by `AUTH_REQUIRED` / `API_KEY` and rate-limit settings. API keys can be sent with `Authorization: Bearer <token>` or `X-API-Key: <token>`. Login-based flows also support the HttpOnly `session` cookie.

## Build and Deployment

Build the frontend:

```bash
npm run build
```

When `frontend/dist` exists, FastAPI mounts it at `/`, so one backend process can serve both the API and the static frontend.

The repository includes `docker-compose.yml` with Postgres and n8n services for historical or extended workflows. The current default backend uses SQLite and does not require Postgres or n8n for local development.

## Testing

```bash
.venv/bin/python -m pytest
```

Pytest settings are defined in `pyproject.toml`:

- `asyncio_mode = "auto"`
- `pythonpath = ["."]`
- `testpaths = ["tests"]`

The current repository push policy excludes `tests/` from the remote repository, but local development can still keep and run local tests.

## Repository Push Policy

The following paths are local-only and should not be pushed:

- `tests/`
- `docs/`
- `CLAUDE.md`
- `next.md`

They are ignored by `.gitignore` and may still exist locally for development notes, private instructions, or local verification.

## Troubleshooting

### `python: command not found`

macOS may not provide a `python` command by default. Use `python3` or the virtual environment Python instead:

```bash
python3 --version
.venv/bin/python --version
```

### `API key is not configured for model: openai`

`USE_MOCK_IMAGES=true` is not enabled, and no usable `OPENAI_API_KEY` or `OPENAI_IMAGE_API_KEY` is configured. For local development, enable mock mode first.

### `Invalid or missing API key`

`API_KEY` or `AUTH_REQUIRED=true` is configured, but the request does not include credentials. For local frontend debugging, leave `API_KEY` empty; direct API calls should include `Authorization: Bearer ...` or `X-API-Key`.

### Upload failed

Only PNG, JPEG, WebP images and MP4, WebM, MOV videos are supported. The size limit is controlled by `ASSET_UPLOAD_MAX_BYTES` and defaults to 8 MiB.

### Frontend cannot reach backend

Make sure both backend and frontend processes are running through `npm run dev`. The Vite frontend uses relative `/api/...` URLs by default, and the local development address is usually `http://127.0.0.1:5173`.
