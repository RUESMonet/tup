from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.agents.text_rendering_rules import TextRenderingRules
from src.models.prompt_skill import ImageActionType, PromptIntent, PromptSkillRequest


@dataclass(frozen=True)
class CreativeBrief:
    user_prompt: str
    action_type: ImageActionType
    profile: str
    source_image_count: int
    defects: tuple[str, ...] = ()
    character_anchors: tuple[str, ...] = ()


@dataclass(frozen=True)
class PromptSpec:
    intent: dict[str, Any]
    creative_direction: dict[str, Any]
    case_strategy: dict[str, Any]
    scene_graph: dict[str, Any]
    composition: dict[str, Any]
    style_system: dict[str, Any]
    text_system: dict[str, Any]
    edit_operation: dict[str, Any]
    character_identity: dict[str, Any]
    constraints: dict[str, Any]
    generation_plan: dict[str, Any]
    final_prompt_sections: tuple[str, ...] = field(default_factory=tuple)

    def as_payload(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "creative_direction": self.creative_direction,
            "case_strategy": self.case_strategy,
            "scene_graph": self.scene_graph,
            "composition": self.composition,
            "style_system": self.style_system,
            "text_system": self.text_system,
            "edit_operation": self.edit_operation,
            "character_identity": self.character_identity,
            "constraints": self.constraints,
            "generation_plan": self.generation_plan,
            "final_prompt_sections": list(self.final_prompt_sections),
        }


class PromptSpecCompiler:
    def compile(
        self,
        request: PromptSkillRequest,
        intent: PromptIntent,
        cases: list[dict[str, Any]],
        base_payload: dict[str, Any],
    ) -> PromptSpec:
        brief = CreativeBrief(
            user_prompt=request.prompt,
            action_type=intent.action_type,
            profile=intent.profile,
            source_image_count=len(request.source_images),
            defects=tuple(request.defects),
            character_anchors=tuple(request.character_anchors),
        )
        selected_strategies = self._selected_strategies(cases)
        prompt_payload = base_payload.get("prompt") if isinstance(base_payload.get("prompt"), dict) else {}
        text_literals = _unique([*TextRenderingRules.extract_text_literals(request.prompt), *intent.detected_text_literals])
        return PromptSpec(
            intent=self._intent_payload(brief, intent),
            creative_direction=self._creative_direction(brief, prompt_payload, cases),
            case_strategy=selected_strategies,
            scene_graph=self._scene_graph(brief, prompt_payload, cases),
            composition=self._composition(prompt_payload, cases),
            style_system=self._style_system(prompt_payload, cases),
            text_system=self._text_system(intent, text_literals, cases),
            edit_operation=self._edit_operation(intent, request.mask_image is not None),
            character_identity=self._character_identity(intent, request),
            constraints=self._constraints(intent, prompt_payload, brief.defects, cases),
            generation_plan=self._generation_plan(brief, cases),
            final_prompt_sections=self._render_sections(brief, intent, prompt_payload, cases, text_literals),
        )

    def final_prompt(self, spec: PromptSpec) -> str:
        return "\n".join(section for section in spec.final_prompt_sections if section.strip())

    def _selected_strategies(self, cases: list[dict[str, Any]]) -> dict[str, Any]:
        selected = []
        visual_principles: list[str] = []
        for case in cases[:5]:
            visual_dna = case.get("visual_dna") if isinstance(case.get("visual_dna"), dict) else {}
            prompt_spec = case.get("prompt_spec") if isinstance(case.get("prompt_spec"), dict) else {}
            selected.append(
                {
                    "case_id": case.get("id"),
                    "title": case.get("title"),
                    "profile": case.get("profile"),
                    "source": case.get("source"),
                    "creative_strategy": prompt_spec.get("creative_strategy") or _first(visual_dna.get("profile_strategy")),
                    "transferable_dna": {key: value for key, value in visual_dna.items() if value},
                }
            )
            for item in case.get("takeaways", []):
                if item and item not in visual_principles:
                    visual_principles.append(str(item))
        return {
            "retrieval_mode": "case_dna_transfer_not_template_fill",
            "selected_cases": selected,
            "visual_principles": visual_principles[:10],
        }

    def _intent_payload(self, brief: CreativeBrief, intent: PromptIntent) -> dict[str, Any]:
        return {
            "action_type": brief.action_type.value,
            "profile": brief.profile,
            "confidence": intent.confidence,
            "source_image_count": brief.source_image_count,
            "needs_text_rendering": intent.needs_text_rendering,
            "needs_character_consistency": intent.needs_character_consistency,
        }

    def _creative_direction(self, brief: CreativeBrief, prompt_payload: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "core_brief": brief.user_prompt,
            "target_profile": brief.profile,
            "concept_source": "user brief + retrieved visual DNA + quality reference hints",
            "case_inspiration": [case.get("title") for case in cases[:3] if case.get("title")],
            "default_quality_direction": prompt_payload.get("style") or _case_value(cases, "style_system", "visual_style") or _case_strategy(cases) or "professional image-generation art direction",
        }

    def _scene_graph(self, brief: CreativeBrief, prompt_payload: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
        scene_graph = {
            "hero_subject": prompt_payload.get("subject") or brief.user_prompt,
            "environment": prompt_payload.get("environment") or _dna_value(cases, "composition") or "environment chosen to reinforce the brief",
            "supporting_elements": _unique([*_dna_values(cases, "subject_strategy"), *_list(prompt_payload.get("scene_constraints"))])[:8],
            "spatial_relationships": _unique(_dna_values(cases, "composition"))[:6],
        }
        reference_policy = _list(prompt_payload.get("reference_image_policy"))
        if reference_policy:
            scene_graph["reference_image_policy"] = reference_policy[:8]
        return scene_graph

    def _composition(self, prompt_payload: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "layout": prompt_payload.get("camera_and_composition") or _dna_value(cases, "composition") or "clear focal hierarchy with controlled negative space",
            "camera": _dna_value(cases, "camera") or prompt_payload.get("camera_and_composition") or "camera angle selected for the subject and use case",
            "hierarchy": "primary subject first, supporting details second, decorative elements last",
            "continuity": "composition must stay coherent across iterations and edits",
        }

    def _style_system(self, prompt_payload: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "visual_style": prompt_payload.get("style") or _case_strategy(cases),
            "lighting": prompt_payload.get("lighting") or _dna_value(cases, "lighting") or "controlled high-quality lighting",
            "color_palette": prompt_payload.get("color_palette") or "palette derived from the selected case DNA and user brief",
            "materials": _unique(_dna_values(cases, "materials"))[:6],
            "atmosphere": prompt_payload.get("atmosphere") or "cohesive atmosphere without visual clutter",
        }

    def _text_system(self, intent: PromptIntent, text_literals: list[str], cases: list[dict[str, Any]]) -> dict[str, Any]:
        if not intent.needs_text_rendering and not _dna_values(cases, "typography"):
            return {}
        quoted = [f'"{literal}"' for literal in text_literals]
        return {
            "required_text": quoted,
            "typography_strategy": _dna_value(cases, "typography") or "isolated readable text with explicit placement, font style, and high contrast",
            "fidelity_rules": [
                "render only requested text literals exactly",
                "avoid invented letters, fake text, misspellings, or extra slogans",
                "place text on calm background areas with enough contrast",
            ],
        }

    def _edit_operation(self, intent: PromptIntent, has_mask: bool) -> dict[str, Any]:
        if intent.action_type not in _EDIT_ACTIONS:
            return {}
        return {
            "operation": intent.action_type.value,
            "instruction": intent.edit_instruction,
            "mask_policy": "edit only the masked region" if has_mask else "global edit constrained by preserve directives",
            "preserve": intent.preserve_directives,
            "modify": intent.modify_directives,
        }

    def _character_identity(self, intent: PromptIntent, request: PromptSkillRequest) -> dict[str, Any]:
        anchors = _unique([*request.character_anchors, *intent.character_anchors])
        if not intent.needs_character_consistency and not anchors:
            return {}
        return {
            "locked_anchors": anchors,
            "policy": "identity anchors are invariant across prompt recompilation; scene, pose, and style may change only around them",
        }

    def _constraints(self, intent: PromptIntent, prompt_payload: dict[str, Any], defects: tuple[str, ...], cases: list[dict[str, Any]]) -> dict[str, Any]:
        avoid = _unique([*_list(prompt_payload.get("negative_prompt")), *intent.avoid_directives, *_dna_values(cases, "negative_patterns")])
        return {
            "preserve": intent.preserve_directives,
            "avoid": avoid,
            "defect_repair_targets": list(defects),
            "quality_gates": [
                "subject and named entity fidelity",
                "clear visual hierarchy",
                "case-level polish rather than generic detail inflation",
            ],
        }

    def _generation_plan(self, brief: CreativeBrief, cases: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "compiler": "prompt_spec_compiler_v1",
            "strategy": "compile structured visual brief from retrieved case DNA before rendering final prompt",
            "execution_mode": brief.action_type.value,
            "case_count": len(cases),
        }

    def _render_sections(
        self,
        brief: CreativeBrief,
        intent: PromptIntent,
        prompt_payload: dict[str, Any],
        cases: list[dict[str, Any]],
        text_literals: list[str],
    ) -> tuple[str, ...]:
        sections = [
            f"Task: {intent.action_type.value} / {brief.profile} image production brief",
            f"Creative brief: {brief.user_prompt}",
            f"Case DNA transfer: {_case_strategy(cases)}",
            f"Hero subject and scene: {prompt_payload.get('subject') or brief.user_prompt}; {prompt_payload.get('environment') or _dna_value(cases, 'composition') or 'coherent environment'}",
            f"Composition: {prompt_payload.get('camera_and_composition') or _dna_value(cases, 'composition') or 'strong focal hierarchy, controlled layout, balanced negative space'}",
            f"Lighting and materials: {prompt_payload.get('lighting') or _dna_value(cases, 'lighting') or 'professional controlled lighting'}; {'; '.join(_unique(_dna_values(cases, 'materials'))[:4])}",
            f"Style system: {prompt_payload.get('style') or _case_strategy(cases)}; color palette: {prompt_payload.get('color_palette') or 'coherent palette derived from the brief'}",
        ]
        reference_policy = _list(prompt_payload.get("reference_image_policy"))
        if reference_policy:
            sections.append("Reference image policy: " + "; ".join(reference_policy[:8]))
        if text_literals:
            sections.append("Text rendering: " + "; ".join(f'render exactly "{literal}" with clear readable typography, stable placement, and no invented text' for literal in text_literals))
        if intent.action_type in _EDIT_ACTIONS:
            sections.append("Edit operation: " + "; ".join(_unique([*intent.preserve_directives, *intent.modify_directives]) or [str(intent.edit_instruction or brief.user_prompt)]))
        if intent.needs_character_consistency or brief.character_anchors:
            sections.append("Character identity lock: " + "; ".join(_unique([*brief.character_anchors, *intent.character_anchors, *intent.preserve_directives])))
        avoid = _unique([*_list(prompt_payload.get("negative_prompt")), *intent.avoid_directives, *_dna_values(cases, "negative_patterns")])
        if avoid:
            sections.append("Avoid: " + "; ".join(avoid[:8]))
        if brief.defects:
            sections.append("Repair targets from previous iteration: " + "; ".join(brief.defects))
        return tuple(sections)


_EDIT_ACTIONS = {ImageActionType.EDIT, ImageActionType.INPAINT, ImageActionType.OUTPAINT, ImageActionType.STYLE_TRANSFER}


def _list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _first(value: Any) -> str | None:
    items = _list(value)
    return items[0] if items else None


def _dna_values(cases: list[dict[str, Any]], key: str) -> list[str]:
    values: list[str] = []
    for case in cases:
        visual_dna = case.get("visual_dna") if isinstance(case.get("visual_dna"), dict) else {}
        values.extend(_list(visual_dna.get(key)))
    return _unique(values)


def _dna_value(cases: list[dict[str, Any]], key: str) -> str | None:
    values = _dna_values(cases, key)
    return values[0] if values else None


def _case_value(cases: list[dict[str, Any]], section: str, key: str) -> str | None:
    for case in cases:
        prompt_spec = case.get("prompt_spec") if isinstance(case.get("prompt_spec"), dict) else {}
        section_value = prompt_spec.get(section) if isinstance(prompt_spec.get(section), dict) else {}
        value = section_value.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _case_strategy(cases: list[dict[str, Any]]) -> str:
    for case in cases:
        prompt_spec = case.get("prompt_spec") if isinstance(case.get("prompt_spec"), dict) else {}
        strategy = prompt_spec.get("creative_strategy")
        if isinstance(strategy, str) and strategy.strip():
            return strategy
        visual_dna = case.get("visual_dna") if isinstance(case.get("visual_dna"), dict) else {}
        strategy = _first(visual_dna.get("profile_strategy"))
        if strategy:
            return strategy
    return "case-informed structured prompt strategy"
