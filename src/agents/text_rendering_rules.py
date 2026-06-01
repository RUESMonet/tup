from copy import deepcopy
import re
from typing import Any


class TextRenderingRules:
    TEXT_MARKERS = (
        "logo",
        "brand",
        "label",
        "typography",
        "text",
        "word",
        "says",
        "title",
        "subtitle",
        "ui copy",
        "标志",
        "名称",
        "文字",
        "标签",
        "品牌",
        "字样",
        "字体",
        "标题",
        "副标题",
        "文案",
        "按钮",
        "招牌",
        "写着",
        "写上",
    )
    CN_LITERAL_PATTERNS = (
        r"(?:标题|副标题|按钮文字|文字|文案|字样|logo|Logo|LOGO|品牌|名称)\s*(?:写着|写上|为|是|：|:)\s*([^，。；;,.\n]+)",
        r"(?:says|text|title|subtitle|logo)\s*(?:is|as|:)?\s*['\"]?([^'\"，。；;,.\n]{2,})",
    )

    @classmethod
    def detect_text_rendering_need(cls, prompt: str) -> bool:
        normalized = prompt.lower()
        return any(cls._marker_matches(prompt, normalized, marker) for marker in cls.TEXT_MARKERS)

    @classmethod
    def extract_text_literals(cls, prompt: str) -> list[str]:
        literals: list[str] = []
        for match in re.finditer(r"[\"“”']([^\"“”']{2,80})[\"“”']", prompt):
            literals.append(match.group(1).strip())
        for pattern in cls.CN_LITERAL_PATTERNS:
            for match in re.finditer(pattern, prompt, flags=re.IGNORECASE):
                candidate = cls._clean_literal(match.group(1))
                if candidate:
                    literals.append(candidate)
        return list(dict.fromkeys(literals))[:8]

    @classmethod
    def apply_constraints(cls, payload: dict[str, Any], literals: list[str]) -> dict[str, Any]:
        enriched = deepcopy(payload)
        prompt_payload = enriched.setdefault("prompt", {})
        existing = prompt_payload.get("text_and_logo_constraints")
        requested = ", ".join(f'"{literal}"' for literal in literals)
        if requested:
            constraint = (
                f"Render only the explicitly requested text: {requested}; use clear readable typography, exact spelling, stable baseline, "
                "proper kerning, and placement that matches the layout; do not invent extra text, fake letters, watermarks, or unrelated logos."
            )
        else:
            constraint = (
                "If text is required by the prompt, render it with exact spelling, clear readable typography, stable baseline, and no fake letters; "
                "otherwise do not add decorative text, watermarks, random labels, or unrelated logos."
            )
        prompt_payload["text_and_logo_constraints"] = cls._merge_text(existing, constraint)
        negatives = prompt_payload.get("negative_prompt")
        prompt_payload["negative_prompt"] = cls._merge_negative(negatives)
        return enriched

    @staticmethod
    def _marker_matches(prompt: str, normalized: str, marker: str) -> bool:
        if marker.isascii():
            return re.search(rf"(?<![a-z0-9]){re.escape(marker.lower())}(?![a-z0-9])", normalized) is not None
        return marker in prompt

    @staticmethod
    def _clean_literal(value: str) -> str:
        cleaned = value.strip().strip("：:，,。.;； ")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned if 1 < len(cleaned) <= 80 else ""

    @staticmethod
    def _merge_text(existing: Any, constraint: str) -> str | list[str]:
        if isinstance(existing, str) and existing.strip():
            return f"{existing.strip()} {constraint}"
        if isinstance(existing, list):
            return [*existing, constraint]
        return constraint

    @staticmethod
    def _merge_negative(value: Any) -> list[str]:
        base: list[str] = []
        if isinstance(value, str) and value.strip():
            base.append(value)
        elif isinstance(value, list):
            base.extend(item for item in value if isinstance(item, str) and item.strip())
        base.extend(["garbled text", "misspelled requested text", "extra random letters", "fake typography"])
        return list(dict.fromkeys(base))
