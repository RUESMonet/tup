import json

from src.models.prompt_report import PromptReport
from src.models.visual_report import VisualReport
from src.agents.prompt_pattern_library import prompt_pattern_library
from src.agents.quality_reference import QualityReference


class OptimizerAgent:
    OPTIMIZATION_TERMS = QualityReference.PROFILES
    DEFAULT_NEGATIVE = (
        "negative prompt: low resolution, blurry, distorted anatomy, extra limbs, "
        "text artifacts, watermark, incoherent layout"
    )

    async def refine(self, prompt: str, report: PromptReport | VisualReport) -> str:
        if isinstance(report, PromptReport):
            return self._refine_from_prompt_report(prompt, report)
        return self._refine_from_visual_report(prompt, report)

    def _refine_from_prompt_report(self, prompt: str, report: PromptReport) -> str:
        prompt_text = self._original_prompt_text(prompt)
        additions: list[str] = []
        missing = set(report.missing)
        terms = self._select_terms(prompt_text)
        pattern_reference = prompt_pattern_library.build_reference(prompt_text)
        if "无风格限定词" in missing:
            additions.append(str(terms["style"]))
        if "缺少光影描述" in missing:
            additions.append(str(terms["lighting"]))
        if "缺少镜头或构图参数" in missing:
            additions.append(str(terms["camera"]))
        if "缺少负向约束" in missing:
            additions.append(self.DEFAULT_NEGATIVE)
        if "主体不够具体" in missing or "存在泛化或歧义词" in missing:
            additions.append(str(terms["constraints"]))

        payload = {
            "task": "image_generation",
            "source": "prompt_pre_evaluation",
            "original_prompt": prompt_text.strip(),
            "prompt": {
                "subject": prompt_text.strip(),
                "style": terms["style"],
                "lighting": terms["lighting"],
                "camera_and_composition": terms["camera"],
                "atmosphere": terms["atmosphere"],
                "constraints": terms["constraints"],
                "negative_prompt": self.DEFAULT_NEGATIVE,
            },
            "additional_constraints": list(dict.fromkeys(additions)),
            "pattern_principles": pattern_reference.pattern_principles,
            "matched_patterns": [pattern.model_dump(mode="json") for pattern in pattern_reference.matched_patterns],
            "quality_requirements": [
                "preserve the user's core subject",
                "make the image coherent, detailed, and production-ready",
                "avoid ambiguity, low quality artifacts, and broken composition",
            ],
        }
        return self._dump_json(payload)

    def _refine_from_visual_report(self, prompt: str, report: VisualReport) -> str:
        fixes: list[str] = []
        defects = " ".join(report.defects)
        if "主体" in defects or "subject" in defects:
            fixes.append("keep the original subject unmistakable and centered")
        if "构图" in defects or "composition" in defects:
            fixes.append("improve composition with a clear focal point and balanced framing")
        if "模糊" in defects or "blurry" in defects:
            fixes.append("increase sharpness and fine detail")
        if "风格" in defects or "style" in defects:
            fixes.append("make the requested visual style more consistent")
        if not fixes:
            fixes.append(report.suggestion or "increase image quality while preserving the original intent")

        payload = self._load_prompt_payload(prompt)
        payload["source"] = "visual_feedback_iteration"
        payload["visual_feedback"] = {
            "total_score": report.total_score,
            "defects": report.defects,
            "suggestion": report.suggestion,
        }
        pattern_reference = prompt_pattern_library.build_reference(str(payload.get("original_prompt") or prompt))
        payload["pattern_principles"] = list(
            dict.fromkeys([*payload.get("pattern_principles", []), *pattern_reference.pattern_principles])
        )
        payload["matched_patterns"] = pattern_reference.model_dump(mode="json")["matched_patterns"]
        payload["revision_focus"] = fixes
        payload["quality_requirements"] = list(
            dict.fromkeys(
                [
                    *payload.get("quality_requirements", []),
                    "preserve the original user intent",
                    "fix only the reported visual defects",
                ]
            )
        )
        return self._dump_json(payload)

    def _select_terms(self, prompt: str) -> dict[str, tuple[str, ...] | str]:
        return QualityReference.profile_terms(prompt)

    @staticmethod
    def _original_prompt_text(prompt: str) -> str:
        try:
            payload = json.loads(prompt)
        except json.JSONDecodeError:
            return prompt
        if not isinstance(payload, dict):
            return prompt
        prompt_payload = payload.get("prompt")
        if isinstance(prompt_payload, dict):
            raw_text = prompt_payload.get("raw_text")
            if isinstance(raw_text, str) and raw_text.strip():
                return raw_text
            structured_text = OptimizerAgent._prompt_payload_text(prompt_payload)
            if structured_text:
                return structured_text
        original_prompt = payload.get("original_prompt")
        return original_prompt if isinstance(original_prompt, str) and original_prompt.strip() else prompt

    @staticmethod
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
        return "\n".join(item for value in fields for item in OptimizerAgent._prompt_text_items(value))

    @staticmethod
    def _prompt_text_items(value) -> list[str]:
        if isinstance(value, str) and value.strip():
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str) and item.strip()]
        return []

    @staticmethod
    def _dump_json(payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _load_prompt_payload(prompt: str) -> dict:
        try:
            payload = json.loads(prompt)
        except json.JSONDecodeError:
            return {
                "task": "image_generation",
                "source": "visual_feedback_iteration",
                "original_prompt": prompt.strip(),
                "prompt": {"subject": prompt.strip()},
            }

        if not isinstance(payload, dict):
            return {
                "task": "image_generation",
                "source": "visual_feedback_iteration",
                "original_prompt": prompt.strip(),
                "prompt": {"subject": prompt.strip()},
            }
        return payload
