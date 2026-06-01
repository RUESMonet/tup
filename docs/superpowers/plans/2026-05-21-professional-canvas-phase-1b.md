# Professional Canvas Phase 1B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a storyboard-aware image-to-video prompt optimization workflow that saves motion prompt versions and feeds optimized prompts into the existing canvas video generation route.

**Architecture:** Reuse the existing canvas, prompt artifact, image candidate, asset, and video router boundaries. Add a focused deterministic video prompt optimizer for storyboard motion prompts, persist versions as `storyboard_video_prompt_version`, and let the current `/api/canvases/{canvas_id}/generate/video` route consume an authorized prompt artifact when present.

**Tech Stack:** FastAPI, Pydantic v2, SQLite repository layer, existing canvas prompt artifacts, existing `VideoRouter`, React/Vite canvas workspace.

---

## Scope

This phase implements only the storyboard image-to-video slice:

- Video prompt optimization from canvas/storyboard fields and selected image context.
- Version persistence with `prompt_artifacts.kind = "storyboard_video_prompt_version"`.
- Optional `prompt_artifact_id` linkage for canvas video generation.
- Frontend optimization controls and video dialog prefill.
- Tests and build verification.

This phase does not implement credits, billing, admin dashboards, payment automation, public community, timeline editing, or final film assembly.

## File Structure

- Create: `src/agents/canvas_video_prompt_optimizer.py`
  - Small deterministic optimizer that turns storyboard/canvas/source context into a motion prompt and simple quality report.
- Modify: `src/models/canvas.py`
  - Add video prompt optimization request/response models.
  - Add optional `prompt_artifact_id` to `CanvasGenerateVideoRequest`.
- Modify: `src/api/canvas_routes.py`
  - Add `/api/canvases/{canvas_id}/storyboard/video-prompt`.
  - Validate video prompt artifacts in `/generate/video` and use the stored final prompt when linked.
- Modify: `src/services/canvas_repository.py`
  - Persist `prompt_artifact_id` on generated video node payload/asset metadata.
- Modify: `frontend/src/api/canvas.js`
  - Add `optimizeCanvasVideoPrompt()`.
- Modify: `frontend/src/workspace/CanvasWorkspaceController.jsx`
  - Load both image and video artifacts, optimize video prompts, prefill video dialog, submit artifact-linked video generation.
- Modify: `frontend/src/workspace/StoryboardPromptPanel.jsx`
  - Display latest image and video prompt versions and expose video prompt optimization.
- Modify: `frontend/src/workspace/CanvasWorkspaceComponents.jsx`
  - Pass new prompt props/actions and add an optimization action inside `VideoFromCandidateDialog`.
- Test: `tests/test_canvas_routes.py`
  - Route and generation integration coverage.
- Test: `tests/test_canvas_video_prompt_optimizer.py`
  - Deterministic optimizer unit coverage.

## Current Code References

- Existing canvas video route: `src/api/canvas_routes.py:540-572`.
- Existing selected candidate source resolution: `src/api/canvas_routes.py:725-747`.
- Existing generated video persistence: `src/services/canvas_repository.py:844-895` and `src/services/canvas_repository.py:1405-1415`.
- Existing video request model: `src/models/canvas.py:527-561`.
- Existing frontend video dialog state and submit path: `frontend/src/workspace/CanvasWorkspaceController.jsx:1300-1304` and `frontend/src/workspace/CanvasWorkspaceController.jsx:1461-1493`.
- Existing video dialog component: `frontend/src/workspace/CanvasWorkspaceComponents.jsx:981-1011`.
- Existing prompt panel: `frontend/src/workspace/StoryboardPromptPanel.jsx:13-45`.

---

### Task 1: Backend Failing Tests for Video Prompt Versions

**Files:**
- Modify: `tests/test_canvas_routes.py`
- Test: `tests/test_canvas_routes.py`

- [ ] **Step 1: Add model import for the new request**

Change the canvas model import near the top of `tests/test_canvas_routes.py` from:

```python
from src.models.canvas import CanvasStoryboardImagePromptRequest
```

to:

```python
from src.models.canvas import CanvasStoryboardImagePromptRequest, CanvasStoryboardVideoPromptRequest
```

- [ ] **Step 2: Add request validation tests**

Add these tests after `test_storyboard_image_prompt_request_requires_node_in_selection`:

```python
def test_storyboard_video_prompt_request_requires_node_in_selection():
    with pytest.raises(ValueError, match="node_id must be included in selected_node_ids"):
        CanvasStoryboardVideoPromptRequest(node_id="storyboard-a", selected_node_ids=["storyboard-b"])


def test_storyboard_video_prompt_request_rejects_duplicate_sources():
    with pytest.raises(ValueError, match="Choose at most one source image"):
        CanvasStoryboardVideoPromptRequest(
            node_id="storyboard-a",
            selected_node_ids=["storyboard-a"],
            source_candidate_id="candidate-a",
            source_image_asset_id="asset-a",
        )
```

- [ ] **Step 3: Add successful video prompt optimization route test**

Add this test after `test_canvas_storyboard_image_prompt_optimization_persists_version`:

```python
def test_canvas_storyboard_video_prompt_optimization_persists_version(tmp_path):
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
                "camera_motion": "slow dolly in",
                "subject_action": "香水瓶保持稳定，瓶身高光缓慢移动",
                "shot_size": "medium close-up",
                "temporal_rhythm": "calm commercial pacing",
                "ending_state": "clean hero frame",
                "duration": "5",
                "aspect_ratio": "16:9",
            },
        },
    ).json()
    batch = client.post(
        f"/api/canvases/{canvas_id}/image-batches",
        json={
            "selected_node_ids": [storyboard["id"]],
            "model": "openai",
            "threshold": 0.0,
            "max_iter": 1,
            "params": {"n": 1},
            "skip_prompt_evaluation": True,
        },
    ).json()
    listed = client.get(f"/api/canvases/{canvas_id}/image-batches").json()["batches"][0]
    candidate = listed["candidates"][0]
    selected = client.patch(
        f"/api/canvases/{canvas_id}/image-batches/{batch['id']}/candidates/{candidate['id']}",
        json={"status": "selected", "reason": "best hero frame", "position": {"x": 420, "y": 0}},
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/storyboard/video-prompt",
        json={
            "node_id": selected["node_id"],
            "selected_node_ids": [storyboard["id"], selected["node_id"]],
            "root_node_id": storyboard["id"],
            "source_candidate_id": candidate["id"],
            "duration": 5,
            "aspect_ratio": "16:9",
        },
    )
    artifacts = client.get(
        f"/api/canvases/{canvas_id}/prompt-artifacts",
        params={"node_id": selected["node_id"], "kind": "storyboard_video_prompt_version"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert "slow dolly in" in payload["final_prompt"]
    assert "香水瓶保持稳定" in payload["final_prompt"]
    assert payload["video_report"]["score"] >= 8.0
    assert payload["artifact"]["kind"] == "storyboard_video_prompt_version"
    assert payload["artifact"]["node_id"] == selected["node_id"]
    assert payload["artifact"]["payload"]["workflow"] == "storyboard_video_prompt_optimization"
    assert payload["artifact"]["payload"]["source_context"]["candidate_id"] == candidate["id"]
    assert payload["artifact"]["payload"]["final_prompt"] == payload["final_prompt"]
    assert artifacts.status_code == 200
    assert [artifact["id"] for artifact in artifacts.json()["artifacts"]] == [payload["artifact"]["id"]]
```

- [ ] **Step 4: Add foreign candidate rejection test**

Add this test after the success route test:

```python
def test_canvas_storyboard_video_prompt_rejects_foreign_candidate(tmp_path):
    ada_client = _client(tmp_path)
    grace_client = _client(tmp_path)
    _register(ada_client, "ada")
    _register(grace_client, "grace")
    ada_project_id = _project(ada_client, "Ada")
    grace_project_id = _project(grace_client, "Grace")
    ada_canvas_id = _canvas(ada_client, ada_project_id)
    grace_canvas_id = _canvas(grace_client, grace_project_id)
    ada_node = ada_client.post(
        f"/api/canvases/{ada_canvas_id}/nodes",
        json={"type": "storyboard", "title": "Ada shot", "position": {"x": 0, "y": 0}, "payload": {"prompt": "Ada 私有分镜"}},
    ).json()
    grace_node = grace_client.post(
        f"/api/canvases/{grace_canvas_id}/nodes",
        json={"type": "storyboard", "title": "Grace shot", "position": {"x": 0, "y": 0}, "payload": {"prompt": "Grace 私有分镜"}},
    ).json()
    grace_batch = grace_client.post(
        f"/api/canvases/{grace_canvas_id}/image-batches",
        json={"selected_node_ids": [grace_node["id"]], "model": "openai", "threshold": 0.0, "max_iter": 1, "params": {"n": 1}, "skip_prompt_evaluation": True},
    ).json()
    grace_candidate = grace_client.get(f"/api/canvases/{grace_canvas_id}/image-batches").json()["batches"][0]["candidates"][0]

    response = ada_client.post(
        f"/api/canvases/{ada_canvas_id}/storyboard/video-prompt",
        json={"node_id": ada_node["id"], "selected_node_ids": [ada_node["id"]], "source_candidate_id": grace_candidate["id"]},
    )

    assert grace_batch["id"]
    assert response.status_code == 404
    assert response.json()["detail"] == "Source image candidate not found"
```

- [ ] **Step 5: Add artifact-linked video generation test**

Add this test after `test_canvas_image_batch_api_generates_candidates_and_selects_one`:

```python
def test_canvas_video_generation_uses_video_prompt_artifact(tmp_path):
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
            "payload": {"prompt": "香水瓶英雄镜头", "camera_motion": "slow dolly in", "subject_action": "瓶身稳定，光线流动"},
        },
    ).json()
    batch = client.post(
        f"/api/canvases/{canvas_id}/image-batches",
        json={"selected_node_ids": [storyboard["id"]], "model": "openai", "threshold": 0.0, "max_iter": 1, "params": {"n": 1}, "skip_prompt_evaluation": True},
    ).json()
    candidate = client.get(f"/api/canvases/{canvas_id}/image-batches").json()["batches"][0]["candidates"][0]
    selected = client.patch(
        f"/api/canvases/{canvas_id}/image-batches/{batch['id']}/candidates/{candidate['id']}",
        json={"status": "selected", "reason": "best hero frame", "position": {"x": 420, "y": 0}},
    ).json()
    optimized = client.post(
        f"/api/canvases/{canvas_id}/storyboard/video-prompt",
        json={"node_id": selected["node_id"], "selected_node_ids": [storyboard["id"], selected["node_id"]], "source_candidate_id": candidate["id"], "duration": 5},
    ).json()

    response = client.post(
        f"/api/canvases/{canvas_id}/generate/video",
        json={"prompt": "manual prompt should be replaced", "prompt_artifact_id": optimized["artifact"]["id"], "source_candidate_id": candidate["id"], "duration": 5},
    )
    task = _wait_for_task(client, response.json()["task_id"])
    canvas = client.get(f"/api/canvases/{canvas_id}").json()
    generated = next(node for node in canvas["nodes"] if node["type"] == "generated_video")

    assert response.status_code == 202
    assert task["input"]["prompt_artifact_id"] == optimized["artifact"]["id"]
    assert task["input"]["prompt"] == optimized["final_prompt"]
    assert generated["payload"]["prompt_artifact_id"] == optimized["artifact"]["id"]
    assert generated["payload"]["motion_prompt"] == optimized["final_prompt"]
```

- [ ] **Step 6: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py::test_storyboard_video_prompt_request_requires_node_in_selection tests/test_canvas_routes.py::test_storyboard_video_prompt_request_rejects_duplicate_sources tests/test_canvas_routes.py::test_canvas_storyboard_video_prompt_optimization_persists_version tests/test_canvas_routes.py::test_canvas_storyboard_video_prompt_rejects_foreign_candidate tests/test_canvas_routes.py::test_canvas_video_generation_uses_video_prompt_artifact -q
```

Expected: FAIL because `CanvasStoryboardVideoPromptRequest` and `/storyboard/video-prompt` do not exist yet, and `/generate/video` does not accept `prompt_artifact_id`.

---

### Task 2: Optimizer Unit Tests

**Files:**
- Create: `tests/test_canvas_video_prompt_optimizer.py`
- Test: `tests/test_canvas_video_prompt_optimizer.py`

- [ ] **Step 1: Create failing optimizer tests**

Create `tests/test_canvas_video_prompt_optimizer.py` with this content:

```python
from src.agents.canvas_graph_compiler import CanvasCompileProduct, CreativeGraph
from src.agents.canvas_video_prompt_optimizer import build_storyboard_video_prompt
from src.models.canvas import CanvasNodeResponse


def _node(payload: dict) -> CanvasNodeResponse:
    return CanvasNodeResponse(
        id="node-1",
        canvas_id="canvas-1",
        type="storyboard",
        title="Shot 01",
        position={"x": 0, "y": 0},
        size={"width": 280, "height": 160},
        payload=payload,
        created_at="2026-05-21T00:00:00Z",
        updated_at="2026-05-21T00:00:00Z",
    )


def _compiled() -> CanvasCompileProduct:
    return CanvasCompileProduct(
        creative_graph=CreativeGraph(
            canvas_id="canvas-1",
            project_id="project-1",
            primary_brief="Compiled canvas prompt for a perfume hero frame",
            nodes=[],
            edges=[],
        ),
        prompt_spec={"task": "storyboard_video"},
        final_prompt="Compiled canvas prompt for a perfume hero frame",
    )


def test_video_prompt_optimizer_uses_storyboard_motion_fields():
    draft = build_storyboard_video_prompt(
        _node(
            {
                "scene": "black gold studio",
                "camera_motion": "slow dolly in",
                "subject_action": "perfume bottle stays stable while highlights move",
                "shot_size": "medium close-up",
                "temporal_rhythm": "calm commercial pacing",
                "ending_state": "clean hero frame",
                "duration": "5",
                "aspect_ratio": "16:9",
            }
        ),
        _compiled(),
        {"candidate_id": "candidate-1", "prompt": "crisp product image", "score": 8.7},
        duration=5,
        aspect_ratio="16:9",
    )

    assert "slow dolly in" in draft.final_prompt
    assert "perfume bottle stays stable" in draft.final_prompt
    assert "clean hero frame" in draft.final_prompt
    assert draft.video_report["score"] >= 8.0
    assert draft.source_context["candidate_id"] == "candidate-1"


def test_video_prompt_optimizer_degrades_with_sparse_storyboard_fields():
    draft = build_storyboard_video_prompt(
        _node({"prompt": "minimal product motion"}),
        _compiled(),
        {},
        duration=None,
        aspect_ratio=None,
    )

    assert "minimal product motion" in draft.final_prompt
    assert "steady motion" in draft.final_prompt
    assert draft.video_report["missing"]
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_video_prompt_optimizer.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.agents.canvas_video_prompt_optimizer'`.

---

### Task 3: Canvas Models

**Files:**
- Modify: `src/models/canvas.py:527-561`
- Test: `tests/test_canvas_routes.py`

- [ ] **Step 1: Add `prompt_artifact_id` to `CanvasGenerateVideoRequest`**

Modify `CanvasGenerateVideoRequest` to include `prompt_artifact_id` and validate it with existing optional IDs:

```python
class CanvasGenerateVideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=12000)
    prompt_artifact_id: str | None = Field(default=None, min_length=1)
    source_candidate_id: str | None = Field(default=None, min_length=1)
    source_image_asset_id: str | None = Field(default=None, min_length=1)
    selected_node_ids: list[str] = Field(default_factory=list, max_length=80)
    duration: int | None = Field(default=None, ge=1, le=60)
    aspect_ratio: str | None = Field(default=None, max_length=32)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("prompt")
    @classmethod
    def strip_video_prompt(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Prompt is required")
        return stripped

    @field_validator("prompt_artifact_id", "source_candidate_id", "source_image_asset_id", "aspect_ratio")
    @classmethod
    def strip_optional_video_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank")
        return stripped

    @field_validator("selected_node_ids")
    @classmethod
    def validate_unique_video_node_ids(cls, value: list[str]) -> list[str]:
        return _validate_unique_node_ids(value) if value else []

    @field_validator("params")
    @classmethod
    def validate_video_params_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_canvas_payload(value)
        return value

    @model_validator(mode="after")
    def validate_video_source(self) -> "CanvasGenerateVideoRequest":
        if bool(self.source_candidate_id) == bool(self.source_image_asset_id):
            raise ValueError("Choose exactly one source image candidate or source image asset")
        return self
```

- [ ] **Step 2: Add video prompt request/response models**

Add these classes after `CanvasStoryboardImagePromptRequest`:

```python
class CanvasStoryboardVideoPromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    selected_node_ids: list[str] = Field(min_length=1, max_length=80)
    root_node_id: str | None = Field(default=None, min_length=1)
    source_candidate_id: str | None = Field(default=None, min_length=1)
    source_image_asset_id: str | None = Field(default=None, min_length=1)
    duration: int | None = Field(default=None, ge=1, le=60)
    aspect_ratio: str | None = Field(default=None, max_length=32)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("node_id", "root_node_id", "source_candidate_id", "source_image_asset_id", "aspect_ratio")
    @classmethod
    def strip_optional_video_prompt_ids(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value cannot be blank")
        return stripped

    @field_validator("selected_node_ids")
    @classmethod
    def validate_unique_video_prompt_node_ids(cls, value: list[str]) -> list[str]:
        return _validate_unique_node_ids(value)

    @field_validator("params")
    @classmethod
    def validate_video_prompt_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_canvas_payload(value)
        return value

    @model_validator(mode="after")
    def validate_video_prompt_selection(self) -> "CanvasStoryboardVideoPromptRequest":
        if self.node_id not in self.selected_node_ids:
            raise ValueError("node_id must be included in selected_node_ids")
        if self.source_candidate_id and self.source_image_asset_id:
            raise ValueError("Choose at most one source image")
        return self
```

Add this response model after `CanvasStoryboardImagePromptResponse`:

```python
class CanvasStoryboardVideoPromptResponse(BaseModel):
    final_prompt: str
    video_report: dict[str, Any]
    source_context: dict[str, Any]
    artifact: PromptArtifactResponse
```

- [ ] **Step 3: Run model tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py::test_storyboard_video_prompt_request_requires_node_in_selection tests/test_canvas_routes.py::test_storyboard_video_prompt_request_rejects_duplicate_sources -q
```

Expected: PASS.

---

### Task 4: Video Prompt Optimizer Helper

**Files:**
- Create: `src/agents/canvas_video_prompt_optimizer.py`
- Test: `tests/test_canvas_video_prompt_optimizer.py`

- [ ] **Step 1: Create optimizer helper**

Create `src/agents/canvas_video_prompt_optimizer.py` with this content:

```python
from typing import Any

from pydantic import BaseModel, Field

from src.agents.canvas_graph_compiler import CanvasCompileProduct
from src.models.canvas import CanvasNodeResponse

VIDEO_DIMENSIONS = (
    "reference_image_role",
    "subject_action",
    "camera_motion",
    "shot_size",
    "duration",
    "temporal_rhythm",
    "ending_state",
    "stability_constraints",
)


class CanvasVideoPromptDraft(BaseModel):
    final_prompt: str
    video_report: dict[str, Any] = Field(default_factory=dict)
    source_context: dict[str, Any] = Field(default_factory=dict)


def build_storyboard_video_prompt(
    node: CanvasNodeResponse,
    compiled: CanvasCompileProduct,
    source_context: dict[str, Any],
    duration: int | None,
    aspect_ratio: str | None,
) -> CanvasVideoPromptDraft:
    payload = node.payload or {}
    scene = _first_text(payload, "scene", "environment", "prompt", fallback=compiled.final_prompt)
    camera_motion = _first_text(payload, "camera_motion", "camera", fallback="steady motion with controlled cinematic movement")
    subject_action = _first_text(payload, "subject_action", "action", fallback="subject remains stable with subtle premium motion")
    shot_size = _first_text(payload, "shot_size", "composition", fallback="medium shot with clean composition")
    rhythm = _first_text(payload, "temporal_rhythm", fallback="calm commercial pacing")
    ending = _first_text(payload, "ending_state", fallback="clean final hero frame")
    duration_text = str(duration or payload.get("duration") or "5")
    aspect_text = aspect_ratio or str(payload.get("aspect_ratio") or "16:9")
    source_prompt = _source_text(source_context)
    parts = [
        f"Image-to-video motion prompt for a {duration_text}s {aspect_text} clip.",
        f"Reference image role: preserve the selected frame identity, composition, material, lighting, and color palette.{source_prompt}",
        f"Scene: {scene}.",
        f"Subject action: {subject_action}.",
        f"Camera motion: {camera_motion}.",
        f"Shot size and composition: {shot_size}.",
        f"Temporal rhythm: {rhythm}.",
        f"Ending state: {ending}.",
        "Stability constraints: no identity drift, no geometry warping, no flicker, no unwanted camera shake, no extra limbs, no text morphing.",
        "Negative motion prompt: avoid chaotic motion, melting details, sudden cuts, inconsistent reflections, unstable product silhouette, and background popping.",
    ]
    final_prompt = " ".join(_normalize(part) for part in parts if _normalize(part))
    missing = [dimension for dimension, present in _dimension_presence(payload, source_context, duration, aspect_ratio).items() if not present]
    score = round(max(6.0, 10.0 - len(missing) * 0.45), 1)
    return CanvasVideoPromptDraft(
        final_prompt=final_prompt,
        source_context={key: value for key, value in source_context.items() if value is not None},
        video_report={
            "score": score,
            "passed": score >= 8.0,
            "missing": missing,
            "dimensions": list(VIDEO_DIMENSIONS),
            "suggestion": "补充缺失的运动、稳定性或结尾状态字段可提升图生视频一致性。" if missing else "视频 Prompt 已覆盖图生视频关键维度。",
        },
    )


def _first_text(payload: dict[str, Any], *keys: str, fallback: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback.strip()


def _source_text(source_context: dict[str, Any]) -> str:
    prompt = source_context.get("prompt")
    score = source_context.get("score")
    if isinstance(prompt, str) and prompt.strip():
        score_text = f" Source score: {score}." if isinstance(score, (int, float)) else ""
        return f" Source image prompt: {prompt.strip()}.{score_text}"
    return ""


def _dimension_presence(payload: dict[str, Any], source_context: dict[str, Any], duration: int | None, aspect_ratio: str | None) -> dict[str, bool]:
    return {
        "reference_image_role": bool(source_context),
        "subject_action": bool(_optional_text(payload, "subject_action", "action")),
        "camera_motion": bool(_optional_text(payload, "camera_motion", "camera")),
        "shot_size": bool(_optional_text(payload, "shot_size", "composition")),
        "duration": bool(duration or payload.get("duration")),
        "temporal_rhythm": bool(_optional_text(payload, "temporal_rhythm")),
        "ending_state": bool(_optional_text(payload, "ending_state")),
        "stability_constraints": True,
    }


def _optional_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize(value: str) -> str:
    return " ".join(value.strip().split())
```

- [ ] **Step 2: Run optimizer tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_video_prompt_optimizer.py -q
```

Expected: PASS.

---

### Task 5: Backend Video Prompt Route and Artifact Persistence

**Files:**
- Modify: `src/api/canvas_routes.py`
- Test: `tests/test_canvas_routes.py`

- [ ] **Step 1: Add imports**

In `src/api/canvas_routes.py`, add the optimizer import near existing agent imports:

```python
from src.agents.canvas_video_prompt_optimizer import build_storyboard_video_prompt
```

Add these model imports in the `src.models.canvas` import block:

```python
    CanvasStoryboardVideoPromptRequest,
    CanvasStoryboardVideoPromptResponse,
```

- [ ] **Step 2: Add source context helper**

Add this helper near `_resolve_canvas_video_source`:

```python
def _canvas_video_prompt_source_context(
    owner_id: str,
    canvas_id: str,
    project_id: str,
    request: CanvasStoryboardVideoPromptRequest,
    canvas_repository: CanvasRepository,
    project_repository: ProjectRepository,
) -> dict[str, Any]:
    if request.source_candidate_id:
        candidate = canvas_repository.get_image_candidate(owner_id, canvas_id, request.source_candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Source image candidate not found")
        return {
            "candidate_id": candidate.id,
            "asset_id": candidate.asset_id,
            "node_id": candidate.node_id,
            "prompt": candidate.prompt,
            "score": candidate.score,
            "status": candidate.status,
        }
    if request.source_image_asset_id:
        asset = project_repository.get_asset(owner_id, project_id, request.source_image_asset_id)
        if asset is None or asset.kind != AssetKind.image:
            raise HTTPException(status_code=404, detail="Source image asset not found")
        return {"asset_id": asset.id, "image_url": asset.url, "media_type": asset.media_type}
    return {}
```

- [ ] **Step 3: Add route**

Add this route immediately after `optimize_storyboard_image_prompt`:

```python
@router.post(
    "/api/canvases/{canvas_id}/storyboard/video-prompt",
    response_model=CanvasStoryboardVideoPromptResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_high_cost_access)],
)
async def optimize_storyboard_video_prompt(
    canvas_id: str,
    request: CanvasStoryboardVideoPromptRequest,
    user: AuthUser = Depends(require_current_user),
    canvas_repository: CanvasRepository = Depends(get_canvas_repository),
    project_repository: ProjectRepository = Depends(get_project_repository),
) -> CanvasStoryboardVideoPromptResponse:
    canvas = await asyncio.to_thread(canvas_repository.get_canvas, user.id, canvas_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    canvas_node_ids = {node.id for node in canvas.nodes}
    if request.node_id not in canvas_node_ids or not set(request.selected_node_ids).issubset(canvas_node_ids):
        raise HTTPException(status_code=404, detail="Selected node not found")
    if request.root_node_id is not None and request.root_node_id not in set(request.selected_node_ids):
        raise HTTPException(status_code=404, detail="Root node not found")
    _reject_archived_repair_version_selection(canvas, request.selected_node_ids)
    node = next(item for item in canvas.nodes if item.id == request.node_id)
    source_context = await asyncio.to_thread(_canvas_video_prompt_source_context, user.id, canvas_id, canvas.project_id, request, canvas_repository, project_repository)
    compiled = await asyncio.to_thread(_compile_canvas_or_422, canvas, request.selected_node_ids, None, request.root_node_id)
    draft = build_storyboard_video_prompt(node, compiled, source_context, request.duration, request.aspect_ratio)
    payload = {
        "workflow": "storyboard_video_prompt_optimization",
        "node_id": request.node_id,
        "selected_node_ids": request.selected_node_ids,
        "root_node_id": request.root_node_id,
        "source_candidate_id": request.source_candidate_id,
        "source_image_asset_id": request.source_image_asset_id,
        "duration": request.duration,
        "aspect_ratio": request.aspect_ratio,
        "compiled_prompt": compiled.final_prompt,
        "final_prompt": draft.final_prompt,
        "video_report": draft.video_report,
        "source_context": draft.source_context,
    }
    try:
        artifact = await asyncio.to_thread(
            canvas_repository.create_prompt_artifact,
            user.id,
            canvas_id,
            request.node_id,
            "storyboard_video_prompt_version",
            payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if artifact is None:
        raise HTTPException(status_code=404, detail="Canvas or node not found")
    return CanvasStoryboardVideoPromptResponse(final_prompt=draft.final_prompt, video_report=draft.video_report, source_context=draft.source_context, artifact=artifact)
```

- [ ] **Step 4: Run route tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py::test_canvas_storyboard_video_prompt_optimization_persists_version tests/test_canvas_routes.py::test_canvas_storyboard_video_prompt_rejects_foreign_candidate -q
```

Expected: PASS.

---

### Task 6: Artifact-Linked Canvas Video Generation

**Files:**
- Modify: `src/api/canvas_routes.py:540-572`
- Modify: `src/services/canvas_repository.py:844-895`
- Modify: `src/services/canvas_repository.py:1405-1415`
- Test: `tests/test_canvas_routes.py`

- [ ] **Step 1: Validate and apply video prompt artifacts in the route**

Modify `generate_canvas_video` so the route resolves an effective prompt before creating `VideoGenerateRequest`:

```python
    artifact = None
    if request.prompt_artifact_id is not None:
        artifact = await asyncio.to_thread(canvas_repository.get_prompt_artifact, user.id, canvas_id, request.prompt_artifact_id)
        if artifact is None or artifact.kind != "storyboard_video_prompt_version":
            raise HTTPException(status_code=404, detail="Prompt artifact not found")
    effective_prompt = _prompt_artifact_final_prompt(artifact) or request.prompt
    source_image_url = await asyncio.to_thread(_provider_image_source, source_asset.url, source_asset.media_type, settings)
    execution_request = VideoGenerateRequest(prompt=effective_prompt, source_image_asset_id=source_asset.id, source_image_url=source_image_url, duration=request.duration, aspect_ratio=request.aspect_ratio, params=request.params)
    task_input = {**request.model_dump(mode="json"), "prompt": effective_prompt, "canvas_id": canvas_id, "source_asset_id": source_asset.id, "workflow": "image_to_video_from_canvas"}
```

Keep the existing validation and task creation around this block unchanged.

- [ ] **Step 2: Pass artifact id to the background task**

Change the background task call to include the artifact id:

```python
    background_tasks.add_task(
        _run_canvas_video_task,
        user.id,
        task.task_id,
        canvas.project_id,
        canvas_id,
        source_node_ids or request.selected_node_ids,
        source_asset.id,
        request.prompt_artifact_id,
        execution_request,
        canvas_repository,
        project_repository,
        video_router,
    )
```

Update `_run_canvas_video_task` signature:

```python
async def _run_canvas_video_task(
    owner_id: str,
    task_id: str,
    project_id: str,
    canvas_id: str,
    source_node_ids: list[str],
    source_asset_id: str,
    prompt_artifact_id: str | None,
    request: VideoGenerateRequest,
    canvas_repository: CanvasRepository,
    project_repository: ProjectRepository,
    video_router: VideoRouter,
) -> None:
```

- [ ] **Step 3: Persist artifact id on generated video results**

Modify the `create_generated_video_result` call in `_run_canvas_video_task`:

```python
        generated = await asyncio.to_thread(
            canvas_repository.create_generated_video_result,
            owner_id,
            project_id,
            canvas_id,
            source_node_ids,
            source_asset_id,
            prompt_artifact_id,
            result.url,
            result.media_type,
            task_id,
            request.prompt,
            {"x": 840, "y": 0},
        )
```

Modify `CanvasRepository.create_generated_video_result` signature:

```python
    def create_generated_video_result(
        self,
        owner_id: str,
        project_id: str,
        canvas_id: str,
        source_node_ids: list[str],
        source_asset_id: str,
        prompt_artifact_id: str | None,
        video_url: str,
        media_type: str,
        task_id: str,
        prompt: str,
        position: dict[str, float],
    ) -> tuple[CanvasNodeResponse, str] | None:
```

Modify the asset metadata insert payload:

```python
_json({
    "task_id": task_id,
    "canvas_id": canvas_id,
    "source": "canvas_video_generation",
    "source_asset_id": source_asset_id,
    "source_node_ids": source_node_ids,
    "prompt_artifact_id": prompt_artifact_id,
})
```

Modify the node insert payload call:

```python
_json(_generated_video_node_payload(asset_id, source_node_ids, source_asset_id, prompt_artifact_id, media_type, task_id, prompt))
```

Modify `_generated_video_node_payload`:

```python
def _generated_video_node_payload(asset_id: str, source_node_ids: list[str], source_asset_id: str, prompt_artifact_id: str | None, media_type: str, task_id: str, prompt: str) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "source_node_ids": source_node_ids,
        "source_asset_id": source_asset_id,
        "prompt_artifact_id": prompt_artifact_id,
        "media_type": media_type,
        "role": "generated_video",
        "source": "canvas_video_generation",
        "task_id": task_id,
        "motion_prompt": prompt[:MAX_GENERATED_FINAL_PROMPT_CHARS],
    }
```

- [ ] **Step 4: Run artifact-linked video generation test**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py::test_canvas_video_generation_uses_video_prompt_artifact -q
```

Expected: PASS.

---

### Task 7: Frontend API and Controller Wiring

**Files:**
- Modify: `frontend/src/api/canvas.js`
- Modify: `frontend/src/workspace/CanvasWorkspaceController.jsx`
- Test: `npm run build`

- [ ] **Step 1: Add video prompt API helper**

Add this helper after `optimizeCanvasImagePrompt` in `frontend/src/api/canvas.js`:

```js
export function optimizeCanvasVideoPrompt(canvasId, payload) {
  return postJson(`/api/canvases/${canvasId}/storyboard/video-prompt`, payload);
}
```

- [ ] **Step 2: Import helper in controller**

Add `optimizeCanvasVideoPrompt` to the long import from `../api/canvas` in `frontend/src/workspace/CanvasWorkspaceController.jsx`.

- [ ] **Step 3: Add controller state**

Add state near existing video dialog and prompt artifact state:

```js
const [optimizingVideoPromptNodeId, setOptimizingVideoPromptNodeId] = useState("");
const [videoPromptArtifactId, setVideoPromptArtifactId] = useState("");
```

- [ ] **Step 4: Load all recent prompt artifacts**

In both `loadCanvas()` and `refreshCanvasArtifacts()`, change the prompt artifact fetch from kind-specific image loading:

```js
fetchCanvasPromptArtifacts(firstCanvas.id, { kind: "storyboard_image_prompt_version", limit: 80 })
```

to all recent canvas prompt artifacts:

```js
fetchCanvasPromptArtifacts(firstCanvas.id, { limit: 100 })
```

Make the same replacement for `canvas.id` inside `refreshCanvasArtifacts()`.

- [ ] **Step 5: Add latest artifact helpers**

Add these helpers near other controller-local utility functions:

```js
function latestNodePromptArtifact(artifacts, nodeId, kind) {
  return (Array.isArray(artifacts) ? artifacts : []).find((artifact) => artifact.node_id === nodeId && artifact.kind === kind) || null;
}

function artifactPrompt(artifact) {
  return artifact?.payload?.final_prompt || artifact?.payload?.compiled_prompt || "";
}
```

- [ ] **Step 6: Add video prompt optimization action**

Add this function after `optimizeStoryboardImagePrompt`:

```js
async function optimizeStoryboardVideoPrompt(node = selectedNode, sourceCandidate = videoDialogCandidate) {
  if (!canvas || !node || optimizingVideoPromptNodeId) {
    return;
  }
  const sourceIds = selectedSourceNodeIds(canvas, node.id);
  const selectedNodeIds = sourceIds.length ? sourceIds : [node.id];
  setOptimizingVideoPromptNodeId(node.id);
  try {
    const response = await optimizeCanvasVideoPrompt(canvas.id, {
      node_id: node.id,
      selected_node_ids: selectedNodeIds,
      root_node_id: selectedNodeIds.includes(node.id) ? node.id : selectedNodeIds[0],
      source_candidate_id: sourceCandidate?.id || undefined,
      duration: VIDEO_DEFAULTS.duration,
      aspect_ratio: VIDEO_DEFAULTS.aspectRatio,
      params: {},
    });
    setPromptArtifacts((current) => [response.artifact, ...current.filter((artifact) => artifact.id !== response.artifact.id)]);
    const nextPayload = { ...node.payload, video_prompt_artifact_id: response.artifact.id, motion_prompt: response.final_prompt };
    const updated = await updateCanvasNode(canvas.id, node.id, { payload: nextPayload });
    setCanvas((current) => (current ? { ...current, nodes: current.nodes.map((item) => (item.id === updated.id ? updated : item)) } : current));
    setVideoPrompt(response.final_prompt);
    setVideoPromptArtifactId(response.artifact.id);
    onStatus?.({ kind: "ready", message: "视频 Prompt 已优化并保存版本" });
  } catch (error) {
    onStatus?.({ kind: "failed", message: error?.message || "视频 Prompt 优化失败" });
  } finally {
    setOptimizingVideoPromptNodeId("");
  }
}
```

- [ ] **Step 7: Prefill video dialog with latest video artifact**

Replace `openVideoDialog(candidate)` with:

```js
function openVideoDialog(candidate) {
  dialogReturnFocusRef.current = document.activeElement;
  const nodeId = candidate?.node_id || "";
  const latestVideoArtifact = nodeId ? latestNodePromptArtifact(promptArtifacts, nodeId, "storyboard_video_prompt_version") : null;
  const prompt = artifactPrompt(latestVideoArtifact) || `基于这张精选图生成专业短片：保持主体身份、材质、构图和光影，加入克制的镜头推进与高级商业广告节奏。`;
  setVideoDialogCandidate(candidate);
  setVideoPrompt(prompt);
  setVideoPromptArtifactId(latestVideoArtifact?.id || "");
}
```

- [ ] **Step 8: Clear artifact link when user edits prompt**

Add this action helper near dialog setters:

```js
function updateVideoPrompt(value) {
  setVideoPrompt(value);
  setVideoPromptArtifactId("");
}
```

Pass `updateVideoPrompt` instead of `setVideoPrompt` in the actions object:

```js
setVideoPrompt: updateVideoPrompt,
```

- [ ] **Step 9: Submit artifact-linked video generation**

In `createVideoFromCandidate()`, include `prompt_artifact_id`:

```js
      const task = await createCanvasVideoTask(canvas.id, {
        prompt,
        prompt_artifact_id: videoPromptArtifactId || undefined,
        source_candidate_id: videoDialogCandidate.id,
        selected_node_ids: sourceNodeIds,
        duration: VIDEO_DEFAULTS.duration,
        aspect_ratio: VIDEO_DEFAULTS.aspectRatio,
        params: {},
      });
```

Clear the artifact id after closing:

```js
      setVideoPromptArtifactId("");
```

Also add `setVideoPromptArtifactId("")` inside `closeVideoDialog()` after `setVideoDialogCandidate(null)`.

- [ ] **Step 10: Pass new state and actions to the view**

Add to the state object passed into `CanvasWorkspaceView`:

```js
optimizingVideoPromptNodeId,
videoPromptArtifactId,
```

Add to the actions object passed into `CanvasWorkspaceView`:

```js
optimizeStoryboardVideoPrompt,
```

- [ ] **Step 11: Run frontend build**

Run:

```bash
npm run build
```

Expected: PASS.

---

### Task 8: Prompt Panel and Video Dialog UI

**Files:**
- Modify: `frontend/src/workspace/StoryboardPromptPanel.jsx`
- Modify: `frontend/src/workspace/CanvasWorkspaceComponents.jsx`
- Test: `npm run build`

- [ ] **Step 1: Extend prompt panel props and artifact filters**

Change the component signature in `StoryboardPromptPanel.jsx` to:

```js
export function StoryboardPromptPanel({ selectedNode, artifacts = [], optimizingNodeId, optimizingVideoNodeId, onOptimize, onOptimizeVideo }) {
```

Replace the artifact selection block with:

```js
  const imageArtifacts = safeArtifacts.filter((artifact) => artifact.node_id === selectedNode.id && artifact.kind === "storyboard_image_prompt_version");
  const videoArtifacts = safeArtifacts.filter((artifact) => artifact.node_id === selectedNode.id && artifact.kind === "storyboard_video_prompt_version");
  const latest = imageArtifacts[0] || null;
  const latestVideo = videoArtifacts[0] || null;
  const busy = Boolean(optimizingNodeId);
  const videoBusy = Boolean(optimizingVideoNodeId);
  const canRunOptimize = typeof onOptimize === "function";
  const canRunVideoOptimize = typeof onOptimizeVideo === "function";
  const canOptimize = ["brief", "storyboard", "series_frame", "shot", "prompt_program", "semantic_spec", "selected_image"].includes(selectedNode.type);
```

- [ ] **Step 2: Add video optimization button and latest video section**

After the image optimize button, add:

```jsx
      <button className="secondary-image-action compact" type="button" onClick={() => onOptimizeVideo?.(selectedNode)} disabled={videoBusy || !canRunVideoOptimize}>
        {videoBusy ? <Loader2 className="spinning" size={16} /> : <Sparkles size={16} />}
        <span>{latestVideo ? "重新优化视频 Prompt" : "优化视频 Prompt"}</span>
      </button>
```

After the existing image artifact block, add:

```jsx
      {latestVideo ? (
        <div className="canvas-safe-fields">
          <div><span>最新视频版本</span><strong>{artifactTitle(latestVideo)}</strong></div>
          <div><span>Motion Prompt</span><strong>{artifactFinalPrompt(latestVideo)}</strong></div>
        </div>
      ) : (
        <small>还没有保存的视频 Prompt 版本。优化后会把运动提示词和图生视频上下文保存到当前节点。</small>
      )}
      {videoArtifacts.length > 1 ? <small>视频历史版本：{videoArtifacts.length} 个。</small> : null}
```

Change the image history line to use `imageArtifacts`:

```jsx
      {imageArtifacts.length > 1 ? <small>图像历史版本：{imageArtifacts.length} 个，可在后续阶段加入对比和回滚。</small> : null}
```

- [ ] **Step 3: Pass video props from workspace components**

In `CanvasWorkspaceView`, destructure these from `state`:

```js
optimizingVideoPromptNodeId,
videoPromptArtifactId,
```

Change the `StoryboardPromptPanel` render to:

```jsx
<StoryboardPromptPanel
  selectedNode={selectedNode}
  artifacts={promptArtifacts || []}
  optimizingNodeId={optimizingPromptNodeId}
  optimizingVideoNodeId={optimizingVideoPromptNodeId}
  onOptimize={actions.optimizeStoryboardImagePrompt}
  onOptimizeVideo={actions.optimizeStoryboardVideoPrompt}
/>
```

- [ ] **Step 4: Add video optimization button to `VideoFromCandidateDialog`**

Change the function signature:

```js
export function VideoFromCandidateDialog({ candidate, prompt, promptArtifactId, optimizing, creating, onOptimizePrompt, onPromptChange, onClose, onSubmit }) {
```

Add this button before the submit button inside `.canvas-dialog-actions`:

```jsx
          <button className="secondary-image-action" type="button" onClick={onOptimizePrompt} disabled={creating || optimizing}>
            {optimizing ? <Loader2 className="spinning" size={16} /> : <Sparkles size={16} />}
            <span>{promptArtifactId ? "重新优化 Prompt" : "优化视频 Prompt"}</span>
          </button>
```

Add this hint after the textarea label:

```jsx
        {promptArtifactId ? <small>当前将使用已保存的视频 Prompt 版本生成视频。</small> : <small>编辑提示词后会作为手写版本提交，不再绑定已保存版本。</small>}
```

- [ ] **Step 5: Wire dialog props**

Change the `VideoFromCandidateDialog` render in `CanvasWorkspaceView` to:

```jsx
{videoDialogCandidate ? (
  <VideoFromCandidateDialog
    candidate={videoDialogCandidate}
    prompt={videoPrompt}
    promptArtifactId={videoPromptArtifactId}
    optimizing={Boolean(optimizingVideoPromptNodeId)}
    creating={creatingVideo}
    onOptimizePrompt={() => {
      const targetNode = videoDialogCandidate.node_id ? canvas?.nodes?.find((node) => node.id === videoDialogCandidate.node_id) : selectedNode;
      actions.optimizeStoryboardVideoPrompt(targetNode || selectedNode, videoDialogCandidate);
    }}
    onPromptChange={actions.setVideoPrompt}
    onClose={actions.closeVideoDialog}
    onSubmit={actions.createVideoFromCandidate}
  />
) : null}
```

- [ ] **Step 6: Run frontend build**

Run:

```bash
npm run build
```

Expected: PASS.

---

### Task 9: Verification Pass

**Files:**
- Verify: `tests/test_canvas_routes.py`
- Verify: `tests/test_canvas_generation_lineage.py`
- Verify: `tests/test_video_router.py`
- Verify: `tests/test_canvas_video_prompt_optimizer.py`
- Verify: frontend build

- [ ] **Step 1: Run focused Phase 1B tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_video_prompt_optimizer.py tests/test_canvas_routes.py::test_canvas_storyboard_video_prompt_optimization_persists_version tests/test_canvas_routes.py::test_canvas_storyboard_video_prompt_rejects_foreign_candidate tests/test_canvas_routes.py::test_canvas_video_generation_uses_video_prompt_artifact -q
```

Expected: all selected tests PASS.

- [ ] **Step 2: Run canvas and video regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_canvas_routes.py tests/test_canvas_generation_lineage.py tests/test_video_router.py -q
```

Expected: all tests PASS.

- [ ] **Step 3: Run prompt regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_prompt_evaluator.py tests/test_prompt_skill_agent.py tests/test_prompt_spec_compiler.py -q
```

Expected: all tests PASS.

- [ ] **Step 4: Build frontend**

Run:

```bash
npm run build
```

Expected: Vite build PASS.

- [ ] **Step 5: Run full backend suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: full backend suite PASS.

- [ ] **Step 6: Manual browser verification**

Run the app with mock media:

```bash
USE_MOCK_IMAGES=true USE_MOCK_VIDEOS=true AUTH_REQUIRED=false ALLOW_PUBLIC_REGISTRATION=true API_KEY='' SECURE_SESSION_COOKIES=false npm run dev
```

Verify this flow:

1. Register or sign in.
2. Create/open a project.
3. Open a canvas.
4. Create a storyboard node with a Chinese creative brief.
5. Optimize image prompt.
6. Generate image candidates.
7. Select one candidate.
8. Open the image-to-video dialog from the selected candidate.
9. Click “优化视频 Prompt”.
10. Confirm the dialog textarea is filled with the saved motion prompt.
11. Submit “生成视频”.
12. Confirm a generated video node appears and stores the same `motion_prompt`.

Expected: optimized video prompt version appears in the inspector, video generation succeeds in mock mode, and generated video candidate can enter the existing approval/final lineage flow.

---

## Self-Review

### Spec Coverage

- Storyboard-level image-to-video workflow: covered by Tasks 1, 5, 6, 7, and 8.
- Video prompt optimization dimensions: covered by Task 4 helper and Task 2 unit tests.
- Prompt version history per node: covered by Task 5 artifact route and Task 8 inspector display.
- Reuse existing video generation route/router: covered by Task 6, which keeps `/generate/video` and `VideoRouter` as the execution path.
- Project/user isolation: covered by Task 1 foreign candidate test and Task 5 route validation.
- Credits/admin/payment excluded: stated in Scope and not included in tasks.

### Placeholder Scan

No step relies on unspecified implementation details. Every new model, route, helper, frontend helper, and UI action has concrete code snippets and verification commands.

### Type Consistency

- Artifact kind is consistently `storyboard_video_prompt_version`.
- Request class is consistently `CanvasStoryboardVideoPromptRequest`.
- Response class is consistently `CanvasStoryboardVideoPromptResponse`.
- Frontend helper is consistently `optimizeCanvasVideoPrompt`.
- Node payload field for optimized video prompt is consistently `video_prompt_artifact_id`.
- Video generation request field is consistently `prompt_artifact_id`.

### Commit Note

The current workspace at `/Users/apple/Documents/tup` is not a git repository. During execution, do not run commit steps unless the workspace is moved into a git repository. If execution happens in a git repository, create one commit after each approved task with conventional messages such as `feat: add canvas video prompt optimizer` and `test: cover canvas video prompt versions`.
