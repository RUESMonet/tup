import json
from typing import Any

import httpx

from src.config import Settings
from src.services.url_security import hosts_from_csv, hosts_from_urls, safe_https_base_url


class PromptOptimizerAgent:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def optimize(self, prompt: str, reference_payload: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.evaluator_api_key:
            raise RuntimeError("Evaluator API key is not configured for prompt optimization")
        payload = self._build_payload(prompt, reference_payload)
        headers = {
            "Authorization": f"Bearer {self.settings.evaluator_api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)

        data = await self._request_openai(payload, headers, timeout)
        if not isinstance(data, dict):
            raise RuntimeError("prompt optimizer returned a non-object response")

        text = self._extract_openai_text(data)
        if not text:
            raise RuntimeError("prompt optimizer returned no text content")
        try:
            optimized = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("prompt optimizer returned invalid JSON") from exc
        try:
            return self._coerce_optimized_prompt(optimized)
        except ValueError as exc:
            raise RuntimeError(f"prompt optimizer returned an invalid prompt: {exc}") from exc

    async def _request_openai(self, payload: dict[str, Any], headers: dict[str, str], timeout: httpx.Timeout) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(base_url=_safe_base_url(self.settings), timeout=timeout) as client:
                response = await client.post("/responses", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"HTTP {exc.response.status_code} from prompt optimizer endpoint") from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RuntimeError(f"prompt optimizer request error: {exc.__class__.__name__}") from exc
        except ValueError as exc:
            raise RuntimeError("prompt optimizer endpoint returned invalid response JSON") from exc
        return data

    def _build_payload(self, prompt: str, reference_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": self.settings.prompt_optimizer_model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": self._build_request(prompt, reference_payload),
                        }
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "optimized_image_prompt",
                    "strict": True,
                    "schema": self._optimized_prompt_schema(),
                }
            },
        }

    @staticmethod
    def _build_request(prompt: str, reference_payload: dict[str, Any]) -> str:
        compact_reference = {
            "quality": reference_payload.get("quality"),
            "optimization_hints": reference_payload.get("optimization_hints"),
            "candidate_prompts": reference_payload.get("candidate_prompts"),
            "matched_patterns": reference_payload.get("matched_patterns"),
            "pattern_principles": reference_payload.get("pattern_principles"),
            "scoring_reference": reference_payload.get("scoring_reference"),
            "guide": reference_payload.get("guide"),
        }
        return json.dumps(
            {
                "task": "optimize_image_prompt_from_reference",
                "instruction": (
                    "Return JSON only. Do not include markdown, code fences, commentary, or plain labeled text. "
                    "Combine the user's prompt with the provided quality/reference data to produce a generation-ready JSON prompt. "
                    "Preserve the user's subject, scene, objects, counts, named entities, and explicit constraints. "
                    "Use reference data as optimization guidance, not as content to copy blindly. "
                    "Do not add unrelated brands, objects, people, locations, plants, props, or story elements. "
                    "All prompt fields must be JSON strings or JSON arrays according to the response schema."
                ),
                "user_prompt": prompt,
                "reference": compact_reference,
                "output_policy": {
                    "language": "follow the user's language unless technical photography terms are clearer in English",
                    "format": "strict JSON object matching the response schema",
                    "negative_prompt": "array of concise defects to avoid, without repeated negative prompt prefixes",
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def _coerce_optimized_prompt(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("optimized prompt payload is not an object")
        prompt_payload = payload.get("prompt") if isinstance(payload.get("prompt"), dict) else {}
        negative_prompt = [_strip_negative_prefix(item) for item in _required_list(prompt_payload, "negative_prompt")]
        return {
            "task": _expected_string(payload, "task", "image_generation"),
            "source": _expected_string(payload, "source", "llm_reference_optimizer"),
            "original_prompt": _required_string(payload, "original_prompt"),
            "profile": _required_string(payload, "profile"),
            "optimization_hints": _required_list(payload, "optimization_hints"),
            "prompt": {
                "subject": _required_string(prompt_payload, "subject"),
                "environment": _required_string(prompt_payload, "environment"),
                "style": _required_string(prompt_payload, "style"),
                "lighting": _required_string(prompt_payload, "lighting"),
                "camera_and_composition": _required_string(prompt_payload, "camera_and_composition"),
                "atmosphere": _required_string(prompt_payload, "atmosphere"),
                "color_palette": _required_string(prompt_payload, "color_palette"),
                "text_and_logo_constraints": _required_string(prompt_payload, "text_and_logo_constraints"),
                "scene_constraints": _required_list(prompt_payload, "scene_constraints"),
                "negative_prompt": negative_prompt,
            },
            "reference_usage": _required_reference_usage(payload),
        }

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
    def _optimized_prompt_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["task", "source", "original_prompt", "profile", "optimization_hints", "prompt", "reference_usage"],
            "properties": {
                "task": {"type": "string"},
                "source": {"type": "string"},
                "original_prompt": {"type": "string"},
                "profile": {"type": "string"},
                "optimization_hints": {"type": "array", "items": {"type": "string"}},
                "prompt": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "subject",
                        "environment",
                        "style",
                        "lighting",
                        "camera_and_composition",
                        "atmosphere",
                        "color_palette",
                        "text_and_logo_constraints",
                        "scene_constraints",
                        "negative_prompt",
                    ],
                    "properties": {
                        "subject": {"type": "string"},
                        "environment": {"type": "string"},
                        "style": {"type": "string"},
                        "lighting": {"type": "string"},
                        "camera_and_composition": {"type": "string"},
                        "atmosphere": {"type": "string"},
                        "color_palette": {"type": "string"},
                        "text_and_logo_constraints": {"type": "string"},
                        "scene_constraints": {"type": "array", "items": {"type": "string"}},
                        "negative_prompt": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "reference_usage": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["used_quality_dimensions", "used_pattern_ids", "candidate_strategy"],
                    "properties": {
                        "used_quality_dimensions": {"type": "array", "items": {"type": "string"}},
                        "used_pattern_ids": {"type": "array", "items": {"type": "string"}},
                        "candidate_strategy": {"type": "string"},
                    },
                },
            },
        }


def _safe_base_url(settings: Settings) -> str:
    return safe_https_base_url(
        settings.prompt_optimizer_base_url,
        _allowed_hosts(settings),
        error_message="prompt optimizer base URL is not allowed",
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


def _string_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _list_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = _string_value(payload.get(key))
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _expected_string(payload: dict[str, Any], key: str, expected: str) -> str:
    value = _required_string(payload, key)
    if value != expected:
        raise ValueError(f"{key} must be {expected}")
    return value


def _required_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array")
    values = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(values) != len(value) or not values:
        raise ValueError(f"{key} is required")
    return values


def _string_array(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array")
    values = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if len(values) != len(value):
        raise ValueError(f"{key} must contain strings")
    return values


def _strip_negative_prefix(value: str) -> str:
    return value.removeprefix("negative prompt:").removeprefix("Negative Prompt:").strip()


def _required_reference_usage(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("reference_usage")
    if not isinstance(usage, dict):
        raise ValueError("reference_usage is required")
    return {
        "used_quality_dimensions": _string_array(usage, "used_quality_dimensions"),
        "used_pattern_ids": _string_array(usage, "used_pattern_ids"),
        "candidate_strategy": _required_string(usage, "candidate_strategy"),
    }
