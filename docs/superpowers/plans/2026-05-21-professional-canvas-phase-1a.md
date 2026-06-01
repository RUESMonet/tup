# Professional Canvas Phase 1A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing canvas into the first professional storyboard prompt workflow by adding storyboard node metadata, node-linked image prompt optimization, prompt version history, and minimal frontend controls that reuse the current prompt scoring system.

**Architecture:** Keep the current FastAPI + React/Vite app. Store prompt versions in the existing `prompt_artifacts` table instead of introducing a new database table. Add canvas-scoped APIs that compile selected canvas nodes, run the existing `PromptSkillPipeline` prompt optimizer/evaluator without generating an image, save the result as a node-linked artifact, and expose artifact history to the canvas UI.

**Tech Stack:** FastAPI, Pydantic, SQLite, pytest, React, Vite, existing canvas/project/auth/prompt skill services.

---

## Scope Split

The approved product spec covers multiple independent subsystems. This plan implements the first independently testable slice only:

- Storyboard-friendly canvas payload fields.
- Canvas API to optimize an image prompt for a selected storyboard/brief graph.
- Node-linked prompt version history using `prompt_artifacts`.
- Optional `prompt_artifact_id` linkage on image batch generation requests.
- Minimal canvas UI controls for creating storyboard nodes, optimizing image prompts, and viewing saved prompt versions.

Do not implement credits, public community, video prompt optimization, image-to-video generation changes, payment, or expanded admin screens in this plan. Those need separate plans after this slice is passing.

## File Structure

### Backend

- Modify: `src/models/canvas.py`
  - Add storyboard prompt request/response models.
  - Add `PromptArtifactListResponse`.
  - Add safe payload fields used by storyboard nodes and prompt-version links.
  - Add optional `prompt_artifact_id` to `CanvasGenerateImageRequest`.

- Modify: `src/services/canvas_repository.py`
  - Add `list_prompt_artifacts()`.
  - Keep `create_prompt_artifact()` as the single writer for prompt versions.

- Modify: `src/api/canvas_routes.py`
  - Import the new canvas models and `PromptReport`.
  - Add `GET /api/canvases/{canvas_id}/prompt-artifacts`.
  - Add `POST /api/canvases/{canvas_id}/storyboard/image-prompt`.
  - Pass `prompt_artifact_id` through image batch creation and task input.

- Modify: `tests/test_canvas_routes.py`
  - Add tests for image prompt optimization persistence, artifact listing, ownership isolation, and image batch artifact linkage.

### Frontend

- Modify: `frontend/src/api/canvas.js`
  - Add `fetchCanvasPromptArtifacts()`.
  - Add `optimizeCanvasImagePrompt()`.

- Modify: `frontend/src/workspace/CanvasWorkspaceController.jsx`
  - Load prompt artifacts with canvas details.
  - Add storyboard node creation from the brief editor.
  - Add image prompt optimization action for the selected graph.
  - Save the latest artifact id back into the selected node payload.

- Modify: `frontend/src/workspace/CanvasWorkspaceComponents.jsx`
  - Add `storyboard` node label.
  - Import and render the prompt-version panel.
  - Add a selected-node action for image prompt optimization.

- Create: `frontend/src/workspace/StoryboardPromptPanel.jsx`
  - Focused panel for optimizing and viewing prompt versions for the selected node.

---

### Task 1: Backend Tests for Storyboard Prompt Versions

**Files:**
- Modify: `tests/test_canvas_routes.py`

- [ ] **Step 1: Add the failing tests**

Append these tests near the existing canvas API tests in `tests/test_canvas_routes.py`:

```python
def test_canvas_storyboard_image_prompt_optimization_persists_version(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    storyboard = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={
            "type": "storyboard",
            "title": "Shot 01",
            "position": {"x": 0, "y": 0},
            "payload": {
                "role": "storyboard",
                "prompt": "高端香水广告首镜，黑金背景，产品居中",
                "scene": "黑金摄影棚",
                "camera": "slow dolly in",
                "subject_action": "香水瓶保持稳定，瓶身高光缓慢移动",
                "shot_size": "medium close-up",
                "duration": "5",
                "aspect_ratio": "16:9",
            },
        },
    )
    assert storyboard.status_code == 201

    response = client.post(
        f"/api/canvases/{canvas_id}/storyboard/image-prompt",
        json={
            "node_id": storyboard.json()["id"],
            "selected_node_ids": [storyboard.json()["id"]],
            "root_node_id": storyboard.json()["id"],
            "params": {"size": "1024x1024", "quality": "high"},
            "skip_prompt_evaluation": True,
        },
    )
    listed = client.get(f"/api/canvases/{canvas_id}/prompt-artifacts", params={"node_id": storyboard.json()["id"], "kind": "storyboard_image_prompt_version"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["final_prompt"]
    assert payload["prompt_report"]["score"] == 10.0
    assert payload["artifact"]["kind"] == "storyboard_image_prompt_version"
    assert payload["artifact"]["node_id"] == storyboard.json()["id"]
    assert payload["artifact"]["payload"]["workflow"] == "storyboard_image_prompt_optimization"
    assert payload["artifact"]["payload"]["selected_node_ids"] == [storyboard.json()["id"]]
    assert payload["artifact"]["payload"]["prompt_skill"]["final_english_prompt"] == payload["final_prompt"]
    assert listed.status_code == 200
    assert [artifact["id"] for artifact in listed.json()["artifacts"]] == [payload["artifact"]["id"]]


def test_canvas_storyboard_image_prompt_rejects_foreign_node(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    ada_project_id = _project(ada_client, "Ada")
    grace_project_id = _project(grace_client, "Grace")
    ada_canvas_id = _canvas(ada_client, ada_project_id)
    grace_canvas_id = _canvas(grace_client, grace_project_id)
    grace_node = grace_client.post(
        f"/api/canvases/{grace_canvas_id}/nodes",
        json={"type": "storyboard", "title": "Private", "position": {"x": 0, "y": 0}, "payload": {"prompt": "私有分镜"}},
    ).json()

    response = ada_client.post(
        f"/api/canvases/{ada_canvas_id}/storyboard/image-prompt",
        json={"node_id": grace_node["id"], "selected_node_ids": [grace_node["id"]], "skip_prompt_evaluation": True},
    )

    assert response.status_code == 404


def test_canvas_image_batch_records_prompt_artifact_link(tmp_path):
    client = _client(tmp_path)
    _register(client, "ada")
    project_id = _project(client)
    canvas_id = _canvas(client, project_id)
    node = client.post(
        f"/api/canvases/{canvas_id}/nodes",
        json={"type": "storyboard", "title": "Shot", "position": {"x": 0, "y": 0}, "payload": {"prompt": "高端香水广告图"}},
    ).json()
    optimized = client.post(
        f"/api/canvases/{canvas_id}/storyboard/image-prompt",
        json={"node_id": node["id"], "selected_node_ids": [node["id"]], "skip_prompt_evaluation": True},
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/image-batches",
        json={
            "selected_node_ids": [node["id"]],
            "model": "openai",
            "threshold": 0.0,
            "max_iter": 1,
            "params": {"n": 1},
            "skip_prompt_evaluation": True,
            "prompt_artifact_id": optimized["artifact"]["id"],
        },
    )

    assert response.status_code == 202
    assert response.json()["prompt_artifact_id"] == optimized["artifact"]["id"]
```

- [ ] **Step 2: Run the first test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py::test_canvas_storyboard_image_prompt_optimization_persists_version -q
```

Expected: FAIL with 422 on the storyboard node payload fields or 404 for the missing `/storyboard/image-prompt` endpoint.

- [ ] **Step 3: Run all new tests to capture the red state**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py::test_canvas_storyboard_image_prompt_optimization_persists_version tests/test_canvas_routes.py::test_canvas_storyboard_image_prompt_rejects_foreign_node tests/test_canvas_routes.py::test_canvas_image_batch_records_prompt_artifact_link -q
```

Expected: FAIL until the backend models, route, and repository method are implemented.

---

### Task 2: Canvas Models for Storyboard Prompt APIs

**Files:**
- Modify: `src/models/canvas.py`
- Test: `tests/test_canvas_routes.py`

- [ ] **Step 1: Add storyboard payload keys**

In `src/models/canvas.py`, extend `CANVAS_PROMPT_TEXT_FIELDS` with these string fields:

```python
    "camera_motion",
    "ending_state",
    "prompt_artifact_id",
    "shot_size",
    "subject_action",
    "temporal_rhythm",
```

Place them alphabetically near related existing keys. `duration` and `aspect_ratio` already exist.

- [ ] **Step 2: Add the request and response models**

In `src/models/canvas.py`, after `CanvasGenerateImageRequest`, add:

```python
class CanvasStoryboardImagePromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    selected_node_ids: list[str] = Field(min_length=1, max_length=80)
    root_node_id: str | None = Field(default=None, min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    skip_prompt_evaluation: bool = False

    @field_validator("node_id", "root_node_id")
    @classmethod
    def strip_optional_storyboard_ids(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank")
        return stripped

    @field_validator("selected_node_ids")
    @classmethod
    def validate_unique_storyboard_node_ids(cls, value: list[str]) -> list[str]:
        return _validate_unique_node_ids(value)

    @field_validator("params")
    @classmethod
    def validate_storyboard_prompt_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_canvas_payload(value)
        _validate_canvas_generate_image_params(value)
        return value
```

In `src/models/canvas.py`, after `PromptArtifactResponse`, add:

```python
class PromptArtifactListResponse(BaseModel):
    artifacts: list[PromptArtifactResponse]


class CanvasStoryboardImagePromptResponse(BaseModel):
    final_prompt: str
    prompt_report: dict[str, Any]
    prompt_skill: dict[str, Any]
    optimization_trace: dict[str, Any]
    artifact: PromptArtifactResponse
```

- [ ] **Step 3: Add prompt artifact linkage to image generation requests**

In `CanvasGenerateImageRequest`, add this field after `root_node_id`:

```python
    prompt_artifact_id: str | None = Field(default=None, min_length=1)
```

Update the existing optional id validator to include it:

```python
    @field_validator("root_node_id", "prompt_artifact_id")
    @classmethod
    def strip_optional_root_node_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank")
        return stripped
```

- [ ] **Step 4: Run the model-validation test again**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py::test_canvas_storyboard_image_prompt_optimization_persists_version -q
```

Expected: FAIL with 404 for the missing `/storyboard/image-prompt` endpoint, not 422 for unsupported payload fields.

---

### Task 3: Repository Read API for Prompt Artifacts

**Files:**
- Modify: `src/services/canvas_repository.py`
- Test: `tests/test_canvas_routes.py`

- [ ] **Step 1: Add the repository method**

In `CanvasRepository`, immediately after `get_prompt_artifact()`, add:

```python
    def list_prompt_artifacts(
        self,
        owner_id: str,
        canvas_id: str,
        node_id: str | None = None,
        kind: str | None = None,
        limit: int = 50,
    ) -> list[PromptArtifactResponse] | None:
        if limit < 1 or limit > 100:
            raise ValueError("Prompt artifact limit must be between 1 and 100")
        with self.database.connect() as connection:
            canvas = connection.execute("SELECT 1 FROM canvases WHERE owner_id = ? AND id = ?", (owner_id, canvas_id)).fetchone()
            if canvas is None:
                return None
            filters = ["owner_id = ?", "canvas_id = ?"]
            values: list[Any] = [owner_id, canvas_id]
            if node_id is not None:
                filters.append("node_id = ?")
                values.append(node_id)
            if kind is not None:
                filters.append("kind = ?")
                values.append(kind)
            values.append(limit)
            rows = connection.execute(
                f"""
                SELECT id, canvas_id, node_id, kind, payload_json, created_at
                FROM prompt_artifacts
                WHERE {' AND '.join(filters)}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                tuple(values),
            ).fetchall()
        return [_artifact_response(row) for row in rows]
```

- [ ] **Step 2: Run repository-covered tests and verify route is still missing**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py::test_canvas_storyboard_image_prompt_optimization_persists_version -q
```

Expected: FAIL with 404 for the missing route.

---

### Task 4: Canvas Prompt Artifact Routes

**Files:**
- Modify: `src/api/canvas_routes.py`
- Test: `tests/test_canvas_routes.py`

- [ ] **Step 1: Import the new models and prompt report**

In `src/api/canvas_routes.py`, add these imports to the existing model import block:

```python
    CanvasStoryboardImagePromptRequest,
    CanvasStoryboardImagePromptResponse,
    PromptArtifactListResponse,
```

Add this import near the existing prompt imports:

```python
from src.models.prompt_report import PromptReport
```

- [ ] **Step 2: Add the artifact listing route**

After `get_canvas()`, add:

```python
@router.get("/api/canvases/{canvas_id}/prompt-artifacts", response_model=PromptArtifactListResponse)
def list_canvas_prompt_artifacts(
    canvas_id: str,
    node_id: str | None = Query(default=None, min_length=1),
    kind: str | None = Query(default=None, min_length=1, max_length=80),
    limit: int = Query(default=50, ge=1, le=100),
    user: AuthUser = Depends(require_current_user),
    repository: CanvasRepository = Depends(get_canvas_repository),
) -> PromptArtifactListResponse:
    artifacts = repository.list_prompt_artifacts(
        user.id,
        canvas_id,
        node_id.strip() if node_id else None,
        kind.strip() if kind else None,
        limit,
    )
    if artifacts is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    return PromptArtifactListResponse(artifacts=artifacts)
```

- [ ] **Step 3: Add the storyboard prompt optimization route**

After `compile_canvas()`, add:

```python
@router.post(
    "/api/canvases/{canvas_id}/storyboard/image-prompt",
    response_model=CanvasStoryboardImagePromptResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_high_cost_access)],
)
async def optimize_storyboard_image_prompt(
    canvas_id: str,
    request: CanvasStoryboardImagePromptRequest,
    user: AuthUser = Depends(require_current_user),
    canvas_repository: CanvasRepository = Depends(get_canvas_repository),
    project_repository: ProjectRepository = Depends(get_project_repository),
    pipeline: PromptSkillPipeline = Depends(get_prompt_skill_pipeline),
    settings: Settings = Depends(get_settings),
) -> CanvasStoryboardImagePromptResponse:
    canvas = await asyncio.to_thread(canvas_repository.get_canvas, user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    canvas_node_ids = {node.id for node in canvas.nodes}
    if request.node_id not in canvas_node_ids or not set(request.selected_node_ids).issubset(canvas_node_ids):
        raise HTTPException(status_code=404, detail="Selected node not found")
    if request.node_id not in set(request.selected_node_ids):
        raise HTTPException(status_code=422, detail="node_id must be included in selected_node_ids")
    if request.root_node_id is not None and request.root_node_id not in set(request.selected_node_ids):
        raise HTTPException(status_code=404, detail="Root node not found")
    _reject_archived_repair_version_selection(canvas, request.selected_node_ids)

    compiled = await asyncio.to_thread(_compile_canvas_or_422, canvas, request.selected_node_ids, None, request.root_node_id)
    prompt_request = await asyncio.to_thread(_canvas_prompt_skill_request, user.id, canvas.project_id, compiled, request.params, project_repository, settings)
    prompt_skill = await pipeline.prompt_skill_agent.optimize(prompt_request)
    prompt_report = (
        PromptReport(score=10.0, passed=True, missing=[], suggestion="")
        if request.skip_prompt_evaluation
        else await pipeline.prompt_evaluator.evaluate(prompt_request.prompt)
    )
    optimization_trace = PromptSkillPipeline._trace(prompt_request.prompt, prompt_skill, prompt_report)
    prompt_skill_payload = prompt_skill.model_dump(mode="json")
    prompt_report_payload = prompt_report.model_dump(mode="json")
    trace_payload = optimization_trace.model_dump(mode="json")
    artifact_payload = {
        "workflow": "storyboard_image_prompt_optimization",
        "node_id": request.node_id,
        "selected_node_ids": request.selected_node_ids,
        "root_node_id": request.root_node_id,
        "params": request.params,
        "creative_graph": compiled.creative_graph.model_dump(mode="json"),
        "prompt_spec": compiled.prompt_spec,
        "compiled_prompt": compiled.final_prompt,
        "final_prompt": prompt_skill.final_english_prompt,
        "prompt_report": prompt_report_payload,
        "prompt_skill": prompt_skill_payload,
        "optimization_trace": trace_payload,
    }
    try:
        artifact = await asyncio.to_thread(
            canvas_repository.create_prompt_artifact,
            user.id,
            canvas_id,
            request.node_id,
            "storyboard_image_prompt_version",
            artifact_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if artifact is None:
        raise HTTPException(status_code=404, detail="Canvas or node not found")
    return CanvasStoryboardImagePromptResponse(
        final_prompt=prompt_skill.final_english_prompt,
        prompt_report=prompt_report_payload,
        prompt_skill=prompt_skill_payload,
        optimization_trace=trace_payload,
        artifact=artifact,
    )
```

- [ ] **Step 4: Run the prompt-version tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py::test_canvas_storyboard_image_prompt_optimization_persists_version tests/test_canvas_routes.py::test_canvas_storyboard_image_prompt_rejects_foreign_node -q
```

Expected: PASS.

---

### Task 5: Link Prompt Versions to Image Batches

**Files:**
- Modify: `src/api/canvas_routes.py`
- Test: `tests/test_canvas_routes.py`

- [ ] **Step 1: Validate `prompt_artifact_id` before task creation**

In `generate_canvas_image()`, after `_reject_archived_repair_version_selection(...)`, add:

```python
    if request.prompt_artifact_id is not None:
        artifact = await asyncio.to_thread(canvas_repository.get_prompt_artifact, user.id, canvas_id, request.prompt_artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Prompt artifact not found")
```

In `create_canvas_image_batch()`, after `_validate_repair_batch_source(...)`, add the same validation block:

```python
    if request.prompt_artifact_id is not None:
        artifact = await asyncio.to_thread(canvas_repository.get_prompt_artifact, user.id, canvas_id, request.prompt_artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="Prompt artifact not found")
```

- [ ] **Step 2: Include `prompt_artifact_id` in image generation task input**

In `generate_canvas_image()`, add `prompt_artifact_id` to `task_input`:

```python
        "prompt_artifact_id": request.prompt_artifact_id,
```

The resulting `task_input` block should include it beside `root_node_id` and `model`.

- [ ] **Step 3: Pass `prompt_artifact_id` when creating image batches**

In `create_canvas_image_batch()`, replace this line:

```python
    batch = await asyncio.to_thread(canvas_repository.create_image_batch, user.id, canvas_id, request.selected_node_ids, None, task.task_id, compiled.final_prompt, request.params)
```

with:

```python
    batch = await asyncio.to_thread(canvas_repository.create_image_batch, user.id, canvas_id, request.selected_node_ids, request.prompt_artifact_id, task.task_id, compiled.final_prompt, request.params)
```

Also add `prompt_artifact_id` to the `task_input` dictionary in that route:

```python
        "prompt_artifact_id": request.prompt_artifact_id,
```

- [ ] **Step 4: Run the batch-linkage test**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py::test_canvas_image_batch_records_prompt_artifact_link -q
```

Expected: PASS.

- [ ] **Step 5: Run canvas backend regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py tests/test_canvas_generation_lineage.py -q
```

Expected: PASS.

- [ ] **Step 6: Conditional commit**

Run:

```bash
git -C /Users/apple/Documents/tup rev-parse --is-inside-work-tree && git -C /Users/apple/Documents/tup add src/models/canvas.py src/services/canvas_repository.py src/api/canvas_routes.py tests/test_canvas_routes.py && git -C /Users/apple/Documents/tup commit -m "feat: add canvas storyboard prompt versions"
```

Expected: In this current workspace, `git rev-parse` may fail because `/Users/apple/Documents/tup` is not a git repo. If it fails, record that no commit was made and continue to the frontend tasks.

---

### Task 6: Frontend API Client for Prompt Versions

**Files:**
- Modify: `frontend/src/api/canvas.js`

- [ ] **Step 1: Add canvas prompt artifact API functions**

Append these functions to `frontend/src/api/canvas.js`:

```js
export function fetchCanvasPromptArtifacts(canvasId, filters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return getJson(`/api/canvases/${canvasId}/prompt-artifacts${query ? `?${query}` : ""}`);
}

export function optimizeCanvasImagePrompt(canvasId, payload) {
  return postJson(`/api/canvases/${canvasId}/storyboard/image-prompt`, payload);
}
```

- [ ] **Step 2: Run frontend build after the API-only change**

Run:

```bash
npm run build
```

Expected: PASS.

---

### Task 7: Storyboard Prompt Panel Component

**Files:**
- Create: `frontend/src/workspace/StoryboardPromptPanel.jsx`

- [ ] **Step 1: Create the focused panel component**

Create `frontend/src/workspace/StoryboardPromptPanel.jsx` with:

```jsx
import { Loader2, Sparkles } from "lucide-react";

function artifactTitle(artifact) {
  const created = artifact?.created_at ? new Date(artifact.created_at).toLocaleString() : "未知时间";
  const score = artifact?.payload?.prompt_report?.score;
  return `${created}${typeof score === "number" ? ` · Prompt ${score.toFixed(1)}` : ""}`;
}

function artifactFinalPrompt(artifact) {
  return artifact?.payload?.final_prompt || artifact?.payload?.compiled_prompt || "";
}

export function StoryboardPromptPanel({ selectedNode, artifacts, optimizingNodeId, onOptimize }) {
  if (!selectedNode) {
    return null;
  }
  const nodeArtifacts = artifacts.filter((artifact) => artifact.node_id === selectedNode.id && artifact.kind === "storyboard_image_prompt_version");
  const latest = nodeArtifacts[0] || null;
  const busy = optimizingNodeId === selectedNode.id;
  const canOptimize = ["brief", "storyboard", "series_frame", "shot", "prompt_program", "semantic_spec"].includes(selectedNode.type);
  if (!canOptimize) {
    return null;
  }
  return (
    <section className="canvas-inspector-section">
      <div className="canvas-production-heading">
        <span>Storyboard Prompt</span>
        <button className="primary-image-action compact" type="button" onClick={() => onOptimize(selectedNode)} disabled={busy}>
          {busy ? <Loader2 className="spinning" size={16} /> : <Sparkles size={16} />}
          <span>{latest ? "重新优化图像 Prompt" : "优化图像 Prompt"}</span>
        </button>
      </div>
      {latest ? (
        <div className="canvas-node-payload-list">
          <small>{artifactTitle(latest)}</small>
          <p>{artifactFinalPrompt(latest)}</p>
        </div>
      ) : (
        <small>还没有保存的图像 Prompt 版本。优化后会把评分、Prompt Skill 输出和 trace 保存到当前节点。</small>
      )}
      {nodeArtifacts.length > 1 ? <small>历史版本：{nodeArtifacts.length} 个，可在后续阶段加入对比和回滚。</small> : null}
    </section>
  );
}
```

- [ ] **Step 2: Run frontend build and capture unresolved class/import issues**

Run:

```bash
npm run build
```

Expected: PASS because the new component is not imported yet.

---

### Task 8: Frontend Controller State and Actions

**Files:**
- Modify: `frontend/src/workspace/CanvasWorkspaceController.jsx`
- Modify: `frontend/src/api/canvas.js`

- [ ] **Step 1: Import the new API functions**

In `frontend/src/workspace/CanvasWorkspaceController.jsx`, update the import from `../api/canvas` so it includes:

```js
fetchCanvasPromptArtifacts,
optimizeCanvasImagePrompt,
```

- [ ] **Step 2: Add prompt artifact state**

After the `imageBatches` state line, add:

```js
  const [promptArtifacts, setPromptArtifacts] = useState([]);
  const [optimizingPromptNodeId, setOptimizingPromptNodeId] = useState("");
```

- [ ] **Step 3: Load prompt artifacts with canvas details**

In `loadCanvas()`, replace:

```js
      const [detail, batchList] = await Promise.all([fetchCanvas(firstCanvas.id), fetchCanvasImageBatches(firstCanvas.id)]);
```

with:

```js
      const [detail, batchList, artifactList] = await Promise.all([
        fetchCanvas(firstCanvas.id),
        fetchCanvasImageBatches(firstCanvas.id),
        fetchCanvasPromptArtifacts(firstCanvas.id, { kind: "storyboard_image_prompt_version", limit: 80 }),
      ]);
```

Then add this state update beside `setImageBatches(batchList.batches || []);`:

```js
        setPromptArtifacts(artifactList.artifacts || []);
```

- [ ] **Step 4: Refresh prompt artifacts with canvas artifacts**

In `refreshCanvasArtifacts()`, replace:

```js
    const [detail, batchList] = await Promise.all([fetchCanvas(canvas.id), fetchCanvasImageBatches(canvas.id)]);
    setCanvas(detail);
    setImageBatches(batchList.batches || []);
```

with:

```js
    const [detail, batchList, artifactList] = await Promise.all([
      fetchCanvas(canvas.id),
      fetchCanvasImageBatches(canvas.id),
      fetchCanvasPromptArtifacts(canvas.id, { kind: "storyboard_image_prompt_version", limit: 80 }),
    ]);
    setCanvas(detail);
    setImageBatches(batchList.batches || []);
    setPromptArtifacts(artifactList.artifacts || []);
```

- [ ] **Step 5: Add storyboard node creation from the brief editor**

After `addBriefNode()`, add:

```js
  async function addStoryboardNode() {
    const text = brief.trim();
    if (!text || !canvas || creating) {
      return;
    }
    setCreating(true);
    try {
      const node = await createCanvasNode(canvas.id, {
        type: "storyboard",
        title: text.slice(0, 36),
        position: canvasPoint(220, 220, view),
        size: SEMANTIC_NODE_SIZE,
        payload: {
          role: "storyboard",
          prompt: text,
          scene: text,
          camera: "slow controlled camera move",
          camera_motion: "slow dolly in",
          subject_action: "subject remains stable with subtle premium motion",
          shot_size: "medium close-up",
          temporal_rhythm: "calm commercial pacing",
          ending_state: "clean hero frame",
          duration: "5",
          aspect_ratio: "16:9",
        },
      });
      setCanvas((current) => (current ? { ...current, nodes: [...current.nodes, node] } : current));
      setBrief("");
      setSelectedNodeId(node.id);
      onStatus?.({ kind: "ready", message: "分镜节点已加入画布" });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "分镜节点创建失败" });
    } finally {
      setCreating(false);
    }
  }
```

- [ ] **Step 6: Add the image prompt optimization action**

After `createPromptProgramFromSelection()`, add:

```js
  async function optimizeStoryboardImagePrompt(node = selectedNode) {
    if (!canvas || !node || optimizingPromptNodeId) {
      return;
    }
    const sourceIds = selectedSourceIds.includes(node.id) ? selectedSourceIds : [node.id];
    setOptimizingPromptNodeId(node.id);
    try {
      const response = await optimizeCanvasImagePrompt(canvas.id, {
        node_id: node.id,
        selected_node_ids: sourceIds,
        root_node_id: node.id,
        params: { size: "1024x1024", quality: "high" },
        skip_prompt_evaluation: false,
      });
      setPromptArtifacts((current) => [response.artifact, ...current.filter((artifact) => artifact.id !== response.artifact.id)]);
      const nextPayload = { ...node.payload, prompt_artifact_id: response.artifact.id, final_prompt: response.final_prompt };
      const updated = await updateCanvasNode(canvas.id, node.id, { payload: nextPayload });
      setCanvas((current) => current ? { ...current, nodes: current.nodes.map((item) => (item.id === updated.id ? updated : item)) } : current);
      onStatus?.({ kind: "ready", message: "图像 Prompt 已优化并保存版本" });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "图像 Prompt 优化失败" });
    } finally {
      setOptimizingPromptNodeId("");
    }
  }
```

- [ ] **Step 7: Add new state and actions to the view payload**

In the `state` object passed to `CanvasWorkspaceView`, include:

```js
    optimizingPromptNodeId,
    promptArtifacts,
```

In the `actions` object passed to `CanvasWorkspaceView`, include:

```js
    addStoryboardNode,
    optimizeStoryboardImagePrompt,
```

- [ ] **Step 8: Run frontend build**

Run:

```bash
npm run build
```

Expected: FAIL if the new state/actions are not yet consumed cleanly by the view, otherwise PASS. Continue to Task 9 before treating this as complete.

---

### Task 9: Frontend View Integration

**Files:**
- Modify: `frontend/src/workspace/CanvasWorkspaceComponents.jsx`
- Modify: `frontend/src/workspace/CanvasWorkspaceController.jsx`
- Test: manual browser verification after build

- [ ] **Step 1: Import the prompt panel**

At the top of `frontend/src/workspace/CanvasWorkspaceComponents.jsx`, add:

```js
import { StoryboardPromptPanel } from "./StoryboardPromptPanel";
```

- [ ] **Step 2: Add the storyboard node label**

In `NODE_TYPE_LABELS`, add:

```js
  storyboard: "Storyboard",
```

- [ ] **Step 3: Destructure the new state values**

In `CanvasWorkspaceView`, add these to the state destructuring list:

```js
    optimizingPromptNodeId,
    promptArtifacts,
```

- [ ] **Step 4: Add the command-panel storyboard creation button**

Immediately after the existing “放入画布” button, add:

```jsx
        <button className="secondary-image-action canvas-brief-action" type="button" onClick={actions.addStoryboardNode} disabled={!brief.trim() || loading || creating}>
          {creating ? <Loader2 className="spinning" size={18} /> : <Film size={18} />}
          <span>创建分镜节点</span>
        </button>
```

- [ ] **Step 5: Render the prompt panel in the inspector**

Immediately after the selected-node inspector line:

```jsx
        {selectedNode ? <NodeInspector node={selectedNode} edges={canvas?.edges || []} assetById={assetById} updatingPromptProgram={updatingPromptProgram} onSavePromptProgram={actions.updatePromptProgramNode} /> : <p>选择节点查看 Prompt、参考资产和后续编译信息。</p>}
```

add:

```jsx
        <StoryboardPromptPanel selectedNode={selectedNode} artifacts={promptArtifacts || []} optimizingNodeId={optimizingPromptNodeId} onOptimize={actions.optimizeStoryboardImagePrompt} />
```

- [ ] **Step 6: Add an inspector action button for the selected graph**

In the `.canvas-inspector-actions` section, before the existing “生成 Prompt Program” button, add:

```jsx
          {selectedNode && ["brief", "storyboard", "series_frame", "shot", "prompt_program", "semantic_spec"].includes(selectedNode.type) ? (
            <button className="secondary-image-action" type="button" onClick={() => actions.optimizeStoryboardImagePrompt(selectedNode)} disabled={loading || optimizingPromptNodeId === selectedNode.id}>
              {optimizingPromptNodeId === selectedNode.id ? <Loader2 className="spinning" size={16} /> : <Sparkles size={16} />}
              <span>优化图像 Prompt</span>
            </button>
          ) : null}
```

- [ ] **Step 7: Run frontend build**

Run:

```bash
npm run build
```

Expected: PASS.

- [ ] **Step 8: Conditional commit**

Run:

```bash
git -C /Users/apple/Documents/tup rev-parse --is-inside-work-tree && git -C /Users/apple/Documents/tup add frontend/src/api/canvas.js frontend/src/workspace/CanvasWorkspaceController.jsx frontend/src/workspace/CanvasWorkspaceComponents.jsx frontend/src/workspace/StoryboardPromptPanel.jsx && git -C /Users/apple/Documents/tup commit -m "feat: add storyboard prompt panel"
```

Expected: In this current workspace, `git rev-parse` may fail because `/Users/apple/Documents/tup` is not a git repo. If it fails, record that no commit was made and continue to verification.

---

### Task 10: Verification Pass

**Files:**
- No code edits unless verification reveals failures.

- [ ] **Step 1: Run backend canvas tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py tests/test_canvas_generation_lineage.py -q
```

Expected: PASS.

- [ ] **Step 2: Run prompt-related tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_evaluator.py tests/test_prompt_skill_agent.py tests/test_prompt_spec_compiler.py -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend build**

Run:

```bash
npm run build
```

Expected: PASS.

- [ ] **Step 4: Run the full backend test suite when time allows**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS.

- [ ] **Step 5: Manual browser verification**

Run:

```bash
npm run dev
```

Then verify this flow in the browser:

1. Register or sign in.
2. Create a project.
3. Open the canvas.
4. Type a Chinese creative brief.
5. Click “创建分镜节点”.
6. Select the new storyboard node.
7. Click “优化图像 Prompt”.
8. Confirm the inspector shows the saved final prompt and prompt score.
9. Click “生成候选图” with the storyboard node selected.
10. Confirm generated image candidates still appear and can be selected.

Expected: The canvas prompt optimization does not break existing image batch generation.

---

## Self-Review

- Spec coverage: This plan covers reuse of the existing prompt scoring system, canvas-first workflow, storyboard node metadata, prompt version history, and image prompt optimization. It intentionally leaves video prompt optimization, image-to-video generation changes, credits, review/admin expansion, and public SaaS growth loops for later subsystem plans.
- Placeholder scan: No placeholder sections remain. Every task names exact files, concrete code, commands, and expected outcomes.
- Type consistency: The new API uses `CanvasStoryboardImagePromptRequest`, `CanvasStoryboardImagePromptResponse`, `PromptArtifactListResponse`, and the existing `PromptArtifactResponse`. The artifact kind is consistently `storyboard_image_prompt_version`. The frontend calls the matching endpoints through `fetchCanvasPromptArtifacts()` and `optimizeCanvasImagePrompt()`.
