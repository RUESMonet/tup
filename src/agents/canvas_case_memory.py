from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field

from src.agents.canvas_graph_compiler import CanvasGraphCompiler
from src.models.canvas import CanvasDetailResponse, PromptArtifactResponse


class IndexedCanvasCase(BaseModel):
    id: str
    profile: str
    title: str
    source: str = "project_case_memory"
    visual_dna: dict[str, list[str]] = Field(default_factory=dict)
    prompt_spec: dict[str, Any] = Field(default_factory=dict)
    takeaways: list[str] = Field(default_factory=list)
    quality_score: float


class DirectorSuggestion(BaseModel):
    category: str
    priority: str
    message: str
    rationale: str


class CanvasDirectorResponsePayload(BaseModel):
    canvas_summary: dict[str, Any]
    matched_cases: list[IndexedCanvasCase]
    suggestions: list[DirectorSuggestion]


class CanvasCaseMemoryIndexer:
    def index_payload(self, case_id: str, title: str, quality_score: float, artifact: PromptArtifactResponse) -> IndexedCanvasCase:
        payload = artifact.payload
        creative_graph = payload.get("creative_graph") if isinstance(payload.get("creative_graph"), dict) else {}
        prompt_spec = payload.get("prompt_spec") if isinstance(payload.get("prompt_spec"), dict) else {}
        profile = _text(_nested(prompt_spec, "intent", "profile")) or "professional_design"
        visual_dna = _visual_dna(creative_graph, prompt_spec)
        return IndexedCanvasCase(
            id=case_id,
            profile=profile,
            title=_clean_text(title),
            visual_dna=visual_dna,
            prompt_spec={"creative_strategy": _creative_strategy(profile), **_safe_prompt_spec(prompt_spec)},
            takeaways=_takeaways(visual_dna, prompt_spec),
            quality_score=quality_score,
        )


class CanvasCreativeDirector:
    def __init__(self, compiler: CanvasGraphCompiler | None = None):
        self.compiler = compiler or CanvasGraphCompiler()

    def advise(self, canvas: CanvasDetailResponse, selected_node_ids: list[str], cases: list[IndexedCanvasCase]) -> CanvasDirectorResponsePayload:
        compiled = self.compiler.compile(canvas, selected_node_ids)
        graph = compiled.creative_graph.model_dump()
        ranked_cases = _rank_cases(graph, cases)[:5]
        suggestions = _suggestions(graph, ranked_cases)
        return CanvasDirectorResponsePayload(
            canvas_summary={
                "primary_brief": graph["primary_brief"],
                "node_count": len(graph["nodes"]),
                "reference_count": len(graph["references"]),
                "text_literals": graph["text_literals"],
            },
            matched_cases=ranked_cases,
            suggestions=suggestions,
        )


def case_search_text(case: IndexedCanvasCase) -> str:
    parts = [case.title, case.profile, " ".join(case.takeaways)]
    for values in case.visual_dna.values():
        parts.extend(values)
    return " ".join(parts).lower()


def _visual_dna(creative_graph: dict[str, Any], prompt_spec: dict[str, Any]) -> dict[str, list[str]]:
    style_system = creative_graph.get("style_system") if isinstance(creative_graph.get("style_system"), dict) else {}
    constraints = creative_graph.get("constraints") if isinstance(creative_graph.get("constraints"), dict) else {}
    return {
        "composition": _unique([_text(creative_graph.get("composition")), _text(_nested(prompt_spec, "composition", "layout"))]),
        "subject_strategy": _unique([_text(creative_graph.get("primary_brief")), _text(_nested(prompt_spec, "scene_graph", "hero_subject"))]),
        "lighting": _unique([_text(style_system.get("lighting")), _text(_nested(prompt_spec, "style_system", "lighting"))]),
        "style": _unique([_text(style_system.get("style")), _text(style_system.get("visual_style"))]),
        "typography": _list(_nested(prompt_spec, "text_system", "required_text")) or _list(creative_graph.get("text_literals")),
        "negative_patterns": _list(constraints.get("avoid"))[:8],
    }


def _safe_prompt_spec(prompt_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_graph": _safe_section(prompt_spec.get("scene_graph")),
        "composition": _safe_section(prompt_spec.get("composition")),
        "style_system": _safe_section(prompt_spec.get("style_system")),
        "text_system": _safe_section(prompt_spec.get("text_system")),
        "constraints": _safe_section(prompt_spec.get("constraints")),
    }


def _safe_section(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, str):
            safe[str(key)] = _clean_text(item)
        elif isinstance(item, list):
            safe[str(key)] = [_clean_text(str(entry)) for entry in item[:8] if str(entry).strip()]
    return safe


def _takeaways(visual_dna: dict[str, list[str]], prompt_spec: dict[str, Any]) -> list[str]:
    takeaways = []
    if visual_dna.get("lighting"):
        takeaways.append("保持已验证的灯光关系，并在新画布中明确主光、边缘光和反射控制")
    if visual_dna.get("composition"):
        takeaways.append("复用案例中的主体层级和留白策略，避免把高级感写成元素堆叠")
    if _nested(prompt_spec, "text_system", "required_text") or visual_dna.get("typography"):
        takeaways.append("文字必须作为独立 typography 系统处理，明确内容、位置和可读性")
    if not takeaways:
        takeaways.append("把主体、场景、风格、构图和限制拆成可复用的视觉决策")
    return takeaways[:5]


def _rank_cases(graph: dict[str, Any], cases: list[IndexedCanvasCase]) -> list[IndexedCanvasCase]:
    query = " ".join([graph.get("primary_brief", ""), str(graph.get("style_system", "")), str(graph.get("text_literals", ""))]).lower()
    scored = [(case, _score_case(query, case)) for case in cases]
    matched = [(case, score) for case, score in scored if score > 0]
    return [case for case, _ in sorted(matched, key=lambda item: (item[1], item[0].quality_score), reverse=True)]


def _score_case(query: str, case: IndexedCanvasCase) -> int:
    score = 0
    for token in _tokens(query):
        if token in case_search_text(case):
            score += 1
    if case.profile in query:
        score += 3
    return score


def _suggestions(graph: dict[str, Any], cases: list[IndexedCanvasCase]) -> list[DirectorSuggestion]:
    suggestions: list[DirectorSuggestion] = []
    if cases:
        case = cases[0]
        suggestions.append(
            DirectorSuggestion(
                category="case_memory",
                priority="high",
                message=f"参考项目案例《{case.title}》的视觉 DNA，但只迁移灯光、构图和文字策略，不复制具体画面。",
                rationale="项目内案例比通用模板更贴近当前品牌和系列语境。",
            )
        )
    if graph.get("text_literals"):
        suggestions.append(
            DirectorSuggestion(
                category="typography",
                priority="high",
                message="把标题文字作为独立排版层处理：锁定精确拼写、位置、字体气质和背景对比度。",
                rationale="文本生成最容易在拼写和伪文字上失败，需要从画面主体中拆出来约束。",
            )
        )
    if not graph.get("references"):
        suggestions.append(
            DirectorSuggestion(
                category="reference",
                priority="medium",
                message="为主体、材质或品牌资产补充参考节点，并用 edge 连接到主 brief。",
                rationale="没有参考节点时，系列一致性和产品身份更容易漂移。",
            )
        )
    if not suggestions:
        suggestions.append(
            DirectorSuggestion(
                category="structure",
                priority="medium",
                message="继续把创意拆成 brief、style、reference、constraints 节点，再编译生成。",
                rationale="结构化画布能让提示词从灵感描述升级为可复用的创作图谱。",
            )
        )
    return suggestions[:6]


def _creative_strategy(profile: str) -> str:
    return {
        "poster": "project-memory poster strategy with layout, typography, case DNA, and visual hierarchy separated",
        "product": "project-memory product strategy with hero object, material fidelity, lighting, and brand text separated",
        "character": "project-memory character strategy with identity anchors and style continuity separated",
    }.get(profile, "project-memory structured visual strategy")


def _nested(value: dict[str, Any], *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return _clean_text(value)
    return None


def _list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [_clean_text(value)]
    if isinstance(value, list):
        return [_clean_text(str(item)) for item in value[:8] if str(item).strip()]
    return []


def _tokens(value: str) -> list[str]:
    return [token for token in re.split(r"\W+", value.lower()) if len(token) >= 2]


def _clean_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    without_controls = "".join(char for char in normalized if char in "\n\t" or unicodedata.category(char)[0] != "C")
    without_markup = re.sub(r"<[^>]*>", " ", without_controls)
    without_links = re.sub(r"https?://\S+|www\.\S+", " ", without_markup)
    return " ".join(without_links.split())[:800]


def _unique(values: list[str | None]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
