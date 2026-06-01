from src.config import Settings
from src.agents.quality_reference import QualityReference
from src.models.prompt_report import PromptReport


class PromptPreEvaluator:
    STYLE_TERMS = {
        "photorealistic", "cinematic", "watercolor", "oil painting", "anime",
        "illustration", "3d", "pixel art", "写实", "电影感", "水彩", "油画", "动漫", "插画", "制作板", "故事板",
    }
    LIGHT_TERMS = {
        "light", "lighting", "backlight", "golden hour", "neon", "soft light",
        "shadow", "光", "光线", "逆光", "柔光", "霓虹", "黄昏", "阴影", "氛围",
    }
    TECH_TERMS = {
        "lens", "camera", "close-up", "wide angle", "composition", "depth of field",
        "构图", "镜头", "特写", "广角", "景深", "焦距", "俯拍", "仰拍", "分镜", "景别", "机位", "16:9",
    }
    NEGATIVE_MARKERS = {"不要", "避免", "no ", "without", "negative prompt"}
    AMBIGUOUS_TERMS = {"随便", "好看", "高级", "酷", "nice", "cool", "beautiful"}
    REFERENCE_DIMENSION_LABELS = {
        "subject": "参考集：主体仍不够明确",
        "style": "参考集：缺少明确视觉风格",
        "lighting": "参考集：缺少光影或氛围",
        "composition": "参考集：缺少构图或镜头控制",
        "detail": "参考集：缺少材质、纹理或细节",
        "constraints": "参考集：缺少质量约束",
    }

    def __init__(self, settings: Settings):
        self.settings = settings

    async def evaluate(self, prompt: str) -> PromptReport:
        normalized = prompt.lower()
        missing: list[str] = []
        score = 1.0

        if len(prompt.strip()) >= 8 and not self._mostly_ambiguous(normalized):
            score += 2.0
        else:
            missing.append("主体不够具体")

        if self._contains_any(normalized, self.STYLE_TERMS):
            score += 2.0
        else:
            missing.append("无风格限定词")

        if self._contains_any(normalized, self.LIGHT_TERMS):
            score += 1.75
        else:
            missing.append("缺少光影描述")

        if self._contains_any(normalized, self.TECH_TERMS):
            score += 1.75
        else:
            missing.append("缺少镜头或构图参数")

        if self._contains_any(normalized, self.NEGATIVE_MARKERS):
            score += 1.0
        else:
            missing.append("缺少负向约束")

        if self._contains_any(normalized, self.AMBIGUOUS_TERMS):
            score -= 1.0
            if "存在泛化或歧义词" not in missing:
                missing.append("存在泛化或歧义词")

        quality_reference = QualityReference.prompt_quality(prompt)
        matched_count = len(set(quality_reference["matched_dimensions"]))
        if matched_count >= 5:
            score += 1.0
        elif matched_count < 4:
            missing.append("未达到高质量参考结构")
            for dimension in quality_reference["missing_dimensions"][:2]:
                label = self.REFERENCE_DIMENSION_LABELS.get(dimension)
                if label:
                    missing.append(label)

        score = max(0.0, min(10.0, round(score, 2)))
        passed = score >= self.settings.prompt_pass_threshold
        suggestion = (
            "Prompt 已符合高质量参考结构"
            if passed
            else f"建议参考 {QualityReference.SOURCE_NAME} 补充：主体细节、艺术风格、光线类型、镜头参数、质量约束"
        )
        return PromptReport(score=score, passed=passed, missing=missing, suggestion=suggestion)

    @staticmethod
    def _contains_any(text: str, terms: set[str]) -> bool:
        return any(term in text for term in terms)

    @staticmethod
    def _mostly_ambiguous(text: str) -> bool:
        return len(text.strip()) < 8
