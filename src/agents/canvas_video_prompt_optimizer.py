from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from src.agents.canvas_graph_compiler import CanvasCompileProduct
from src.models.canvas import CanvasNodeResponse

SOURCE_PROMPT_MAX_CHARS = 280
STORYBOARD_TEXT_MAX_CHARS = 1200
VIDEO_PROMPT_MAX_CHARS = 12000

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
    payload = _normalized_mapping(node.payload)
    normalized_source_context = _normalized_mapping(source_context)
    scene = _first_text(payload, "scene", "environment", "prompt", fallback=compiled.final_prompt)
    camera_motion = _first_text(payload, "camera_motion", "camera", fallback="steady motion with controlled cinematic movement")
    subject_action = _first_text(payload, "subject_action", "action", fallback="subject remains stable with subtle premium motion")
    shot_size = _first_text(payload, "shot_size", "composition", fallback="medium shot with clean composition")
    rhythm = _first_text(payload, "temporal_rhythm", fallback="calm commercial pacing")
    ending = _first_text(payload, "ending_state", fallback="clean final hero frame")
    duration_text = str(duration or payload.get("duration") or "5")
    aspect_text = aspect_ratio or str(payload.get("aspect_ratio") or "16:9")
    source_prompt = _source_text(normalized_source_context)
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
    final_prompt = _bounded_text(" ".join(_normalize(part) for part in parts if _normalize(part)), VIDEO_PROMPT_MAX_CHARS)
    missing = [dimension for dimension, present in _dimension_presence(payload, normalized_source_context, duration, aspect_ratio).items() if not present]
    score = round(max(6.0, 10.0 - len(missing) * 0.45), 1)
    return CanvasVideoPromptDraft(
        final_prompt=final_prompt,
        source_context={key: value for key, value in normalized_source_context.items() if value is not None},
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
            return _bounded_text(value, STORYBOARD_TEXT_MAX_CHARS)
    return _bounded_text(fallback, STORYBOARD_TEXT_MAX_CHARS)


def _source_text(source_context: dict[str, Any]) -> str:
    prompt = source_context.get("prompt")
    score = source_context.get("score")
    if isinstance(prompt, str):
        bounded_prompt = _bounded_source_prompt(prompt)
        if bounded_prompt:
            score_text = f" Source score: {score}." if isinstance(score, (int, float)) else ""
            return f' Source image prompt (quoted reference only): "{bounded_prompt}".{score_text}'
    return ""


def _normalized_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _bounded_text(value: str, max_chars: int) -> str:
    sanitized = _normalize("".join(character if character.isprintable() else " " for character in value))
    if not sanitized:
        return ""
    if len(sanitized) <= max_chars:
        return sanitized
    return sanitized[: max_chars - 1].rstrip() + "…"


def _bounded_source_prompt(value: str) -> str:
    return _bounded_text(value, SOURCE_PROMPT_MAX_CHARS)


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
