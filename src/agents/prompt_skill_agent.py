import asyncio
from copy import deepcopy
from typing import Any

from src.agents.character_sheet import CharacterSheetExtractor
from src.agents.intent_classifier import IntentClassifier
from src.agents.quality_reference import QualityReference
from src.agents.prompt_spec_compiler import PromptSpecCompiler
from src.agents.rag_case_retriever import RagCaseRetriever
from src.agents.text_rendering_rules import TextRenderingRules
from src.models.prompt_skill import ImageActionType, PromptSkillRequest, PromptSkillResponse, ReferenceUsage, SuggestedImageParams


class PromptSkillAgent:
    def __init__(
        self,
        classifier: IntentClassifier | None = None,
        retriever: RagCaseRetriever | None = None,
        character_extractor: CharacterSheetExtractor | None = None,
        compiler: PromptSpecCompiler | None = None,
    ):
        self.classifier = classifier or IntentClassifier()
        self.retriever = retriever or RagCaseRetriever(limit=5)
        self.character_extractor = character_extractor or CharacterSheetExtractor()
        self.compiler = compiler or PromptSpecCompiler()

    async def optimize(self, request: PromptSkillRequest) -> PromptSkillResponse:
        context_text = self._context_text(request)
        resolved_prompt = "\n".join(item for item in (context_text, request.prompt) if item)
        intent = self.classifier.classify(
            resolved_prompt,
            source_images=request.source_images,
            requested_action_type=request.action_type,
        )
        if request.character_anchors:
            intent.needs_character_consistency = True
            intent.character_anchors = list(dict.fromkeys([*request.character_anchors, *intent.character_anchors]))
            intent.preserve_directives = list(
                dict.fromkeys([
                    *intent.preserve_directives,
                    "Preserve locked conversation character anchors: " + "; ".join(request.character_anchors),
                ])
            )
        cases, freshness = await asyncio.gather(
            self.retriever.retrieve(resolved_prompt, task_type=intent.action_type.value, limit=5),
            self.retriever.source_freshness(),
        )
        resolved_request = request.model_copy(update={"prompt": resolved_prompt})
        internal_hints = QualityReference.optimization_hints(resolved_prompt, request.defects)
        internal_optimized = QualityReference.optimized_prompt_payload(resolved_prompt, internal_hints)
        internal_optimized = self._adapt_payload_for_intent(internal_optimized, intent, cases, mask_image=request.mask_image is not None)
        public_hints = QualityReference.optimization_hints(request.prompt, request.defects)
        optimized = QualityReference.optimized_prompt_payload(request.prompt, public_hints)
        optimized = self._adapt_payload_for_intent(optimized, intent, cases, mask_image=request.mask_image is not None)
        optimized["current_user_prompt"] = request.prompt
        if intent.needs_text_rendering:
            internal_optimized = TextRenderingRules.apply_constraints(internal_optimized, intent.detected_text_literals)
            optimized = TextRenderingRules.apply_constraints(optimized, intent.detected_text_literals)
        spec = self.compiler.compile(resolved_request, intent, cases, internal_optimized)
        public_spec = self.compiler.compile(request, intent, cases, optimized)
        optimized["prompt_spec"] = public_spec.as_payload()
        optimized["source"] = "case_aware_prompt_spec_compiler"
        final_prompt = self.compiler.final_prompt(spec)
        quality_gates = self._quality_gates(intent)
        reference_usage = ReferenceUsage(
            retrieval_strategy="local case DNA retrieval + Prompt Spec compiler + task intent reranking",
            matched_cases=cases,
            pattern_principles=self._pattern_principles(cases),
            source_freshness=freshness,
        )
        return PromptSkillResponse(
            intent=intent,
            optimized_prompt=optimized,
            final_english_prompt=final_prompt,
            reference_usage=reference_usage,
            suggested_params=self._suggested_params(intent, request.params),
            quality_gates=quality_gates,
            edit_policy=self._edit_policy(intent),
            character_policy=self._character_policy(intent),
            warnings=self._warnings(intent),
        )

    def _context_text(self, request: PromptSkillRequest) -> str:
        lines: list[str] = []
        for item in request.conversation_context[-6:]:
            if item.get("role", "user") != "user" or not isinstance(item.get("content"), str):
                continue
            content = str(item["content"]).strip()
            if content:
                lines.append(content)
        if request.character_anchors:
            lines.append("Locked character anchors: " + "; ".join(request.character_anchors[:40]))
        return "\n".join(lines)

    def _adapt_payload_for_intent(self, payload: dict[str, Any], intent, cases: list[dict[str, Any]], *, mask_image: bool = False) -> dict[str, Any]:
        adapted = deepcopy(payload)
        prompt_payload = adapted.setdefault("prompt", {})
        adapted["source"] = "prompt_skill_agent"
        adapted["intent"] = intent.model_dump(mode="json")
        adapted["matched_case_ids"] = [case.get("id") for case in cases if case.get("id")]
        if intent.action_type in self._edit_actions():
            adapted["task"] = "image_edit"
            prompt_payload["edit_instruction"] = intent.edit_instruction
            prompt_payload["mask_policy"] = "Use the provided mask as the only editable region." if mask_image else "No mask was provided; treat the edit as a global image edit constrained by preserve directives."
            prompt_payload["preserve"] = intent.preserve_directives
            prompt_payload["modify"] = intent.modify_directives
            prompt_payload["avoid"] = intent.avoid_directives
            prompt_payload["scene_constraints"] = list(
                dict.fromkeys([
                    *self._list_value(prompt_payload.get("scene_constraints")),
                    *intent.preserve_directives,
                    *intent.avoid_directives,
                ])
            )
        elif intent.action_type in {ImageActionType.IMAGE_TO_IMAGE, ImageActionType.TEXT_AND_IMAGE_TO_IMAGE}:
            adapted["task"] = "image_reference_generation"
            prompt_payload["reference_image_policy"] = [
                "Use provided source images as visual references for identity, style, layout, or material cues.",
                "Do not copy artifacts, compression noise, watermarks, or unrelated background details from references.",
            ]
        else:
            adapted["task"] = "image_generation"
        if intent.needs_character_consistency:
            prompt_payload["character_consistency"] = [
                "Lock identity anchors before changing pose, scene, outfit variants, or camera angle.",
                *intent.character_anchors,
                *intent.preserve_directives,
            ]
        return adapted

    def _render_final_prompt(self, payload: dict[str, Any], intent, cases: list[dict[str, Any]]) -> str:
        prompt_payload = payload.get("prompt") if isinstance(payload.get("prompt"), dict) else {}
        fields = (
            ("Core subject", prompt_payload.get("subject")),
            ("Edit instruction", prompt_payload.get("edit_instruction")),
            ("Environment", prompt_payload.get("environment")),
            ("Visual style", prompt_payload.get("style")),
            ("Lighting", prompt_payload.get("lighting")),
            ("Camera and composition", prompt_payload.get("camera_and_composition")),
            ("Atmosphere", prompt_payload.get("atmosphere")),
            ("Color palette", prompt_payload.get("color_palette")),
            ("Text and logo rendering", prompt_payload.get("text_and_logo_constraints")),
            ("Preserve", prompt_payload.get("preserve")),
            ("Modify", prompt_payload.get("modify")),
            ("Character consistency", prompt_payload.get("character_consistency")),
            ("Scene constraints", prompt_payload.get("scene_constraints") or prompt_payload.get("constraints")),
            ("Negative prompt", prompt_payload.get("negative_prompt")),
        )
        lines = [f"Task: {payload.get('task', 'image_generation')}", f"Intent: {intent.action_type.value}, profile: {intent.profile}"]
        for label, value in fields:
            items = self._list_value(value)
            if items:
                lines.append(f"{label}: {'; '.join(items)}")
        if cases:
            references = "; ".join(str(case.get("title")) for case in cases[:3] if case.get("title"))
            if references:
                lines.append(f"Reference prompt patterns: {references}")
        return "\n".join(lines)

    def _quality_gates(self, intent) -> list[str]:
        gates = [
            "Subject fidelity: every generated image must preserve the user's explicit subject, count, named entities, and scene anchors.",
            "Composition quality: output must have clear focal hierarchy, controlled lighting, and no unintended extra objects.",
            "Artifact control: reject blurry, low-resolution, watermarked, malformed, or incoherent compositions.",
        ]
        if intent.needs_text_rendering:
            gates.append("文字/typography fidelity: requested text must be exact, readable, correctly placed, and free from invented characters.")
        if intent.needs_character_consistency:
            gates.append("Character consistency: identity anchors, proportions, hairstyle, outfit, and accessories must remain stable across outputs.")
        if intent.action_type in self._edit_actions():
            gates.append("Edit fidelity: only requested regions or concepts may change; source identity and unedited regions must be preserved.")
        return gates

    def _suggested_params(self, intent, params: dict[str, Any]) -> SuggestedImageParams:
        aspect_ratio = str(params.get("aspect_ratio") or intent.aspect_ratio or "") or None
        quality = str(params.get("quality") or "high")
        size = str(params.get("size") or "") or None
        background = str(params.get("background") or "") or None
        extras = {key: value for key, value in params.items() if key not in {"aspect_ratio", "quality", "size", "background"}}
        return SuggestedImageParams(aspect_ratio=aspect_ratio, quality=quality, size=size, background=background, extras=extras)

    @staticmethod
    def _pattern_principles(cases: list[dict[str, Any]]) -> list[str]:
        principles: list[str] = []
        for case in cases:
            principles.extend(str(item) for item in case.get("takeaways", []) if item)
        return list(dict.fromkeys(principles))[:8]

    @staticmethod
    def _edit_policy(intent) -> dict[str, list[str]]:
        if intent.action_type not in PromptSkillAgent._edit_actions():
            return {}
        return {
            "preserve": intent.preserve_directives,
            "modify": intent.modify_directives,
            "avoid": intent.avoid_directives,
        }

    @staticmethod
    def _character_policy(intent) -> dict[str, Any]:
        if not intent.needs_character_consistency:
            return {}
        return {
            "anchors": intent.character_anchors,
            "locked_prompt_policy": "Inject these anchors into every subsequent generation or edit unless the user explicitly unlocks them.",
        }

    @staticmethod
    def _warnings(intent) -> list[str]:
        warnings: list[str] = []
        if intent.needs_user_clarification:
            warnings.append("输入信息偏短，系统已给出默认工业级补全；如需更稳定结果，请补充场景、风格、画幅和约束。")
        return warnings

    @staticmethod
    def _list_value(value: Any) -> list[str]:
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]
        return []

    @staticmethod
    def _edit_actions() -> set[ImageActionType]:
        return {ImageActionType.EDIT, ImageActionType.INPAINT, ImageActionType.OUTPAINT, ImageActionType.STYLE_TRANSFER}
