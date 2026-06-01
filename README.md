# 图片生成优化器本地启动

当前入口已回到只做图片：提示词分析、图片生成、视觉评分和自动迭代。启动后端不再要求 Postgres 或 n8n。

## 1. 准备 Python 依赖

macOS 默认可能没有 `python` 命令，请使用 `python3` 或虚拟环境里的 Python：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## 2. 配置环境变量

开发时可以先使用 mock 图片：

```env
USE_MOCK_IMAGES=true
```

接入真实图片模型时填写：

```env
OPENAI_API_KEY=...
OPENAI_IMAGE_MODEL=gpt-image-2
```

如果设置了 `API_KEY`，高成本接口会自动启用鉴权；本地调试可留空。

## 3. 启动本地服务

默认同时启动后端和前端：

```bash
npm run dev
```

打开 Vite 输出的本地地址，默认是 `http://localhost:5173`。

也可以拆开启动。

后端：

只监听 `src`，避免 `.venv` 或前端产物变化触发反复重启：

```bash
.venv/bin/uvicorn src.main:app --reload --reload-dir src --reload-include "*.py" --reload-exclude ".venv/*" --reload-exclude "node_modules/*" --reload-exclude "frontend/dist/*"
```

也可以使用 npm 脚本：

```bash
npm run dev:backend
```

前端：

```bash
npm run dev:frontend
```

## 常见错误

`python: command not found`：使用 `python3` 或 `.venv/bin/python`。

`API key is not configured for model: openai`：没有开启 `USE_MOCK_IMAGES=true`，也没有配置可用的 `OPENAI_API_KEY` 或 `OPENAI_IMAGE_API_KEY`。

`Invalid or missing API key`：`.env` 里设置了 `API_KEY`，前端页面没有传鉴权头。本地调试时先留空 `API_KEY`。
