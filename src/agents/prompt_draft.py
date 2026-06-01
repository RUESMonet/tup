import json
from collections.abc import AsyncIterator

import httpx

from src.agents.prompt_case_library import retrieve_prompt_cases
from src.agents.quality_reference import QualityReference
from src.config import Settings
from src.services.url_security import hosts_from_csv, hosts_from_urls, safe_https_base_url


def _safe_prompt_draft_base_url(settings: Settings) -> str:
    return safe_https_base_url(
        settings.prompt_draft_base_url,
        _allowed_hosts(settings),
        error_message="prompt draft base URL is not allowed",
        proxy_fake_ip_allowed_hosts=hosts_from_csv(settings.model_base_url_allowed_hosts),
    )


def _should_retry_chat_completions(status_code: int) -> bool:
    return status_code in {400, 404, 405}


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


def _loads_sse_json(raw: str) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("prompt draft stream returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("prompt draft stream returned invalid JSON")
    return payload


class PromptDraftAgent:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def draft(self, prompt: str) -> dict:
        clean_prompt = " ".join(prompt.strip().split())
        if not clean_prompt:
            return {
                "draft_prompt": "",
                "source": "empty",
                "model": None,
                "error": None,
            }

        if not self.settings.evaluator_api_key:
            raise RuntimeError("Evaluator API key is not configured for AI prompt drafting")

        draft_prompt = await self._draft_with_openai(clean_prompt)
        return {
            "draft_prompt": draft_prompt,
            "source": "llm",
            "model": self.settings.prompt_draft_model,
            "error": None,
        }

    async def stream_draft(self, prompt: str) -> AsyncIterator[dict]:
        clean_prompt = " ".join(prompt.strip().split())
        if not clean_prompt:
            yield {
                "type": "done",
                "draft_prompt": "",
                "source": "empty",
                "model": None,
                "error": None,
            }
            return

        if not self.settings.evaluator_api_key:
            raise RuntimeError("Evaluator API key is not configured for AI prompt drafting")

        async for event in self._stream_with_openai(clean_prompt):
            yield event

    async def _draft_with_openai(self, prompt: str) -> str:
        payload = await self._build_payload(prompt, stream=False)
        headers = {
            "Authorization": f"Bearer {self.settings.evaluator_api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)

        try:
            async with httpx.AsyncClient(base_url=_safe_prompt_draft_base_url(self.settings), timeout=timeout) as client:
                response = await client.post("/responses", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            if _should_retry_chat_completions(exc.response.status_code):
                return await self._draft_with_chat_completions(prompt, headers, timeout)
            detail = self._response_error_detail(exc.response)
            raise RuntimeError(f"HTTP {exc.response.status_code} from prompt draft endpoint ({detail})") from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RuntimeError(f"prompt draft request error: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("prompt draft endpoint returned invalid response JSON") from exc

        text = self._extract_openai_text(data)
        if not text:
            raise RuntimeError("prompt draft endpoint returned no text content")
        return text.strip()

    async def _stream_with_openai(self, prompt: str) -> AsyncIterator[dict]:
        payload = await self._build_payload(prompt, stream=True)
        headers = {
            "Authorization": f"Bearer {self.settings.evaluator_api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        accumulated = ""
        saw_done = False

        try:
            async with httpx.AsyncClient(base_url=_safe_prompt_draft_base_url(self.settings), timeout=timeout) as client:
                async with client.stream("POST", "/responses", json=payload, headers=headers) as response:
                    response.raise_for_status()
                    async for event in self._iter_sse_json(response):
                        event_type = event.get("type")
                        if event_type == "response.output_text.delta":
                            delta = event.get("delta", "")
                            if not isinstance(delta, str) or not delta:
                                continue
                            accumulated += delta
                            yield {"type": "delta", "delta": delta}
                        elif event_type == "response.output_text.done":
                            text = event.get("text")
                            if isinstance(text, str) and text.strip():
                                accumulated = text
                        elif event_type == "response.failed":
                            error_message = self._event_error_message(event)
                            raise RuntimeError(error_message or "prompt draft stream failed")
                        elif event_type == "error":
                            error_message = self._event_error_message(event)
                            raise RuntimeError(error_message or "prompt draft stream returned an error event")
                        elif event_type == "response.completed":
                            saw_done = True
                            yield {
                                "type": "done",
                                "draft_prompt": accumulated.strip(),
                                "source": "llm",
                                "model": self.settings.prompt_draft_model,
                                "error": None,
                            }
        except httpx.HTTPStatusError as exc:
            if _should_retry_chat_completions(exc.response.status_code):
                async for event in self._stream_with_chat_completions(prompt, headers, timeout):
                    yield event
                return
            detail = self._response_error_detail(exc.response)
            raise RuntimeError(f"HTTP {exc.response.status_code} from prompt draft endpoint ({detail})") from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RuntimeError(f"prompt draft request error: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("prompt draft stream returned invalid JSON") from exc

        if not saw_done:
            if not accumulated.strip():
                raise RuntimeError("prompt draft stream ended without text output")
            yield {
                "type": "done",
                "draft_prompt": accumulated.strip(),
                "source": "llm",
                "model": self.settings.prompt_draft_model,
                "error": None,
            }

    async def _draft_with_chat_completions(self, prompt: str, headers: dict[str, str], timeout: httpx.Timeout) -> str:
        payload = await self._build_chat_payload(prompt, stream=False)
        try:
            async with httpx.AsyncClient(base_url=_safe_prompt_draft_base_url(self.settings), timeout=timeout) as client:
                response = await client.post("/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = self._response_error_detail(exc.response)
            raise RuntimeError(f"HTTP {exc.response.status_code} from prompt draft chat endpoint ({detail})") from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RuntimeError(f"prompt draft chat request error: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("prompt draft chat endpoint returned invalid response JSON") from exc

        text = self._extract_chat_text(data)
        if not text:
            raise RuntimeError("prompt draft chat endpoint returned no text content")
        return text.strip()

    async def _stream_with_chat_completions(self, prompt: str, headers: dict[str, str], timeout: httpx.Timeout) -> AsyncIterator[dict]:
        payload = await self._build_chat_payload(prompt, stream=True)
        accumulated = ""
        try:
            async with httpx.AsyncClient(base_url=_safe_prompt_draft_base_url(self.settings), timeout=timeout) as client:
                async with client.stream("POST", "/chat/completions", json=payload, headers=headers) as response:
                    response.raise_for_status()
                    async for event in self._iter_sse_json(response):
                        if event.get("type") == "error":
                            error_message = self._event_error_message(event)
                            raise RuntimeError(error_message or "prompt draft chat stream returned an error event")
                        delta = self._chat_delta_text(event)
                        if delta:
                            accumulated += delta
                            yield {"type": "delta", "delta": delta}
        except httpx.HTTPStatusError as exc:
            detail = self._response_error_detail(exc.response)
            raise RuntimeError(f"HTTP {exc.response.status_code} from prompt draft chat stream endpoint ({detail})") from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RuntimeError(f"prompt draft chat stream request error: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("prompt draft chat stream returned invalid JSON") from exc

        if not accumulated.strip():
            raise RuntimeError("prompt draft chat stream ended without text output")
        yield {
            "type": "done",
            "draft_prompt": accumulated.strip(),
            "source": "llm",
            "model": self.settings.prompt_draft_model,
            "error": None,
        }

    @staticmethod
    def _build_request(prompt: str, prompt_cases: list[dict]) -> str:
        optimization_hints = QualityReference.optimization_hints(prompt)
        reference = QualityReference.scoring_reference(prompt)
        short_prompt = len(prompt.strip()) <= 20
        return json.dumps(
            {
                "task": "expand_image_prompt",
                "instruction": (
                    "Return only the expanded image prompt text in the same language as the user. "
                    "Do not return JSON, markdown, bullets, titles, or commentary. "
                    "Expand the user's image prompt into a stronger, production-ready single prompt "
                    "using the same language as the user. Preserve the user's core subject, named entities, and intent. "
                    "Do not invent new brands, locations, characters, or plot points that are not implied by the original prompt. "
                    "You may add style, lighting, composition, atmosphere, material detail, and negative constraints when they help. "
                    "Prefer concise, high-density phrasing over long explanation."
                ),
                "original_prompt": prompt,
                "quality_reference": reference,
                "optimization_hints": optimization_hints,
                "case_reference_policy": [
                    "Use the retrieved cases as style and structure references, not as content to copy literally.",
                    "Borrow the repo's strengths: concrete lens/composition terms, controlled lighting, clear hierarchy, and disciplined negative constraints.",
                    "Keep the user's subject first and avoid generic filler.",
                ],
                "retrieved_cases": [
                    {
                        "title": case["title"],
                        "source_case": case["source_case"],
                        "pattern": PromptDraftAgent._case_reference_pattern(case["pattern"]),
                        "takeaways": case["takeaways"],
                    }
                    for case in prompt_cases
                ],
                "length_budget": {
                    "preferred_style": "single compact paragraph",
                    "target_chars": 160 if short_prompt else 240,
                    "hard_cap_chars": 260 if short_prompt else 340,
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _case_reference_pattern(pattern: str) -> str:
        blocked_markers = (
            "ignore previous",
            "ignore prior",
            "system prompt",
            "developer message",
            "assistant message",
            "follow these instructions",
            "return only",
        )
        segments = [segment.strip() for segment in pattern.replace("```", " ").split(",") if segment.strip()]
        safe_segments = [segment for segment in segments if not any(marker in segment.lower() for marker in blocked_markers)]
        return ", ".join(safe_segments)[:700]

    async def _build_payload(self, prompt: str, stream: bool) -> dict:
        prompt_cases = await retrieve_prompt_cases(prompt)
        return {
            "model": self.settings.prompt_draft_model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": self._build_request(prompt, prompt_cases),
                        }
                    ],
                }
            ],
            "stream": stream,
            "text": {
                "format": {
                    "type": "text",
                }
            },
        }

    async def _build_chat_payload(self, prompt: str, stream: bool) -> dict:
        prompt_cases = await retrieve_prompt_cases(prompt)
        return {
            "model": self.settings.prompt_draft_model,
            "messages": [
                {
                    "role": "user",
                    "content": self._build_request(prompt, prompt_cases),
                }
            ],
            "stream": stream,
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
    def _extract_chat_text(data: dict) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list):
            return ""
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
        return ""

    @staticmethod
    def _chat_delta_text(event: dict) -> str:
        choices = event.get("choices")
        if not isinstance(choices, list):
            return ""
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                return delta["content"]
        return ""

    @staticmethod
    def _response_error_detail(response: httpx.Response) -> str:
        text = response.text.strip()
        if not text:
            return "empty response body"
        compact = " ".join(text.split())
        return compact[:240]

    @staticmethod
    async def _iter_sse_json(response: httpx.Response) -> AsyncIterator[dict]:
        data_lines: list[str] = []

        async for line in response.aiter_lines():
            if not line:
                if data_lines:
                    raw = "\n".join(data_lines)
                    data_lines.clear()
                    if raw == "[DONE]":
                        return
                    yield _loads_sse_json(raw)
                continue

            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        if data_lines:
            raw = "\n".join(data_lines)
            if raw != "[DONE]":
                yield _loads_sse_json(raw)

    @staticmethod
    def _event_error_message(event: dict) -> str:
        error = event.get("error")
        if isinstance(error, dict):
            for key in ("message", "code", "type"):
                value = error.get(key)
                if isinstance(value, str) and value:
                    return value
        if isinstance(error, str) and error:
            return error
        return ""
