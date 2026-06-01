from typing import Any, cast

from src.agents.quality_reference import QualityReference
from src.models.optimization_guide import GuideAction, GuideDimension, GuideIssue, OptimizationGuide


_DIMENSIONS: tuple[GuideDimension, ...] = ("subject", "style", "lighting", "composition", "detail", "constraints")

_DIMENSION_COPY: dict[GuideDimension, tuple[str, str, str, str, str]] = {
    "subject": (
        "主体信息不足",
        "补充主体身份、数量、外观和主体与环境的关系。",
        "补充主体和场景关系",
        "把主体放在提示词开头，说明数量、材质、位置和动作。",
        "例如：透明玻璃香水瓶居中放置在浅灰石材台面上，瓶身轮廓清晰。",
    ),
    "style": (
        "风格方向不够明确",
        "指定摄影、插画、海报、角色设定或 UI mockup 等稳定风格。",
        "收窄视觉风格",
        "选择一个主要风格方向，避免多个互相冲突的艺术描述。",
        "例如：realistic commercial product photography, premium material rendering。",
    ),
    "lighting": (
        "光影与氛围不足",
        "补充主光、辅光、时间段、阴影或反射控制，让画面情绪更稳定。",
        "补充光影与氛围",
        "描述光源类型、方向、强弱和希望保留的阴影或反射效果。",
        "例如：softbox studio lighting, controlled reflections, clean specular highlights。",
    ),
    "composition": (
        "构图与镜头不足",
        "补充镜头、景别、焦点层级、画面留白或布局比例，减少随机构图。",
        "明确镜头和构图",
        "指定拍摄角度、焦段、主体位置和前后景层级。",
        "例如：three-quarter product angle, centered hero composition, sharp foreground detail。",
    ),
    "detail": (
        "细节约束不足",
        "补充材质、纹理、环境、服装、道具或可验证细节，提高成片质感。",
        "补充可验证细节",
        "加入能被画面直接验证的材质、纹理、品牌感和环境细节。",
        "例如：polished glass material, subtle condensation, fine label edge detail。",
    ),
    "constraints": (
        "负向约束不足",
        "加入负向词和一致性约束，限制模糊、水印、文字错误、主体漂移等问题。",
        "加入负向约束",
        "列出明确不要出现的瑕疵，并约束文字、logo、数量和几何形态。",
        "例如：negative prompt: blurry, watermark, warped label, duplicated object。",
    ),
}

_SEVERITY_BY_INDEX = ("high", "medium", "medium", "low", "low", "low")


class OptimizationGuideBuilder:
    def build(self, prompt: str, reference_payload: dict[str, Any]) -> OptimizationGuide:
        payload = reference_payload or {}
        quality = self._quality(prompt, payload)
        missing_dimensions = self._missing_dimensions(quality)
        candidate_prompts = self._candidate_prompts(payload)

        if not missing_dimensions:
            return OptimizationGuide(
                summary="当前提示词结构较完整，可以直接生成并根据视觉评分做小幅迭代。",
                actions=[
                    GuideAction(
                        title="直接生成并观察评分",
                        instruction="保留当前主体、风格、光影、构图和约束，只在生成后针对最低分项做局部调整。",
                        example="生成图片后优先查看主体匹配、构图、风格和技术质量的最低项。",
                        priority="low",
                    )
                ],
                next_steps=["生成图片后查看视觉评分最低项", "只针对低分项补充约束，避免一次改动过多"],
            )

        issues = [self._issue(dimension, index) for index, dimension in enumerate(missing_dimensions)]
        actions = [self._action(dimension, index) for index, dimension in enumerate(missing_dimensions)]
        candidate_action = self._candidate_action(candidate_prompts)
        if candidate_action:
            actions.append(candidate_action)

        return OptimizationGuide(
            summary=self._summary(quality, missing_dimensions),
            issues=issues,
            actions=actions,
            next_steps=self._next_steps(candidate_prompts),
        )

    def _quality(self, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        quality = payload.get("quality")
        if isinstance(quality, dict):
            return quality
        return QualityReference.prompt_quality(prompt)

    def _missing_dimensions(self, quality: dict[str, Any]) -> list[GuideDimension]:
        missing = quality.get("missing_dimensions")
        if isinstance(missing, list):
            return self._known_dimensions(missing)
        matched = quality.get("matched_dimensions")
        if isinstance(matched, list):
            matched_set = {dimension for dimension in matched if isinstance(dimension, str)}
            return [dimension for dimension in _DIMENSIONS if dimension not in matched_set]
        return ["style", "lighting", "composition", "constraints"]

    def _candidate_prompts(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = payload.get("candidate_prompts")
        if not isinstance(candidates, list):
            return []
        return [candidate for candidate in candidates if isinstance(candidate, dict)]

    def _issue(self, dimension: GuideDimension, index: int) -> GuideIssue:
        title, detail, *_ = _DIMENSION_COPY[dimension]
        severity = _SEVERITY_BY_INDEX[min(index, len(_SEVERITY_BY_INDEX) - 1)]
        return GuideIssue(dimension=dimension, title=title, detail=detail, severity=severity)

    def _action(self, dimension: GuideDimension, index: int) -> GuideAction:
        *_, title, instruction, example = _DIMENSION_COPY[dimension]
        priority = _SEVERITY_BY_INDEX[min(index, len(_SEVERITY_BY_INDEX) - 1)]
        return GuideAction(title=title, instruction=instruction, example=example, priority=priority)

    def _candidate_action(self, candidates: list[dict[str, Any]]) -> GuideAction | None:
        usable = [candidate for candidate in candidates if candidate.get("id") != "original"]
        if not usable:
            return None
        best = max(usable, key=self._estimated_score)
        title = str(best.get("title") or best.get("id") or "候选提示词")
        summary = best.get("summary")
        if isinstance(summary, dict):
            example = f"优先尝试“{title}”：" + " / ".join(f"{key}: {value}" for key, value in list(summary.items())[:3])
        else:
            example = f"优先尝试“{title}”候选提示词。"
        return GuideAction(
            title="套用候选提示词",
            instruction="从候选方案里选择最贴近目标的一版，再按实际生成结果微调。",
            example=example,
            priority="medium",
        )

    def _summary(self, quality: dict[str, Any], missing_dimensions: list[GuideDimension]) -> str:
        profile = quality.get("profile") or "default"
        missing_titles = [self._issue(dimension, index).title for index, dimension in enumerate(missing_dimensions[:3])]
        return f"当前提示词适合 {profile} 方向，但还需要优化：{'、'.join(missing_titles)}。"

    def _next_steps(self, candidates: list[dict[str, Any]]) -> list[str]:
        steps = ["先应用评分最高的候选提示词", "生成图片后查看评分和迭代历史", "只针对最低分项继续补充约束"]
        if not any(candidate.get("id") != "original" for candidate in candidates):
            return steps[1:]
        return steps

    @staticmethod
    def _estimated_score(candidate: dict[str, Any]) -> float:
        score = candidate.get("estimated_score", 0)
        return float(score) if isinstance(score, (int, float)) else 0.0

    @staticmethod
    def _known_dimensions(dimensions: list[Any]) -> list[GuideDimension]:
        known = set(_DIMENSIONS)
        return [cast(GuideDimension, dimension) for dimension in dimensions if isinstance(dimension, str) and dimension in known]
