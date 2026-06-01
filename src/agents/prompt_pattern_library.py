import re
import time
from typing import Any

from src.agents.prompt_case_library import CURATED_FALLBACK_CASES, UPSTREAM_REPO_URL
from src.agents.quality_reference import QualityReference
from src.models.prompt_pattern import PromptPattern, PromptPatternReference


_DIMENSION_TERMS = {
    "subject": ("hero", "subject", "主体", "product", "character", "identity"),
    "style": ("photography", "illustration", "editorial", "poster", "commercial", "cinematic", "style"),
    "lighting": ("lighting", "light", "softbox", "neon", "rim", "golden hour", "光", "灯"),
    "composition": ("lens", "angle", "composition", "layout", "grid", "framing", "35mm", "85mm", "构图"),
    "detail": ("texture", "material", "skin", "reflections", "detail", "palette", "材质", "细节"),
    "constraints": ("avoid", "negative", "no ", "preserve", "consistent", "constraint", "约束", "避免"),
}

_DIMENSION_COPY = {
    "subject": "先锁定原始主体或 hero product/object、数量和可验证视觉锚点，再添加风格或场景增强。",
    "style": "把媒介、审美方向和交付形态写清楚，避免只堆抽象风格词。",
    "lighting": "明确主光、辅光、反射或时间段，让画面情绪和材质表现稳定。",
    "composition": "使用镜头、视角、景别、版式或留白约束来控制画面层级。",
    "detail": "补充材质、纹理、色彩和微细节，但所有细节必须服务原始主体。",
    "constraints": "把不要出现的伪影、文字错误、主体漂移和新增元素作为显式负向约束。",
}


class PromptPatternLibrary:
    def __init__(self, cases: list[dict[str, Any]] | None = None, source_updated_at: float | None = None):
        self.cases = list(cases) if cases is not None else list(CURATED_FALLBACK_CASES)
        self.source_updated_at = source_updated_at or time.time()

    def build_reference(self, prompt: str, limit: int = 3) -> PromptPatternReference:
        profile = QualityReference.select_profile(prompt)
        ranked = self._rank_cases(prompt, profile)
        selected = ranked[:limit]
        patterns = [self._pattern_from_case(case, score) for case, score in selected]
        principles = self._principles(patterns, profile)
        return PromptPatternReference(
            profile=profile,
            profile_confidence=self._profile_confidence(prompt, profile, patterns),
            matched_patterns=patterns,
            pattern_principles=principles,
            source_freshness=self.source_freshness,
        )

    @property
    def source_freshness(self) -> dict[str, Any]:
        return {
            "source": QualityReference.SOURCE_NAME,
            "url": UPSTREAM_REPO_URL,
            "case_count": len(self.cases),
            "loaded_at": self.source_updated_at,
            "mode": "curated_fallback" if self.cases == list(CURATED_FALLBACK_CASES) else "provided_cases",
        }

    def _rank_cases(self, prompt: str, profile: str) -> list[tuple[dict[str, Any], float]]:
        normalized = prompt.lower()
        ranked: list[tuple[dict[str, Any], float]] = []
        for case in self.cases:
            case_profile = str(case.get("profile", "default"))
            if case_profile not in {profile, "default"}:
                continue
            keyword_hits = sum(1 for item in case.get("when_to_use", []) if str(item).lower() in normalized)
            pattern_hits = sum(1 for item in _tokens(str(case.get("pattern", ""))) if item in normalized)
            profile_bonus = 10 if case_profile == profile else 1
            score = profile_bonus + keyword_hits * 2 + min(pattern_hits, 5)
            ranked.append((case, float(score)))
        return sorted(ranked, key=lambda item: item[1], reverse=True)

    def _pattern_from_case(self, case: dict[str, Any], score: float) -> PromptPattern:
        dimensions = self._dimensions(str(case.get("pattern", "")), [str(item) for item in case.get("takeaways", [])])
        principles = [_DIMENSION_COPY[dimension] for dimension in dimensions]
        takeaways = [str(item) for item in case.get("takeaways", []) if str(item).strip()]
        return PromptPattern(
            id=str(case.get("id") or case.get("title") or "pattern"),
            profile=str(case.get("profile") or "default"),
            title=str(case.get("title") or case.get("id") or "参考模式"),
            source_case=str(case.get("source_case") or QualityReference.SOURCE_NAME),
            principles=list(dict.fromkeys([*principles, *takeaways[:2]]))[:5],
            evidence=self._evidence(case),
            relevance=score,
        )

    def _dimensions(self, pattern: str, takeaways: list[str]) -> list[str]:
        text = f"{pattern} {' '.join(takeaways)}".lower()
        dimensions = [dimension for dimension, terms in _DIMENSION_TERMS.items() if any(term in text for term in terms)]
        return dimensions or ["subject", "composition", "constraints"]

    def _evidence(self, case: dict[str, Any]) -> list[str]:
        pattern = str(case.get("pattern") or "")
        fragments = [fragment.strip() for fragment in re.split(r"[,;，；]", pattern) if fragment.strip()]
        return fragments[:4]

    def _principles(self, patterns: list[PromptPattern], profile: str) -> list[str]:
        terms = QualityReference.PROFILES[profile]
        defaults = [
            f"按 {profile} 场景组织 prompt：主体、风格、光影、镜头、细节、约束分层表达。",
            f"参考镜头/构图骨架：{terms['camera']}",
            f"参考光影和氛围骨架：{terms['lighting']} / {terms['atmosphere']}",
            f"约束优先：{terms['constraints']}",
        ]
        extracted = [principle for pattern in patterns for principle in pattern.principles]
        return list(dict.fromkeys([*extracted, *defaults]))[:8]

    def _profile_confidence(self, prompt: str, profile: str, patterns: list[PromptPattern]) -> float:
        keywords = QualityReference.PROFILES[profile]["keywords"]
        keyword_hits = 0
        if isinstance(keywords, tuple):
            keyword_hits = sum(1 for keyword in keywords if keyword and keyword.lower() in prompt.lower())
        return min(1.0, round(0.35 + keyword_hits * 0.15 + len(patterns) * 0.1, 2))


def _tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", text.lower())]


prompt_pattern_library = PromptPatternLibrary()
