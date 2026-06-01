import json

from src.agents.prompt_draft import PromptDraftAgent
from src.agents.prompt_evaluator import PromptPreEvaluator
from src.agents.quality_reference import QualityReference
from src.agents.visual_evaluator import VisualEvaluator
from src.config import Settings
from src.models.prompt_report import PromptReport
from src.models.task import IterationRecord, PipelineResult, PromptOptimizationStage, PromptOptimizationTrace, PromptPayloadView
from src.services.model_router import ModelRouter


class LlmPromptRefiner:
    def __init__(self, settings: Settings):
        self.draft_agent = PromptDraftAgent(settings)

    async def refine(self, prompt: str, report) -> str:
        draft = await self.draft_agent.draft(self._refinement_input(prompt, report))
        draft_prompt = draft.get("draft_prompt")
        if not isinstance(draft_prompt, str) or not draft_prompt.strip():
            raise RuntimeError("LLM prompt optimizer returned no prompt")
        return draft_prompt.strip()

    @staticmethod
    def _refinement_input(prompt: str, report) -> str:
        prompt_text = _prompt_text(prompt)
        defects = getattr(report, "defects", None)
        suggestion = getattr(report, "suggestion", "")
        missing = getattr(report, "missing", None)
        if isinstance(defects, list) and defects:
            return "\n".join([prompt_text, f"视觉缺陷：{'；'.join(str(item) for item in defects)}", f"修正建议：{suggestion}"])
        if isinstance(missing, list) and missing:
            return "\n".join([prompt_text, f"缺失维度：{'；'.join(str(item) for item in missing)}", f"优化建议：{suggestion}"])
        return prompt_text


class ImageGenerationPipeline:
    def __init__(
        self,
        settings: Settings,
        prompt_evaluator: PromptPreEvaluator | None = None,
        optimizer: object | None = None,
        model_router: ModelRouter | None = None,
        visual_evaluator: VisualEvaluator | None = None,
    ):
        self.settings = settings
        self.prompt_evaluator = prompt_evaluator or PromptPreEvaluator(settings)
        self.optimizer = optimizer or LlmPromptRefiner(settings)
        self.model_router = model_router or ModelRouter(settings)
        self.visual_evaluator = visual_evaluator or VisualEvaluator(settings)

    async def run(
        self,
        user_input: str,
        model_id: str,
        threshold: float | None = None,
        max_iter: int | None = None,
        params: dict | None = None,
        skip_prompt_evaluation: bool = False,
    ) -> PipelineResult:
        threshold = threshold if threshold is not None else self.settings.visual_pass_threshold
        max_iter = max_iter or self.settings.max_iterations
        original_prompt = _prompt_text(user_input)
        prompt_report = PromptReport(score=10.0, passed=True, missing=[], suggestion="") if skip_prompt_evaluation else await self.prompt_evaluator.evaluate(original_prompt)
        trace = _initial_trace(original_prompt, prompt_report)

        prompt = user_input
        if not skip_prompt_evaluation and not prompt_report.passed:
            prompt = await self.optimizer.refine(original_prompt, prompt_report)
            trace.stages.append(_prompt_refinement_stage(prompt, trace.profile))

        history: list[IterationRecord] = []
        last_image = None
        last_visual_report = None

        for iteration in range(1, max_iter + 1):
            image = await self.model_router.generate(model_id, prompt, params)
            visual_report = await self.visual_evaluator.score(image, original_prompt, prompt)
            history.append(IterationRecord(iteration=iteration, prompt=prompt, image=image, visual_report=visual_report))
            trace.stages.append(_visual_iteration_stage(iteration, prompt, visual_report, trace.profile))
            last_image = image
            last_visual_report = visual_report

            if visual_report.total_score >= threshold:
                break
            if iteration < max_iter:
                prompt = await self.optimizer.refine(prompt, visual_report)
                trace.stages.append(_visual_refinement_stage(prompt, visual_report, trace.profile))

        if last_image is None or last_visual_report is None:
            raise RuntimeError("Pipeline did not run any image generation iteration")

        return PipelineResult(
            image=last_image,
            final_prompt=history[-1].prompt,
            score=last_visual_report.total_score,
            iterations=len(history),
            prompt_report=prompt_report,
            prompt_history=history,
            optimization_trace=trace,
        )


def _initial_trace(original_prompt: str, prompt_report) -> PromptOptimizationTrace:
    profile = QualityReference.select_profile(original_prompt)
    selected_terms = _selected_terms(original_prompt)
    return PromptOptimizationTrace(
        original_prompt=original_prompt,
        profile=profile,
        quality_source=QualityReference.SOURCE_NAME,
        stages=[
            PromptOptimizationStage(
                stage="pre_evaluation",
                title="原始提示词评估",
                summary="检查主体、风格、光影、镜头、细节和负向约束是否完整。",
                score=prompt_report.score,
                passed=prompt_report.passed,
                missing=prompt_report.missing,
                suggestion=prompt_report.suggestion,
                profile=profile,
                selected_terms=selected_terms,
            )
        ],
    )


def _prompt_refinement_stage(prompt: str, profile: str) -> PromptOptimizationStage:
    payload = _load_prompt_payload(prompt)
    return PromptOptimizationStage(
        stage="prompt_refinement",
        title="关键词与结构化提示词生成",
        summary="根据缺失维度补充风格、光影、镜头、氛围、约束和负向词。",
        source=str(payload.get("source") or "prompt_pre_evaluation"),
        profile=profile,
        prompt_payload=_payload_view(payload),
    )


def _visual_iteration_stage(iteration: int, prompt: str, visual_report, profile: str) -> PromptOptimizationStage:
    return PromptOptimizationStage(
        stage="visual_iteration",
        title=f"第 {iteration} 轮图片评分",
        summary="对生成结果进行视觉质量评分，并记录缺陷用于后续修正。",
        score=visual_report.total_score,
        defects=visual_report.defects,
        suggestion=visual_report.suggestion,
        profile=profile,
        prompt_payload=_payload_view(_load_prompt_payload(prompt)),
    )


def _visual_refinement_stage(prompt: str, visual_report, profile: str) -> PromptOptimizationStage:
    payload = _load_prompt_payload(prompt)
    return PromptOptimizationStage(
        stage="visual_refinement",
        title="视觉反馈修正",
        summary="根据上一轮图片缺陷定向修正 prompt，不改变原始意图。",
        score=visual_report.total_score,
        defects=visual_report.defects,
        suggestion=visual_report.suggestion,
        source=str(payload.get("source") or "visual_feedback_iteration"),
        profile=profile,
        prompt_payload=_payload_view(payload),
    )


def _selected_terms(prompt: str) -> dict:
    terms = QualityReference.profile_terms(prompt)
    return {
        "style": terms.get("style"),
        "lighting": terms.get("lighting"),
        "camera_and_composition": terms.get("camera"),
        "atmosphere": terms.get("atmosphere"),
        "constraints": terms.get("constraints"),
    }


def _payload_view(payload: dict) -> PromptPayloadView:
    prompt_payload = payload.get("prompt") if isinstance(payload.get("prompt"), dict) else {}
    return PromptPayloadView(
        subject=_display_value(prompt_payload.get("subject")),
        environment=_display_value(prompt_payload.get("environment")),
        style=_display_value(prompt_payload.get("style")),
        lighting=_display_value(prompt_payload.get("lighting")),
        camera_and_composition=_display_value(prompt_payload.get("camera_and_composition")),
        atmosphere=_display_value(prompt_payload.get("atmosphere")),
        color_palette=_display_value(prompt_payload.get("color_palette")),
        text_and_logo_constraints=_display_value(prompt_payload.get("text_and_logo_constraints")),
        constraints=_display_value(prompt_payload.get("constraints") or prompt_payload.get("scene_constraints")),
        negative_prompt=_display_value(prompt_payload.get("negative_prompt")),
        additional_constraints=_list_value(payload.get("additional_constraints")),
        pattern_principles=_list_value(payload.get("pattern_principles")),
        quality_requirements=_list_value(payload.get("quality_requirements")),
        revision_focus=_list_value(payload.get("revision_focus")),
    )


def _load_prompt_payload(prompt: str) -> dict:
    try:
        payload = json.loads(prompt)
    except json.JSONDecodeError:
        return {"prompt": {"subject": prompt}}
    return payload if isinstance(payload, dict) else {"prompt": {"subject": prompt}}


def _display_value(value) -> str | list[str] | None:
    if isinstance(value, str):
        return value if value else None
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return None


def _list_value(value) -> list[str]:
    display_value = _display_value(value)
    if display_value is None:
        return []
    if isinstance(display_value, list):
        return display_value
    return [display_value]


def _prompt_text(prompt: str) -> str:
    try:
        payload = json.loads(prompt)
    except json.JSONDecodeError:
        return prompt
    if not isinstance(payload, dict):
        return prompt
    prompt_payload = payload.get("prompt")
    if not isinstance(prompt_payload, dict):
        return prompt
    raw_text = prompt_payload.get("raw_text")
    if isinstance(raw_text, str) and raw_text.strip():
        return raw_text
    structured_text = _prompt_payload_text(prompt_payload)
    if structured_text:
        return structured_text
    original_prompt = payload.get("original_prompt")
    return original_prompt if isinstance(original_prompt, str) and original_prompt.strip() else prompt


def _prompt_payload_text(prompt_payload: dict) -> str:
    fields = (
        prompt_payload.get("subject"),
        prompt_payload.get("environment"),
        prompt_payload.get("style"),
        prompt_payload.get("lighting"),
        prompt_payload.get("camera_and_composition"),
        prompt_payload.get("atmosphere"),
        prompt_payload.get("color_palette"),
        prompt_payload.get("text_and_logo_constraints"),
        prompt_payload.get("scene_constraints") or prompt_payload.get("constraints"),
        prompt_payload.get("negative_prompt"),
    )
    return "\n".join(item for value in fields for item in _prompt_text_items(value))


def _prompt_text_items(value) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []
