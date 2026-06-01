from __future__ import annotations

from typing import Any

from src.agents.canvas_graph_compiler import CanvasCompileProduct
from src.models.canvas import CanvasSeriesFrameResponse, CanvasSeriesPlanResponse

MIN_SERIES_FRAMES = 3
MAX_SERIES_FRAMES = 8
SERIES_BEATS = (
    {
        "title": "Hero Establishing Key Visual",
        "beat": "establish the campaign world, hero subject hierarchy, and premium visual promise",
        "camera": "wide-to-medium hero composition with controlled negative space for campaign typography",
    },
    {
        "title": "Identity Continuity Portrait",
        "beat": "prove the same character or product identity under a tighter editorial setup",
        "camera": "medium portrait or three-quarter product angle with face, silhouette, and signature details readable",
    },
    {
        "title": "Material Macro Evidence",
        "beat": "show tactile material, finish, label, fabric, skin, or surface details that make the design believable",
        "camera": "macro close-up with shallow depth of field and precise highlight control",
    },
    {
        "title": "Lifestyle Context Frame",
        "beat": "place the locked identity inside a contextual scene without changing the core anchors",
        "camera": "environmental mid-shot with foreground and background layers supporting the same art direction",
    },
    {
        "title": "Motion and Interaction Beat",
        "beat": "add gesture, motion, or interaction while preserving product geometry and character identity",
        "camera": "dynamic diagonal composition with controlled motion cues and stable brand readability",
    },
    {
        "title": "Composition Variant",
        "beat": "create an alternate layout for social, banner, or editorial use while maintaining the same system",
        "camera": "graphic layout with asymmetry, crop discipline, and clear hierarchy for copy placement",
    },
    {
        "title": "Detail Reinforcement Cut",
        "beat": "reinforce the most recognizable identity anchors and remove ambiguity before final delivery",
        "camera": "tight controlled crop focused on locked anchors and signature design details",
    },
    {
        "title": "Campaign End Card",
        "beat": "resolve the series with a polished commercial end frame and explicit continuity to prior frames",
        "camera": "balanced final composition with strong center of interest and clean space for required text",
    },
)


class CanvasSeriesPlanner:
    def plan(self, compiled: CanvasCompileProduct, frame_count: int | None = None) -> CanvasSeriesPlanResponse:
        count = _frame_count(frame_count)
        graph = compiled.creative_graph
        character_lock = _unique(graph.character_anchors)[:20]
        style_lock = {key: value for key, value in graph.style_system.items() if value}
        reference_policy = _reference_policy(compiled.prompt_spec, graph.references)
        text_literals = _unique(graph.text_literals)[:12]
        frames = [
            _frame_response(
                index=index,
                beat=beat,
                foundation_prompt=compiled.final_prompt,
                primary_brief=graph.primary_brief,
                character_lock=character_lock,
                style_lock=style_lock,
                reference_policy=reference_policy,
                text_literals=text_literals,
                constraints=graph.constraints,
                source_node_ids=[node.id for node in graph.nodes],
            )
            for index, beat in enumerate(SERIES_BEATS[:count], start=1)
        ]
        return CanvasSeriesPlanResponse(
            canvas_id=graph.canvas_id,
            project_id=graph.project_id,
            primary_brief=graph.primary_brief,
            character_lock=character_lock,
            style_lock=style_lock,
            reference_policy=reference_policy,
            text_literals=text_literals,
            frames=frames,
        )


def _frame_response(
    *,
    index: int,
    beat: dict[str, str],
    foundation_prompt: str,
    primary_brief: str,
    character_lock: list[str],
    style_lock: dict[str, str],
    reference_policy: list[str],
    text_literals: list[str],
    constraints: dict[str, list[str]],
    source_node_ids: list[str],
) -> CanvasSeriesFrameResponse:
    continuity = _continuity(character_lock, style_lock, reference_policy, text_literals)
    prompt = _frame_prompt(
        index=index,
        beat=beat,
        foundation_prompt=foundation_prompt,
        primary_brief=primary_brief,
        character_lock=character_lock,
        style_lock=style_lock,
        reference_policy=reference_policy,
        text_literals=text_literals,
        constraints=constraints,
    )
    return CanvasSeriesFrameResponse(
        index=index,
        title=f"{index:02d} · {beat['title']}",
        beat=beat["beat"],
        camera=beat["camera"],
        prompt=prompt,
        continuity=continuity,
        source_node_ids=source_node_ids,
    )


def _frame_prompt(
    *,
    index: int,
    beat: dict[str, str],
    foundation_prompt: str,
    primary_brief: str,
    character_lock: list[str],
    style_lock: dict[str, str],
    reference_policy: list[str],
    text_literals: list[str],
    constraints: dict[str, list[str]],
) -> str:
    sections = [
        f"Series frame {index}: {beat['title']}",
        f"Base production brief: {primary_brief}",
        f"Frame intent: {beat['beat']}",
        f"Camera and composition: {beat['camera']}",
        f"Production prompt foundation: {foundation_prompt}",
    ]
    if character_lock:
        sections.append("Character lock: " + "; ".join(character_lock))
    if style_lock:
        sections.append("Style lock: " + "; ".join(f"{key}={value}" for key, value in style_lock.items()))
    if reference_policy:
        sections.append("Reference policy: " + "; ".join(reference_policy))
    if text_literals:
        sections.append("Required text literals: " + "; ".join(f'"{item}"' for item in text_literals))
    if constraints.get("preserve"):
        sections.append("Preserve across series: " + "; ".join(constraints["preserve"][:12]))
    if constraints.get("avoid"):
        sections.append("Avoid: " + "; ".join(constraints["avoid"][:12]))
    sections.append("Series continuity rule: change only scene beat, pose, crop, and layout; keep locked identity, style system, reference roles, and required text stable.")
    return "\n".join(sections)[:6000]


def _continuity(character_lock: list[str], style_lock: dict[str, str], reference_policy: list[str], text_literals: list[str]) -> list[str]:
    items = []
    if character_lock:
        items.append("character identity: " + "; ".join(character_lock))
    if style_lock:
        items.append("style system: " + "; ".join(f"{key}={value}" for key, value in style_lock.items()))
    if reference_policy:
        items.append("reference roles: " + "; ".join(reference_policy[:8]))
    if text_literals:
        items.append("required text: " + "; ".join(text_literals))
    return items[:8]


def _reference_policy(prompt_spec: dict[str, Any], references: list[dict[str, Any]]) -> list[str]:
    scene_graph = prompt_spec.get("scene_graph")
    if isinstance(scene_graph, dict):
        policy = scene_graph.get("reference_image_policy")
        if isinstance(policy, list):
            return [item for item in policy if isinstance(item, str) and item.strip()][:8]
    return [_reference_line(reference) for reference in references[:8]]


def _reference_line(reference: dict[str, Any]) -> str:
    label = f"@{reference['mention_label']}" if reference.get("mention_label") else str(reference.get("asset_id") or "reference")
    role = str(reference.get("role") or "reference_image")
    instruction = str(reference.get("instruction") or "use as a bounded visual reference without copying artifacts")
    strength = reference.get("influence_strength")
    suffix = f" influence={strength}" if strength is not None else ""
    return f"{label} as {role}: {instruction}{suffix}"


def _frame_count(value: int | None) -> int:
    if type(value) is not int:
        return 4
    return min(MAX_SERIES_FRAMES, max(MIN_SERIES_FRAMES, value))


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
