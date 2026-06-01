import json

import pytest

from src.config import Settings
from src.models.prompt_skill import ImageActionType, PromptIntent, PromptSkillRequest, PromptSkillResponse, ReferenceUsage
from src.models.task import ImageResult
from src.models.visual_report import VisualReport
from src.services.pipeline import ImageGenerationPipeline
from src.services.prompt_skill_pipeline import PromptSkillPipeline


class SpyModelRouter:
    def __init__(self):
        self.prompts: list[str] = []

    async def generate(self, model_id: str, prompt: str, params=None):
        self.prompts.append(prompt)
        return ImageResult(
            url=f"mock://{len(self.prompts)}",
            model_id=model_id,
            provider_model="mock-model",
            metadata={"mock": True},
        )

    async def generate_text_to_image(self, model_id: str, prompt: str, params=None):
        return await self.generate(model_id, prompt, params)

    async def generate_with_references(self, model_id: str, prompt: str, source_images, params=None):
        return await self.generate(model_id, prompt, params)

    async def edit_image(self, model_id: str, prompt: str, source_images, mask_image=None, params=None):
        return await self.generate(model_id, prompt, params)


class FakePromptSkillAgent:
    async def optimize(self, request: PromptSkillRequest):
        return PromptSkillResponse(
            intent=PromptIntent(action_type=ImageActionType.TEXT_TO_IMAGE, profile="poster", confidence=0.9),
            optimized_prompt={"prompt": {"subject": request.prompt}},
            final_english_prompt=request.prompt,
            reference_usage=ReferenceUsage(retrieval_strategy="test"),
        )


class FailingPromptEvaluator:
    def __init__(self):
        self.calls = 0

    async def evaluate(self, prompt: str):
        self.calls += 1
        raise AssertionError("prompt evaluator should be skipped")


class FakeLlmOptimizer:
    async def refine(self, prompt: str, report):
        try:
            payload = json.loads(prompt)
        except json.JSONDecodeError:
            payload = {
                "task": "image_generation",
                "source": "llm_prompt_optimizer",
                "original_prompt": prompt,
                "prompt": {
                    "subject": prompt,
                    "style": "cinematic photorealistic style",
                    "lighting": "soft directional light",
                    "camera_and_composition": "35mm lens, clear composition",
                    "negative_prompt": ["blurry", "watermark"],
                },
                "pattern_principles": ["LLM structured prompt"],
            }
        payload["source"] = "llm_prompt_optimizer"
        if hasattr(report, "total_score"):
            payload["revision_focus"] = ["LLM visual refinement"]
        return json.dumps(payload, ensure_ascii=False)


class SequenceVisualEvaluator:
    def __init__(self, scores: list[float]):
        self.scores = scores
        self.calls = 0

    async def score(self, image, original_input: str, prompt: str):
        score = self.scores[min(self.calls, len(self.scores) - 1)]
        self.calls += 1
        defects = [] if score >= 8 else ["主体不够清晰", "构图不稳定", "模糊"]
        return VisualReport(
            total_score=score,
            composition=score,
            subject_match=score,
            style_match=score,
            technical_quality=score,
            defects=defects,
            suggestion="根据图片缺陷定向修正 Prompt",
        )


@pytest.mark.asyncio
async def test_prompt_skill_pipeline_refines_prompt_after_failed_visual_iteration():
    router = SpyModelRouter()
    pipeline = PromptSkillPipeline(
        Settings(USE_MOCK_IMAGES=True),
        prompt_skill_agent=FakePromptSkillAgent(),
        model_router=router,
        visual_evaluator=SequenceVisualEvaluator([5.0, 8.5]),
    )

    result, _ = await pipeline.run(PromptSkillRequest(prompt="一张香水海报"), "openai", threshold=8.0, max_iter=2, skip_prompt_evaluation=True)

    assert result.iterations == 2
    assert len(router.prompts) == 2
    assert router.prompts[1] != router.prompts[0]
    assert "主体不够清晰" in router.prompts[1]


@pytest.mark.asyncio
async def test_image_pipeline_honors_skip_prompt_evaluation():
    evaluator = FailingPromptEvaluator()
    router = SpyModelRouter()
    pipeline = ImageGenerationPipeline(
        Settings(USE_MOCK_IMAGES=True),
        optimizer=FakeLlmOptimizer(),
        prompt_evaluator=evaluator,
        model_router=router,
        visual_evaluator=SequenceVisualEvaluator([8.5]),
    )

    result = await pipeline.run("一张香水海报", "openai", skip_prompt_evaluation=True)

    assert evaluator.calls == 0
    assert result.prompt_report.passed is True
    assert router.prompts == ["一张香水海报"]


@pytest.mark.asyncio
async def test_prompt_skill_pipeline_honors_skip_prompt_evaluation():
    evaluator = FailingPromptEvaluator()
    router = SpyModelRouter()
    pipeline = PromptSkillPipeline(
        Settings(USE_MOCK_IMAGES=True),
        prompt_skill_agent=FakePromptSkillAgent(),
        prompt_evaluator=evaluator,
        model_router=router,
        visual_evaluator=SequenceVisualEvaluator([8.5]),
    )

    result, _ = await pipeline.run(PromptSkillRequest(prompt="一张香水海报"), "openai", skip_prompt_evaluation=True)

    assert evaluator.calls == 0
    assert result.prompt_report.passed is True
    assert router.prompts == ["一张香水海报"]


@pytest.mark.asyncio
async def test_weak_prompt_is_evaluated_and_optimized_before_generation():
    router = SpyModelRouter()
    pipeline = ImageGenerationPipeline(
        Settings(USE_MOCK_IMAGES=True),
        optimizer=FakeLlmOptimizer(),
        model_router=router,
        visual_evaluator=SequenceVisualEvaluator([8.5]),
    )

    result = await pipeline.run("一只猫", "openai")

    assert result.prompt_report.passed is False
    assert result.prompt_report.score < 6.0
    assert router.prompts[0] != "一只猫"
    payload = json.loads(router.prompts[0])
    assert payload["task"] == "image_generation"
    assert payload["prompt"]["subject"] == "一只猫"
    assert payload["pattern_principles"]
    assert result.optimization_trace is not None
    stages = result.optimization_trace.stages
    assert [stage.stage for stage in stages] == ["pre_evaluation", "prompt_refinement", "visual_iteration"]
    assert stages[0].selected_terms["style"]
    assert stages[1].prompt_payload.subject == "一只猫"
    assert stages[1].prompt_payload.style
    assert stages[1].prompt_payload.negative_prompt
    assert result.iterations == 1


@pytest.mark.asyncio
async def test_optimized_structured_candidate_is_preserved_for_generation_when_it_passes():
    router = SpyModelRouter()
    pipeline = ImageGenerationPipeline(
        Settings(USE_MOCK_IMAGES=True),
        optimizer=FakeLlmOptimizer(),
        model_router=router,
        visual_evaluator=SequenceVisualEvaluator([8.5]),
    )
    structured_input = json.dumps(
        {
            "task": "image_generation",
            "source": "quality_reference_candidate_optimizer",
            "original_prompt": "一只猫",
            "prompt": {
                "subject": "一只猫坐在窗台上",
                "environment": "窗边室内环境",
                "style": "cinematic photorealistic style",
                "lighting": "soft directional light",
                "camera_and_composition": "35mm lens, clear composition",
                "atmosphere": "安静温暖",
                "color_palette": "warm amber and soft blue",
                "text_and_logo_constraints": "no visible text or logo",
                "negative_prompt": ["blurry", "watermark"],
            },
        },
        ensure_ascii=False,
    )

    result = await pipeline.run(structured_input, "openai")

    assert result.prompt_report.passed is True
    assert router.prompts[0] == structured_input
    assert result.optimization_trace is not None
    assert [stage.stage for stage in result.optimization_trace.stages] == ["pre_evaluation", "visual_iteration"]
    prompt_payload = result.optimization_trace.stages[1].prompt_payload
    assert prompt_payload.environment == "窗边室内环境"
    assert prompt_payload.color_palette == "warm amber and soft blue"
    assert prompt_payload.text_and_logo_constraints == "no visible text or logo"


@pytest.mark.asyncio
async def test_structured_original_input_is_evaluated_by_original_prompt_text():
    router = SpyModelRouter()
    pipeline = ImageGenerationPipeline(
        Settings(USE_MOCK_IMAGES=True),
        optimizer=FakeLlmOptimizer(),
        model_router=router,
        visual_evaluator=SequenceVisualEvaluator([8.5]),
    )
    structured_input = json.dumps(
        {
            "task": "image_generation",
            "source": "quality_reference_candidate_optimizer",
            "original_prompt": "一只猫",
            "prompt": {"subject": "一只猫", "raw_text": "一只猫"},
        },
        ensure_ascii=False,
    )

    result = await pipeline.run(structured_input, "openai")

    assert result.prompt_report.passed is False
    payload = json.loads(router.prompts[0])
    assert payload["prompt"]["subject"] == "一只猫"
    assert "quality_reference_candidate_optimizer" not in payload["prompt"]["subject"]


@pytest.mark.asyncio
async def test_visual_score_below_threshold_triggers_prompt_iteration():
    router = SpyModelRouter()
    pipeline = ImageGenerationPipeline(
        Settings(USE_MOCK_IMAGES=True),
        optimizer=FakeLlmOptimizer(),
        model_router=router,
        visual_evaluator=SequenceVisualEvaluator([5.0, 8.8]),
    )

    result = await pipeline.run("一座未来城市", "openai", threshold=8.0, max_iter=3)

    assert result.iterations == 2
    assert len(router.prompts) == 2
    payload = json.loads(router.prompts[1])
    assert payload["revision_focus"]
    assert payload["pattern_principles"]
    assert result.optimization_trace is not None
    assert [stage.stage for stage in result.optimization_trace.stages] == [
        "pre_evaluation",
        "prompt_refinement",
        "visual_iteration",
        "visual_refinement",
        "visual_iteration",
    ]
    visual_refinement = result.optimization_trace.stages[3]
    assert visual_refinement.prompt_payload.revision_focus
    assert result.final_prompt == router.prompts[1]
    assert result.score == 8.8


@pytest.mark.asyncio
async def test_pipeline_stops_at_max_iterations_without_returning_unused_prompt():
    router = SpyModelRouter()
    pipeline = ImageGenerationPipeline(
        Settings(USE_MOCK_IMAGES=True),
        optimizer=FakeLlmOptimizer(),
        model_router=router,
        visual_evaluator=SequenceVisualEvaluator([5.0, 5.2]),
    )

    result = await pipeline.run("一辆红色跑车", "openai", threshold=9.0, max_iter=2)

    assert result.iterations == 2
    assert result.final_prompt == router.prompts[-1]
