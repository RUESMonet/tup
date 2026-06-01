# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

This is a local image generation optimizer with a FastAPI backend and a React/Vite frontend. The app accepts an image prompt, optionally analyzes and refines it, generates images through an OpenAI-compatible image endpoint, visually scores results, and iterates prompts until the configured score threshold or iteration limit is reached.

The current README describes the active app as image-only: prompt analysis, image generation, visual scoring, and automatic iteration. Starting the backend no longer requires Postgres or n8n, even though `docker-compose.yml` still contains Postgres and n8n service definitions.

## Common commands

### Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
npm install
```

Copy `.env.example` to `.env` for local configuration. For local development without external image model calls, set:

```env
USE_MOCK_IMAGES=true
```

### Run locally

```bash
npm run dev
```

This starts both the backend and frontend. The frontend defaults to `http://localhost:5173` / `http://127.0.0.1:5173`.

Run services separately when needed:

```bash
npm run dev:backend
npm run dev:frontend
```

The backend command is defined to reload only `src` Python files so `.venv`, `node_modules`, and frontend build artifacts do not trigger repeated restarts.

### Build and preview frontend

```bash
npm run build
npm run preview
```

`npm run build` builds only the frontend workspace into `frontend/dist`. When that directory exists, the FastAPI app mounts it at `/`.

### Tests

```bash
.venv/bin/python -m pytest
.venv/bin/python -m pytest tests/test_api.py
.venv/bin/python -m pytest tests/test_api.py::test_models_endpoint_lists_supported_models
```

Pytest is configured in `pyproject.toml` with `asyncio_mode = "auto"`, `pythonpath = ["."]`, and `testpaths = ["tests"]`.

### Lint/typecheck status

There are no configured lint, formatter, frontend test, or TypeScript typecheck scripts in `package.json` or `frontend/package.json` at the time this file was created.

## Backend architecture

- `src/main.py` creates the FastAPI app, configures CORS for the Vite dev server, includes the `/api` router, mounts `/uploads`, and serves `frontend/dist` when present.
- `src/config.py` owns environment loading and `Settings`. It reads `.env` directly, supports shared or dedicated OpenAI-compatible keys/base URLs, model names, thresholds, iteration limits, timeouts, retries, mock image mode, auth, rate limits, and upload limits.
- `src/api/image_routes.py` contains the public API:
  - `POST /api/generate` creates an in-memory task and runs the image pipeline in the background.
  - `GET /api/task/{task_id}` and `/history` expose task result and iteration history.
  - `GET /api/models` reports supported model configuration.
  - `POST /api/assets/upload` stores PNG/JPEG/WebP uploads under `uploads/image-optimizer`.
  - `/api/reference*` endpoints provide prompt quality references, candidate prompts, and LLM prompt drafting, including NDJSON streaming.
- High-cost endpoints use `API_KEY`/`AUTH_REQUIRED` and a per-principal or per-IP in-process rate limiter. API keys are accepted via `Authorization: Bearer ...` or `X-API-Key`.
- `src/dependencies.py` wires FastAPI dependencies. `InMemoryTaskStorage` is cached as a singleton; the pipeline and prompt draft agent are built from current settings.
- `src/services/pipeline.py` orchestrates prompt pre-evaluation, optional prompt refinement, image generation, visual scoring, and iterative refinement.
- `src/services/model_router.py` is the image provider boundary. It currently exposes the `openai` model id, supports `USE_MOCK_IMAGES=true`, maps requests to `/images/generations`, retries transient provider failures, and returns `ImageResult` objects.
- `src/services/storage.py` is async, lock-protected, in-memory task storage; tasks are not persisted across process restarts.
- `src/agents/` contains the prompt and visual intelligence layer: prompt pre-evaluation, prompt refinement, visual evaluation, prompt drafting via OpenAI Responses API, quality references, and prompt case retrieval.
- `src/models/` contains Pydantic/domain models for task results and evaluation reports.

## Frontend architecture

The frontend is a single React page under `frontend/src`:

- `main.jsx` mounts the app.
- `ImageOnlyPage.jsx` handles model loading, prompt analysis, image generation submission, task polling, result display, candidate prompt application, and final prompt copy behavior.
- `image.css` contains page styling.

The frontend calls backend APIs with relative `/api/...` URLs and uses polling every 1200ms for generation tasks. Client requests time out after 15 seconds and surface backend connectivity guidance in Chinese UI copy.

## Configuration notes

Important environment variables are documented in `.env.example`:

- `USE_MOCK_IMAGES=true` enables local SVG mock image results without external API keys.
- `OPENAI_API_KEY` is the shared fallback key.
- `OPENAI_IMAGE_API_KEY`, `OPENAI_EVALUATOR_API_KEY`, and their corresponding base URL variables override the shared OpenAI-compatible settings for generation/evaluation.
- `OPENAI_IMAGE_MODEL`, `OPENAI_EVALUATOR_MODEL`, and `OPENAI_PROMPT_DRAFT_MODEL` select provider models.
- `PROMPT_PASS_THRESHOLD`, `VISUAL_PASS_THRESHOLD`, and `MAX_ITERATIONS` control pipeline behavior.
- `API_KEY` automatically enables auth for high-cost endpoints unless `AUTH_REQUIRED` is set explicitly.
- `ASSET_UPLOAD_DIR` and `ASSET_UPLOAD_MAX_BYTES` control upload storage.

## Testing focus

Existing tests cover API behavior, auth/rate limiting, upload handling, prompt quality/reference logic, prompt drafting request shape and streaming, model router configuration/errors, visual evaluator behavior, and pipeline iteration semantics. Prefer adding tests near the boundary being changed:

- API changes: `tests/test_api.py`
- Pipeline orchestration: `tests/test_pipeline.py`
- Model/provider routing: `tests/test_model_router.py`
- Prompt/reference/visual evaluator behavior: `tests/test_prompt_evaluator.py`
