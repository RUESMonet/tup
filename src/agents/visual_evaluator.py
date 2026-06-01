import json
import logging

import httpx

from src.config import Settings
from src.agents.prompt_pattern_library import prompt_pattern_library
from src.agents.quality_reference import QualityReference
from src.models.task import ImageResult
from src.models.visual_report import VisualReport
from src.services.url_security import hosts_from_csv, hosts_from_urls, safe_https_base_url


logger = logging.getLogger(__name__)


def _safe_evaluator_base_url(settings: Settings) -> str:
    return safe_https_base_url(
        settings.evaluator_base_url,
        _allowed_hosts(settings),
        error_message="evaluator base URL is not allowed",
        proxy_fake_ip_allowed_hosts=hosts_from_csv(settings.model_base_url_allowed_hosts),
    )


def _allowed_hosts(settings: Settings) -> set[str]:
    return {
        "api.openai.com",
        *hosts_from_urls(
            (
                settings.openai_base_url,
                settings.openai_image_base_url,
                settings.openai_evaluator_base_url,
                settings.openai_prompt_draft_base_url,
                settings.openai_prompt_optimizer_base_url,
                settings.video_base_url,
            )
        ),
        *hosts_from_csv(settings.model_base_url_allowed_hosts),
    }


class VisualEvaluator:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def score(self, image: ImageResult, original_input: str, prompt: str) -> VisualReport:
        if image.metadata.get("mock"):
            return self._build_fallback_report(original_input, prompt)

        if not self.settings.evaluator_api_key:
            raise RuntimeError("Evaluator API key is not configured for real image scoring")
        if not (image.b64_json or image.url):
            raise RuntimeError("Generated image cannot be scored because no image payload is available")

        try:
            return await self._score_with_openai(image, original_input, prompt)
        except RuntimeError:
            logger.exception("Visual evaluator failed; using local fallback report")
            return self._build_fallback_report(
                original_input,
                prompt,
                extra_defects=["自动评分服务不可用，已使用本地兜底评分。"],
            )

    async def _score_with_openai(
        self,
        image: ImageResult,
        original_input: str,
        prompt: str,
    ) -> VisualReport:
        image_url = self._image_url_for_openai(image)
        if image_url is None:
            raise RuntimeError("Generated image is missing a scorer-compatible URL or base64 payload")

        payload = {
            "model": self.settings.openai_evaluator_model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": self._build_scoring_request(original_input, prompt)},
                        {
                            "type": "input_image",
                            "image_url": image_url,
                        },
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "visual_report",
                    "strict": True,
                    "schema": self._visual_report_schema(),
                }
            },
        }
        headers = {
            "Authorization": f"Bearer {self.settings.evaluator_api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)

        try:
            async with httpx.AsyncClient(base_url=_safe_evaluator_base_url(self.settings), timeout=timeout) as client:
                response = await client.post("/responses", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = self._response_error_detail(exc.response)
            raise RuntimeError(f"HTTP {exc.response.status_code} from evaluator endpoint ({detail})") from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RuntimeError(f"evaluator request error: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("evaluator returned invalid response JSON") from exc

        text = self._extract_openai_text(data)
        if not text:
            raise RuntimeError("evaluator returned no text content")

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("evaluator returned invalid JSON") from exc

        try:
            return self._coerce_visual_report(payload, original_input, prompt)
        except ValueError as exc:
            raise RuntimeError(f"evaluator returned an invalid report: {exc}") from exc

    @staticmethod
    def _build_scoring_request(original_input: str, prompt: str) -> str:
        reference_prompt = original_input or prompt
        return json.dumps(
            {
                "task": "score_image_quality",
                "instruction": (
                    "Return JSON only. Do not include markdown or commentary. "
                    "After scoring, provide concrete optimization_hints and an optimization_prompt "
                    "that can be used for the next image generation iteration."
                ),
                "original_input": original_input,
                "current_prompt": prompt,
                "quality_reference": QualityReference.scoring_reference(reference_prompt),
                "pattern_reference": prompt_pattern_library.build_reference(reference_prompt).model_dump(mode="json"),
                "optimization_reference": QualityReference.optimization_hints(reference_prompt),
                "score_range": {"min": 0.0, "max": 10.0},
                "response_schema": {
                    "total_score": "number",
                    "composition": "number",
                    "subject_match": "number",
                    "style_match": "number",
                    "technical_quality": "number",
                    "defects": ["string"],
                    "suggestion": "string",
                    "optimization_hints": ["string"],
                    "optimization_prompt": "string",
                    "candidate_prompts": [
                        {
                            "id": "string",
                            "title": "string",
                            "estimated_score": "number",
                            "why": "string",
                            "summary": "object",
                            "optimized_prompt": "string",
                        }
                    ],
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _build_optimization_prompt(prompt: str, hints: list[str]) -> str:
        return json.dumps(
            QualityReference.optimized_prompt_payload(prompt, hints),
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def _build_fallback_report(
        self,
        original_input: str,
        prompt: str,
        extra_defects: list[str] | None = None,
    ) -> VisualReport:
        base = 8.2 if "revision_focus" not in prompt else 8.7
        defects: list[str] = list(extra_defects or [])
        if len(prompt) < 80:
            base -= 1.3
            defects.append("prompt 信息不足，主体和风格可能不稳定")
        if not original_input.strip():
            base -= 2.0
            defects.append("原始用户意图为空")

        total = max(0.0, min(10.0, round(base, 2)))
        optimization_hints = QualityReference.optimization_hints(original_input or prompt, defects)
        candidate_prompts = QualityReference.candidate_prompt_payloads(original_input or prompt, optimization_hints)
        return VisualReport(
            total_score=total,
            composition=min(10.0, round(total + 0.1, 2)),
            subject_match=min(10.0, round(total + 0.2, 2)),
            style_match=total,
            technical_quality=max(0.0, round(total - 0.1, 2)),
            defects=defects,
            suggestion="提升主体明确性、构图稳定性和细节清晰度" if defects else "图像质量达到当前阈值",
            optimization_hints=optimization_hints,
            optimization_prompt=json.dumps(
                (candidate_prompts[1] if len(candidate_prompts) > 1 else candidate_prompts[0])["optimized_prompt"],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            candidate_prompts=candidate_prompts,
        )

    def _coerce_visual_report(self, payload: dict, original_input: str, prompt: str) -> VisualReport:
        if not isinstance(payload, dict):
            raise ValueError("report payload is not an object")

        total = self._coerce_score(payload.get("total_score"))
        composition = self._coerce_score(payload.get("composition"))
        subject_match = self._coerce_score(payload.get("subject_match"))
        style_match = self._coerce_score(payload.get("style_match"))
        technical_quality = self._coerce_score(payload.get("technical_quality"))

        component_scores = [score for score in [composition, subject_match, style_match, technical_quality] if score is not None]
        if total is None:
            if not component_scores:
                raise ValueError("total_score is missing")
            total = round(sum(component_scores) / len(component_scores), 2)

        composition = composition if composition is not None else total
        subject_match = subject_match if subject_match is not None else total
        style_match = style_match if style_match is not None else total
        technical_quality = technical_quality if technical_quality is not None else total

        defects = [str(item) for item in payload.get("defects", [])] if isinstance(payload.get("defects"), list) else []
        reference_prompt = original_input or prompt
        optimization_hints = (
            [str(item) for item in payload.get("optimization_hints", [])]
            if isinstance(payload.get("optimization_hints"), list)
            else QualityReference.optimization_hints(reference_prompt, defects)
        )
        candidate_prompts = (
            payload.get("candidate_prompts")
            if isinstance(payload.get("candidate_prompts"), list) and payload.get("candidate_prompts")
            else QualityReference.candidate_prompt_payloads(reference_prompt, optimization_hints)
        )

        optimization_prompt = payload.get("optimization_prompt")
        if isinstance(optimization_prompt, (dict, list)):
            optimization_prompt = json.dumps(optimization_prompt, ensure_ascii=False, separators=(",", ":"))
        elif not isinstance(optimization_prompt, str) or not optimization_prompt.strip():
            optimization_prompt = json.dumps(
                (candidate_prompts[1] if len(candidate_prompts) > 1 else candidate_prompts[0])["optimized_prompt"],
                ensure_ascii=False,
                separators=(",", ":"),
            )

        return VisualReport.model_validate(
            {
                "total_score": total,
                "composition": composition,
                "subject_match": subject_match,
                "style_match": style_match,
                "technical_quality": technical_quality,
                "defects": defects,
                "suggestion": str(payload.get("suggestion", "")),
                "optimization_hints": optimization_hints,
                "optimization_prompt": optimization_prompt,
                "candidate_prompts": candidate_prompts,
            }
        )

    @staticmethod
    def _coerce_score(value: object) -> float | None:
        if value is None:
            return None
        try:
            score = round(float(value), 2)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(10.0, score))

    @staticmethod
    def _image_url_for_openai(image: ImageResult) -> str | None:
        if image.b64_json:
            media_type = image.metadata.get("media_type", "image/png")
            return f"data:{media_type};base64,{image.b64_json}"
        if image.url and image.url.startswith(("http://", "https://")):
            return image.url
        return None

    @staticmethod
    def _extract_openai_text(data: dict) -> str:
        if isinstance(data.get("output_text"), str):
            return data["output_text"]

        for output in data.get("output", []):
            if not isinstance(output, dict):
                continue
            for content in output.get("content", []):
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    return content["text"]
        return ""

    @staticmethod
    def _response_error_detail(response: httpx.Response) -> str:
        text = response.text.strip()
        if not text:
            return "empty response body"
        compact = " ".join(text.split())
        return compact[:240]

    @staticmethod
    def _visual_report_schema() -> dict:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "total_score",
                "composition",
                "subject_match",
                "style_match",
                "technical_quality",
                "defects",
                "suggestion",
                "optimization_hints",
                "optimization_prompt",
                "candidate_prompts",
            ],
            "properties": {
                "total_score": {"type": "number", "minimum": 0, "maximum": 10},
                "composition": {"type": "number", "minimum": 0, "maximum": 10},
                "subject_match": {"type": "number", "minimum": 0, "maximum": 10},
                "style_match": {"type": "number", "minimum": 0, "maximum": 10},
                "technical_quality": {"type": "number", "minimum": 0, "maximum": 10},
                "defects": {"type": "array", "items": {"type": "string"}},
                "suggestion": {"type": "string"},
                "optimization_hints": {"type": "array", "items": {"type": "string"}},
                "optimization_prompt": {"type": "string"},
                "candidate_prompts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["id", "title", "estimated_score", "why", "summary", "optimized_prompt"],
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "estimated_score": {"type": "number", "minimum": 0, "maximum": 10},
                            "why": {"type": "string"},
                            "summary": {"type": "object", "additionalProperties": {"type": "string"}},
                            "optimized_prompt": {"type": "string"},
                        },
                    },
                },
            },
        }
