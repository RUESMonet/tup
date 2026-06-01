from src.agents.prompt_evaluator import PromptPreEvaluator
from src.agents.prompt_skill_agent import PromptSkillAgent
from src.agents.quality_reference import QualityReference
from src.agents.visual_evaluator import VisualEvaluator
from src.config import Settings
from src.models.prompt_report import PromptReport
from src.models.prompt_skill import ImageActionType, PromptSkillRequest, PromptSkillResponse
from src.models.task import IterationRecord, PipelineResult, PromptOptimizationStage, PromptOptimizationTrace
from src.services.model_router import ModelRouter


class PromptSkillPipeline:
    def __init__(
        self,
        settings: Settings,
        prompt_skill_agent: PromptSkillAgent | None = None,
        prompt_evaluator: PromptPreEvaluator | None = None,
        model_router: ModelRouter | None = None,
        visual_evaluator: VisualEvaluator | None = None,
    ):
        self.settings = settings
        self.prompt_skill_agent = prompt_skill_agent or PromptSkillAgent()
        self.prompt_evaluator = prompt_evaluator or PromptPreEvaluator(settings)
        self.model_router = model_router or ModelRouter(settings)
        self.visual_evaluator = visual_evaluator or VisualEvaluator(settings)

    async def run(
        self,
        request: PromptSkillRequest,
        model_id: str,
        threshold: float | None = None,
        max_iter: int | None = None,
        skip_prompt_evaluation: bool = False,
    ) -> tuple[PipelineResult, PromptSkillResponse]:
        threshold = threshold if threshold is not None else self.settings.visual_pass_threshold
        max_iter = max_iter or self.settings.max_iterations
        prompt_skill = await self.prompt_skill_agent.optimize(request)
        prompt_report = PromptReport(score=10.0, passed=True, missing=[], suggestion="") if skip_prompt_evaluation else await self.prompt_evaluator.evaluate(request.prompt)
        prompt = prompt_skill.final_english_prompt
        trace = self._trace(request.prompt, prompt_skill, prompt_report)
        history: list[IterationRecord] = []
        last_image = None
        last_visual_report = None
        for iteration in range(1, max_iter + 1):
            image = await self._generate(prompt_skill, request, model_id, prompt)
            visual_report = await self.visual_evaluator.score(image, request.prompt, prompt)
            history.append(IterationRecord(iteration=iteration, prompt=prompt, image=image, visual_report=visual_report))
            trace.stages.append(
                PromptOptimizationStage(
                    stage="prompt_skill_visual_iteration",
                    title=f"第 {iteration} 轮 Prompt Skill 图片评分",
                    summary="按任务意图、RAG 案例和专项质量门槛评估生成结果。",
                    score=visual_report.total_score,
                    defects=visual_report.defects,
                    suggestion=visual_report.suggestion,
                    profile=prompt_skill.intent.profile,
                )
            )
            last_image = image
            last_visual_report = visual_report
            if visual_report.total_score >= threshold:
                break
            if iteration < max_iter:
                prompt = _visual_feedback_prompt(prompt, visual_report)
                trace.stages.append(_visual_refinement_stage(prompt, visual_report, prompt_skill.intent.profile))
        if last_image is None or last_visual_report is None:
            raise RuntimeError("Prompt Skill pipeline did not produce an image")
        return (
            PipelineResult(
                image=last_image,
                final_prompt=history[-1].prompt,
                score=last_visual_report.total_score,
                iterations=len(history),
                prompt_report=prompt_report if isinstance(prompt_report, PromptReport) else PromptReport(score=0, passed=False, missing=[], suggestion=""),
                prompt_history=history,
                optimization_trace=trace,
            ),
            prompt_skill,
        )

    async def _generate(self, prompt_skill: PromptSkillResponse, request: PromptSkillRequest, model_id: str, prompt: str):
        action = prompt_skill.intent.action_type
        if action in {ImageActionType.EDIT, ImageActionType.INPAINT, ImageActionType.OUTPAINT, ImageActionType.STYLE_TRANSFER}:
            return await self.model_router.edit_image(model_id, prompt, request.source_images, request.mask_image, request.params)
        if action in {ImageActionType.IMAGE_TO_IMAGE, ImageActionType.TEXT_AND_IMAGE_TO_IMAGE}:
            return await self.model_router.generate_with_references(model_id, prompt, request.source_images, request.params)
        return await self.model_router.generate_text_to_image(model_id, prompt, request.params)

    @staticmethod
    def _trace(original_prompt: str, prompt_skill: PromptSkillResponse, prompt_report) -> PromptOptimizationTrace:
        return PromptOptimizationTrace(
            original_prompt=original_prompt,
            profile=prompt_skill.intent.profile,
            quality_source=QualityReference.SOURCE_NAME,
            stages=[
                PromptOptimizationStage(
                    stage="prompt_skill_optimization",
                    title="Prompt Skill 意图识别与 RAG 美化",
                    summary="识别任务类型，匹配本地 awesome 案例，生成工业级结构化 prompt、编辑策略和质量门槛。",
                    score=prompt_report.score,
                    passed=prompt_report.passed,
                    missing=prompt_report.missing,
                    suggestion=prompt_report.suggestion,
                    source="prompt_skill_agent",
                    profile=prompt_skill.intent.profile,
                )
            ],
        )



def _visual_feedback_prompt(prompt: str, visual_report) -> str:
    defects = "; ".join(visual_report.defects[:8])
    suggestion = str(visual_report.suggestion or "").strip()
    feedback = "; ".join(item for item in (defects, suggestion) if item)
    if not feedback:
        return prompt
    return f"{prompt}\nVisual feedback repair: {feedback}"



def _visual_refinement_stage(prompt: str, visual_report, profile: str) -> PromptOptimizationStage:
    return PromptOptimizationStage(
        stage="prompt_skill_visual_refinement",
        title="Prompt Skill 视觉反馈修正",
        summary="根据上一轮视觉评分缺陷修正下一轮生成 prompt，保持任务意图和参考图约束。",
        score=visual_report.total_score,
        defects=visual_report.defects,
        suggestion=visual_report.suggestion,
        source="prompt_skill_visual_feedback",
        profile=profile,
    )
