from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field

from src.agents.prompt_case_library import retrieve_prompt_cases_sync
from src.agents.prompt_spec_compiler import PromptSpecCompiler
from src.models.canvas import CanvasDetailResponse, CanvasEdgeResponse, CanvasNodeResponse
from src.models.prompt_skill import ImageActionType, ImageSource, PromptIntent, PromptSkillRequest

MAX_TEXT_LENGTH = 800
MAX_LIST_ITEMS = 12
MAX_REFERENCES = 8
MENTION_LABEL_RE = re.compile(r"^[a-z0-9一-龥-]{1,32}$")
PROMPT_MENTION_RE = re.compile(r"(?<![\w.-])@([a-z0-9一-龥-]{1,32})(?![\w.-])")
PROMPT_MENTION_FIELDS = ("prompt", "brief", "instruction", "scene")
REFERENCE_ROLE_ALIASES = {
    "product": "product_reference",
    "product_reference": "product_reference",
    "product_identity_reference": "product_reference",
    "style": "style_reference",
    "style_reference": "style_reference",
    "style_identity_reference": "style_reference",
    "character": "character_reference",
    "character_reference": "character_reference",
    "composition": "composition_reference",
    "composition_reference": "composition_reference",
    "layout_reference": "composition_reference",
    "source": "source_image",
    "source_image": "source_image",
    "reference": "reference_image",
    "reference_image": "reference_image",
    "motion": "motion_reference",
    "motion_reference": "motion_reference",
    "timing": "timing_reference",
    "timing_reference": "timing_reference",
    "video": "video_reference",
    "video_reference": "video_reference",
}
SAFE_PAYLOAD_KEYS = {
    "asset_id",
    "asset_kind",
    "aspect_ratio",
    "atmosphere",
    "avoid",
    "brief",
    "camera",
    "camera_and_composition",
    "camera_block",
    "can_change",
    "character_anchors",
    "color_palette",
    "composition",
    "composition_block",
    "constraints",
    "defects",
    "dimensions",
    "duration",
    "environment",
    "frame_index",
    "goal",
    "identity_anchors",
    "instruction",
    "lighting",
    "lighting_block",
    "manifest_sections",
    "media_type",
    "mention_label",
    "motion_prompt",
    "must_keep",
    "negative_constraints",
    "negative_prompt",
    "optimization_prompt",
    "preserve",
    "preserve_directives",
    "plan_profile",
    "profile",
    "prompt",
    "provenance",
    "reference_instruction",
    "reference_role",
    "referenced_asset_ids",
    "referenced_asset_mentions",
    "influence_strength",
    "repair_targets",
    "required_text",
    "role",
    "scene",
    "scene_block",
    "scene_constraints",
    "setting",
    "source_canvas_id",
    "source_node_ids",
    "source_project_id",
    "status",
    "style",
    "subject",
    "subject_block",
    "target_profile",
    "target_score",
    "text_literals",
    "visual_style",
    "workflow",
}


class CreativeGraphNode(BaseModel):
    id: str
    type: str
    title: str
    position: dict[str, float]
    payload: dict[str, Any] = Field(default_factory=dict)


class CreativeGraphEdge(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CreativeGraph(BaseModel):
    canvas_id: str
    project_id: str
    primary_brief: str
    nodes: list[CreativeGraphNode]
    edges: list[CreativeGraphEdge]
    style_system: dict[str, str] = Field(default_factory=dict)
    composition: str | None = None
    constraints: dict[str, list[str]] = Field(default_factory=dict)
    references: list[dict[str, Any]] = Field(default_factory=list)
    text_literals: list[str] = Field(default_factory=list)
    character_anchors: list[str] = Field(default_factory=list)
    semantic_flow: list[dict[str, str]] = Field(default_factory=list)


class CanvasCompileProduct(BaseModel):
    creative_graph: CreativeGraph
    prompt_spec: dict[str, Any]
    final_prompt: str

    def artifact_payload(self, selected_node_ids: list[str]) -> dict[str, Any]:
        return {
            "selected_node_ids": selected_node_ids,
            "creative_graph": self.creative_graph.model_dump(),
            "prompt_spec": self.prompt_spec,
            "final_prompt": self.final_prompt,
        }


class CanvasGraphCompiler:
    def __init__(self, prompt_compiler: PromptSpecCompiler | None = None):
        self.prompt_compiler = prompt_compiler or PromptSpecCompiler()

    def compile(
        self,
        canvas: CanvasDetailResponse,
        selected_node_ids: list[str],
        profile: str | None = None,
        root_node_id: str | None = None,
    ) -> CanvasCompileProduct:
        selected_ids = set(selected_node_ids)
        selected_edges = [edge for edge in canvas.edges if edge.source_node_id in selected_ids and edge.target_node_id in selected_ids]
        selected_nodes = _ordered_nodes(canvas.nodes, selected_ids, selected_edges, root_node_id)
        _validate_prompt_mentions(selected_nodes)
        _validate_reference_count(selected_nodes)
        creative_graph = _creative_graph(canvas, selected_nodes, selected_edges)
        prompt_payload = _prompt_payload(selected_nodes, creative_graph)
        request = PromptSkillRequest(
            prompt=creative_graph.primary_brief,
            source_images=_source_images(selected_nodes),
            character_anchors=_character_anchors(selected_nodes),
            defects=_defects(selected_nodes),
        )
        intent = PromptIntent(
            action_type=ImageActionType.TEXT_AND_IMAGE_TO_IMAGE if request.source_images else ImageActionType.TEXT_TO_IMAGE,
            profile=profile or _profile(selected_nodes),
            confidence=0.86,
            needs_text_rendering=bool(creative_graph.text_literals),
            detected_text_literals=creative_graph.text_literals,
            needs_character_consistency=bool(request.character_anchors),
            character_anchors=request.character_anchors,
            source_image_count=len(request.source_images),
            avoid_directives=_avoid_directives(selected_nodes),
            preserve_directives=_preserve_directives(selected_nodes),
        )
        cases = retrieve_prompt_cases_sync(_case_query(creative_graph, prompt_payload), limit=5, task_type=intent.action_type.value)
        spec = self.prompt_compiler.compile(request, intent, cases, {"prompt": prompt_payload})
        return CanvasCompileProduct(creative_graph=creative_graph, prompt_spec=spec.as_payload(), final_prompt=self.prompt_compiler.final_prompt(spec))


def _ordered_nodes(
    canvas_nodes: list[CanvasNodeResponse],
    selected_ids: set[str],
    selected_edges: list[CanvasEdgeResponse],
    root_node_id: str | None,
) -> list[CanvasNodeResponse]:
    canvas_order = {node.id: index for index, node in enumerate(canvas_nodes)}
    selected_by_id = {node.id: node for node in canvas_nodes if node.id in selected_ids}
    if not selected_by_id:
        return []
    root_id = root_node_id if root_node_id in selected_by_id else min(selected_by_id, key=lambda item: canvas_order[item])
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in selected_by_id}
    for edge in selected_edges:
        adjacency.setdefault(edge.source_node_id, []).append(edge.target_node_id)
    ordered_ids: list[str] = []
    queue = [root_id]
    seen = set()
    while queue:
        node_id = queue.pop(0)
        if node_id in seen or node_id not in selected_by_id:
            continue
        seen.add(node_id)
        ordered_ids.append(node_id)
        neighbors = sorted(adjacency.get(node_id, []), key=lambda item: canvas_order.get(item, 0))
        queue.extend(neighbor for neighbor in neighbors if neighbor not in seen)
    ordered_ids.extend(node.id for node in canvas_nodes if node.id in selected_by_id and node.id not in seen)
    return [selected_by_id[node_id] for node_id in ordered_ids]


def _creative_graph(canvas: CanvasDetailResponse, nodes: list[CanvasNodeResponse], edges: list[CanvasEdgeResponse]) -> CreativeGraph:
    primary_brief = _primary_brief(nodes)
    return CreativeGraph(
        canvas_id=canvas.id,
        project_id=canvas.project_id,
        primary_brief=primary_brief,
        nodes=[_node_payload(node) for node in nodes],
        edges=[_edge_payload(edge) for edge in edges],
        style_system=_style_system(nodes),
        composition=_first_payload_value(nodes, ("camera_and_composition", "composition", "camera")),
        constraints=_constraints(nodes),
        references=_references(nodes),
        text_literals=_text_literals(primary_brief, nodes),
        character_anchors=_character_anchors(nodes),
        semantic_flow=[{"source_node_id": edge.source_node_id, "target_node_id": edge.target_node_id, "type": edge.type} for edge in edges],
    )


def _node_payload(node: CanvasNodeResponse) -> CreativeGraphNode:
    return CreativeGraphNode(
        id=node.id,
        type=node.type,
        title=_clean_text(node.title),
        position=node.position.model_dump(),
        payload=_safe_payload(node.payload),
    )


def _edge_payload(edge: CanvasEdgeResponse) -> CreativeGraphEdge:
    return CreativeGraphEdge(
        id=edge.id,
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        type=_clean_text(edge.type),
        payload=_safe_payload(edge.payload),
    )


def _case_query(graph: CreativeGraph, prompt_payload: dict[str, Any]) -> str:
    parts: list[str] = [graph.primary_brief, graph.composition or ""]
    parts.extend(str(value) for key, value in prompt_payload.items() if key != "semantic_spec" and isinstance(value, str) and value)
    parts.extend(str(item) for item in graph.text_literals)
    parts.extend(str(item) for item in graph.character_anchors)
    parts.extend(str(reference.get("role") or "") for reference in graph.references)
    return " ".join(part for part in parts if part)[:2400]


def _prompt_payload(nodes: list[CanvasNodeResponse], graph: CreativeGraph) -> dict[str, Any]:
    style = graph.style_system
    semantic_spec = _semantic_spec_payload(nodes)
    prompt_program = _prompt_program_payload(nodes)
    return {
        "subject": _join_prompt_parts(graph.primary_brief, prompt_program.get("subject_block"), semantic_spec.get("subject")),
        "environment": _join_prompt_parts(prompt_program.get("scene_block"), semantic_spec.get("scene"), _first_payload_value(nodes, ("environment", "scene", "setting"))),
        "camera_and_composition": _join_prompt_parts(prompt_program.get("composition_block"), prompt_program.get("camera_block"), semantic_spec.get("composition"), graph.composition),
        "lighting": _join_prompt_parts(prompt_program.get("lighting_block"), semantic_spec.get("lighting"), style.get("lighting")),
        "style": _join_prompt_parts(semantic_spec.get("visual_style"), style.get("style"), style.get("visual_style")),
        "color_palette": style.get("color_palette"),
        "atmosphere": style.get("atmosphere"),
        "scene_constraints": _unique([*graph.constraints.get("scene_constraints", []), *(_list_value(prompt_program.get("optimization_prompt")))]),
        "negative_prompt": _unique([*graph.constraints.get("avoid", []), *(_list_value(prompt_program.get("negative_prompt"))), *(_list_value(semantic_spec.get("negative_constraints")))]),
        "reference_image_policy": _reference_image_policy(graph.references),
        "semantic_spec": semantic_spec,
        "prompt_program": prompt_program,
    }


def _join_prompt_parts(*parts: Any) -> str | None:
    values = _unique([_clean_text(str(part)) for part in parts if part])
    return "; ".join(values)[:MAX_TEXT_LENGTH] if values else None


def _list_value(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [_clean_text(value)]
    if isinstance(value, list):
        return [_clean_text(str(item)) for item in value[:MAX_LIST_ITEMS] if str(item).strip()]
    return []


def _semantic_spec_payload(nodes: list[CanvasNodeResponse]) -> dict[str, Any]:
    keys = ("goal", "subject", "scene", "composition", "lighting", "visual_style")
    payload: dict[str, Any] = {key: value for key in keys if (value := _first_payload_value([node for node in nodes if node.type == "semantic_spec"], (key,)))}
    semantic_nodes = [node for node in nodes if node.type == "semantic_spec"]
    for key in ("must_keep", "can_change", "negative_constraints"):
        values = _payload_list_values(semantic_nodes, (key,))
        if values:
            payload[key] = values[:MAX_LIST_ITEMS]
    return payload


def _prompt_program_payload(nodes: list[CanvasNodeResponse]) -> dict[str, Any]:
    prompt_nodes = [node for node in nodes if node.type == "prompt_program"]
    keys = ("subject_block", "scene_block", "composition_block", "lighting_block", "camera_block", "negative_prompt", "optimization_prompt")
    return {key: value for key in keys if (value := _first_payload_value(prompt_nodes, (key,)))}


def _primary_brief(nodes: list[CanvasNodeResponse]) -> str:
    for node in nodes:
        if node.type == "brief":
            prompt = _payload_text(node.payload, ("prompt", "brief", "instruction"))
            if prompt:
                return prompt
    for node in nodes:
        prompt = _payload_text(node.payload, ("prompt", "brief", "instruction"))
        if prompt:
            return prompt
    fallback = "; ".join(_clean_text(node.title) for node in nodes if node.title).strip()
    return fallback or "Professional image production brief"


def _style_system(nodes: list[CanvasNodeResponse]) -> dict[str, str]:
    fields = ("lighting", "style", "visual_style", "color_palette", "atmosphere")
    values: dict[str, str] = {}
    for field in fields:
        value = _first_payload_value(nodes, (field,))
        if value:
            values[field] = value
    return values


def _constraints(nodes: list[CanvasNodeResponse]) -> dict[str, list[str]]:
    return {
        "avoid": _unique([*_payload_list_values(nodes, ("negative_prompt", "avoid", "negative_constraints"))]),
        "preserve": _unique([*_payload_list_values(nodes, ("preserve", "preserve_directives", "must_keep"))]),
        "scene_constraints": _unique([*_payload_list_values(nodes, ("scene_constraints", "constraints", "can_change"))]),
    }


def _validate_prompt_mentions(nodes: list[CanvasNodeResponse]) -> None:
    selected_mentions: dict[str, str] = {}
    for node in nodes:
        asset_id = _payload_text(node.payload, ("asset_id",))
        mention_label = _mention_label(node.payload)
        if not asset_id or not mention_label:
            continue
        if mention_label in selected_mentions:
            raise ValueError(f"Duplicate canvas asset mention label: @{mention_label}")
        selected_mentions[mention_label] = node.id

    unresolved = sorted(_prompt_mentions(nodes) - set(selected_mentions))
    if unresolved:
        raise ValueError(f"Unresolved canvas asset mention: @{unresolved[0]}")


def _prompt_mentions(nodes: list[CanvasNodeResponse]) -> set[str]:
    mentions: set[str] = set()
    for node in nodes:
        for field in PROMPT_MENTION_FIELDS:
            value = node.payload.get(field)
            if isinstance(value, str):
                mentions.update(match.group(1) for match in PROMPT_MENTION_RE.finditer(_clean_text(value)))
    return mentions


def _validate_reference_count(nodes: list[CanvasNodeResponse]) -> None:
    reference_count = sum(1 for node in nodes if _payload_text(node.payload, ("asset_id",)))
    if reference_count > MAX_REFERENCES:
        raise ValueError(f"Canvas references cannot exceed {MAX_REFERENCES}")


def _references(nodes: list[CanvasNodeResponse]) -> list[dict[str, Any]]:
    references = []
    for node in nodes:
        asset_id = _payload_text(node.payload, ("asset_id",))
        if asset_id:
            media_type = _payload_text(node.payload, ("media_type",)) or ""
            reference = {
                "node_id": node.id,
                "asset_id": asset_id,
                "role": _reference_role(node.payload),
                "media_type": media_type,
                "asset_kind": _asset_kind(node.payload, media_type),
            }
            mention_label = _mention_label(node.payload)
            instruction = _payload_text(node.payload, ("reference_instruction",))
            influence_strength = _influence_strength(node.payload.get("influence_strength"))
            if mention_label:
                reference["mention_label"] = mention_label
            if instruction:
                reference["instruction"] = instruction
            if influence_strength is not None:
                reference["influence_strength"] = influence_strength
            references.append(reference)
    return references[:MAX_REFERENCES]


def _source_images(nodes: list[CanvasNodeResponse]) -> list[ImageSource]:
    return [
        ImageSource(
            asset_id=reference["asset_id"],
            media_type=reference["media_type"] or None,
            role=reference["role"],
            metadata={key: reference[key] for key in ("node_id", "mention_label", "instruction", "influence_strength") if key in reference},
        )
        for reference in _references(nodes)
        if reference["asset_kind"] == "image"
    ]


def _reference_image_policy(references: list[dict[str, Any]]) -> list[str]:
    policy = []
    for reference in references[:MAX_REFERENCES]:
        label = f"@{reference['mention_label']}" if reference.get("mention_label") else reference["asset_id"]
        role = reference["role"]
        media_instruction = "use for motion/timing/camera/editing reference; do not treat as a source image"
        default_instruction = media_instruction if reference.get("asset_kind") == "video" else "use as a bounded visual reference without copying artifacts"
        instruction = reference.get("instruction") or default_instruction
        if reference.get("asset_kind") == "video" and media_instruction not in instruction:
            instruction = f"{instruction}; {media_instruction}"
        strength = reference.get("influence_strength")
        suffix = f" influence={strength}" if strength is not None else ""
        policy.append(f"{label} as {role}: {instruction}{suffix}")
    return policy


def _reference_role(payload: dict[str, Any]) -> str:
    raw_role = _payload_text(payload, ("reference_role", "role")) or "reference_image"
    return REFERENCE_ROLE_ALIASES.get(raw_role.lower().replace(" ", "_"), "reference_image")


def _asset_kind(payload: dict[str, Any], media_type: str) -> str:
    raw_kind = _payload_text(payload, ("asset_kind",))
    if raw_kind in {"image", "video"}:
        return raw_kind
    if media_type.startswith("video/"):
        return "video"
    return "image"


def _mention_label(payload: dict[str, Any]) -> str | None:
    label = _payload_text(payload, ("mention_label",))
    if label and MENTION_LABEL_RE.fullmatch(label):
        return label
    return None


def _influence_strength(value: Any) -> float | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    return max(0.0, min(1.0, float(value)))


def _profile(nodes: list[CanvasNodeResponse]) -> str:
    return _first_payload_value(nodes, ("profile", "target_profile")) or "professional_design"


def _character_anchors(nodes: list[CanvasNodeResponse]) -> list[str]:
    return _unique(_payload_list_values(nodes, ("character_anchors", "identity_anchors")))[:40]


def _defects(nodes: list[CanvasNodeResponse]) -> list[str]:
    return _unique(_payload_list_values(nodes, ("defects", "repair_targets")))[:20]


def _avoid_directives(nodes: list[CanvasNodeResponse]) -> list[str]:
    return _constraints(nodes)["avoid"]


def _preserve_directives(nodes: list[CanvasNodeResponse]) -> list[str]:
    return _constraints(nodes)["preserve"]


def _text_literals(primary_brief: str, nodes: list[CanvasNodeResponse]) -> list[str]:
    explicit = _payload_list_values(nodes, ("text_literals", "required_text"))
    quoted = []
    parts = primary_brief.split('"')
    for index, part in enumerate(parts):
        if index % 2 == 1 and part.strip():
            quoted.append(_clean_text(part))
    return _unique([*explicit, *quoted])[:MAX_LIST_ITEMS]


def _first_payload_value(nodes: list[CanvasNodeResponse], keys: tuple[str, ...]) -> str | None:
    for node in nodes:
        value = _payload_text(node.payload, keys)
        if value:
            return value
    return None


def _payload_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _clean_text(value)
    return None


def _payload_list_values(nodes: list[CanvasNodeResponse], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for node in nodes:
        for key in keys:
            value = node.payload.get(key)
            if isinstance(value, str) and value.strip():
                values.append(_clean_text(value))
            if isinstance(value, list):
                values.extend(_clean_text(str(item)) for item in value[:MAX_LIST_ITEMS] if str(item).strip())
    return values


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in SAFE_PAYLOAD_KEYS:
            continue
        normalized = _safe_value(value)
        if normalized not in (None, "", []):
            safe[key] = normalized
    return safe


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, list):
        return [_clean_text(str(item)) for item in value[:MAX_LIST_ITEMS] if str(item).strip()]
    if isinstance(value, int | float | bool):
        return value
    return None


def _clean_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    without_controls = "".join(char for char in normalized if char in "\n\t" or unicodedata.category(char)[0] != "C")
    collapsed = " ".join(without_controls.split())
    return collapsed[:MAX_TEXT_LENGTH]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
