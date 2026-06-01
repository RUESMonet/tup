import re

from src.agents.quality_reference import QualityReference
from src.agents.text_rendering_rules import TextRenderingRules
from src.models.prompt_skill import ImageActionType, ImageSource, PromptIntent


class IntentClassifier:
    EDIT_TERMS = (
        "修改",
        "改成",
        "换成",
        "替换",
        "去掉",
        "移除",
        "添加",
        "增加",
        "保持",
        "编辑",
        "重绘",
        "局部",
        "edit",
        "replace",
        "remove",
        "add",
        "change",
        "preserve",
    )
    INPAINT_TERMS = ("局部", "圈选", "蒙版", "mask", "inpaint", "inpainting", "重绘")
    OUTPAINT_TERMS = ("扩图", "外扩", "延展", "outpaint", "outpainting", "extend canvas")
    STYLE_TRANSFER_TERMS = ("风格迁移", "变成风格", "改成风格", "style transfer")
    CHARACTER_TERMS = (
        "角色一致",
        "同一个角色",
        "同一个人",
        "保持角色",
        "保持人物",
        "人物不变",
        "identity consistency",
        "same character",
        "same person",
        "consistent character",
    )
    ASPECT_RATIOS = ("1:1", "4:3", "3:4", "16:9", "9:16", "21:9", "2:3", "3:2")

    def classify(
        self,
        prompt: str,
        *,
        source_images: list[ImageSource] | None = None,
        requested_action_type: ImageActionType | None = None,
    ) -> PromptIntent:
        clean_prompt = " ".join(prompt.strip().split())
        normalized = clean_prompt.lower()
        sources = source_images or []
        action_type = requested_action_type or self._infer_action_type(clean_prompt, normalized, sources)
        profile = self._profile(clean_prompt, action_type)
        literals = TextRenderingRules.extract_text_literals(clean_prompt)
        needs_text = TextRenderingRules.detect_text_rendering_need(clean_prompt) or bool(literals)
        character_anchors = self._character_anchors(clean_prompt)
        needs_character = bool(character_anchors) or any(term.lower() in normalized for term in self.CHARACTER_TERMS)
        signals = self._signals(normalized, action_type, profile, bool(sources), needs_text, needs_character)
        confidence = min(1.0, max(0.15, sum(signals.values()) / 7.0))
        short_or_vague = len(clean_prompt) < 8 or clean_prompt in {"猫", "狗", "海报", "头像", "logo", "Logo"}
        return PromptIntent(
            action_type=action_type,
            profile=profile,
            confidence=confidence,
            needs_text_rendering=needs_text,
            needs_character_consistency=needs_character,
            needs_user_clarification=short_or_vague,
            clarifying_questions=self._clarifying_questions(clean_prompt, action_type, short_or_vague),
            detected_text_literals=literals,
            character_anchors=character_anchors,
            aspect_ratio=self._aspect_ratio(clean_prompt),
            edit_instruction=clean_prompt if action_type in self._edit_actions() else None,
            preserve_directives=self._preserve_directives(clean_prompt, action_type, needs_character),
            modify_directives=self._modify_directives(clean_prompt, action_type),
            avoid_directives=self._avoid_directives(action_type, needs_text, needs_character),
            source_image_count=len(sources),
            signals=signals,
        )

    def _infer_action_type(self, prompt: str, normalized: str, sources: list[ImageSource]) -> ImageActionType:
        if any(self._term_matches(prompt, normalized, term) for term in self.OUTPAINT_TERMS):
            return ImageActionType.OUTPAINT
        if any(self._term_matches(prompt, normalized, term) for term in self.INPAINT_TERMS):
            return ImageActionType.INPAINT
        if any(self._term_matches(prompt, normalized, term) for term in self.STYLE_TRANSFER_TERMS):
            return ImageActionType.STYLE_TRANSFER
        if sources and any(self._term_matches(prompt, normalized, term) for term in self.EDIT_TERMS):
            return ImageActionType.EDIT
        if len(sources) > 1:
            return ImageActionType.TEXT_AND_IMAGE_TO_IMAGE
        if len(sources) == 1:
            return ImageActionType.IMAGE_TO_IMAGE
        return ImageActionType.TEXT_TO_IMAGE

    def _profile(self, prompt: str, action_type: ImageActionType) -> str:
        if action_type in self._edit_actions() and any(term in prompt for term in ("人物", "人像", "角色", "同一个人", "保持人物")):
            return "portrait"
        normalized = prompt.lower()
        if any(self._term_matches(prompt, normalized, term) for term in self.CHARACTER_TERMS):
            return "character"
        return QualityReference.select_profile(prompt)

    def _signals(
        self,
        normalized: str,
        action_type: ImageActionType,
        profile: str,
        has_sources: bool,
        needs_text: bool,
        needs_character: bool,
    ) -> dict[str, float]:
        return {
            "action": 2.0 if action_type != ImageActionType.TEXT_TO_IMAGE else 1.0,
            "source_images": 2.0 if has_sources else 0.0,
            "profile": 1.5 if profile != "default" else 0.5,
            "edit_terms": 1.5 if any(self._term_matches(normalized, normalized, term) for term in self.EDIT_TERMS) else 0.0,
            "text_rendering": 1.0 if needs_text else 0.0,
            "character_consistency": 1.0 if needs_character else 0.0,
        }

    def _character_anchors(self, prompt: str) -> list[str]:
        anchors: list[str] = []
        traits = re.findall(r"(?:白发|黑发|金发|银发|蓝眼|绿眼|红眼|长发|短发|双马尾|眼镜|制服|盔甲|披风|耳机|机械臂)", prompt)
        anchors.extend(traits)
        for match in re.finditer(r"(?:保持|同一个|一致)[^，。；;,.\n]{2,28}", prompt):
            anchors.append(match.group(0).strip())
        return list(dict.fromkeys(anchors))[:12]

    def _preserve_directives(self, prompt: str, action_type: ImageActionType, needs_character: bool) -> list[str]:
        directives: list[str] = []
        if action_type in self._edit_actions():
            if "背景" in prompt:
                directives.append("Preserve the foreground subject while applying the requested background change; 背景 may change, the main subject must not drift.")
            directives.append("Preserve all source-image subjects, identity, geometry, lighting direction, and unedited regions unless explicitly changed.")
        if needs_character:
            directives.append("Preserve character identity anchors, facial proportions, outfit, hairstyle, accessories, and age impression across outputs.")
        return directives

    def _modify_directives(self, prompt: str, action_type: ImageActionType) -> list[str]:
        if action_type in self._edit_actions():
            return [f"Apply only this user-requested change: {prompt}"]
        return []

    def _avoid_directives(self, action_type: ImageActionType, needs_text: bool, needs_character: bool) -> list[str]:
        directives = ["Avoid subject drift, unrequested objects, watermarks, low-resolution artifacts, and incoherent composition."]
        if action_type in self._edit_actions():
            directives.append("Avoid replacing the entire source image when only a targeted edit was requested.")
        if needs_text:
            directives.append("Avoid misspelled requested text, garbled letters, and invented extra typography.")
        if needs_character:
            directives.append("Avoid face drift, costume drift, age drift, and inconsistent accessories.")
        return directives

    def _aspect_ratio(self, prompt: str) -> str | None:
        for ratio in self.ASPECT_RATIOS:
            if ratio in prompt:
                return ratio
        if "竖版" in prompt or "手机壁纸" in prompt:
            return "9:16"
        if "横版" in prompt or "电影" in prompt or "分镜" in prompt:
            return "16:9"
        return None

    @staticmethod
    def _term_matches(prompt: str, normalized: str, term: str) -> bool:
        if term.isascii():
            return re.search(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])", normalized) is not None
        return term in prompt

    @staticmethod
    def _clarifying_questions(prompt: str, action_type: ImageActionType, short_or_vague: bool) -> list[str]:
        if not short_or_vague:
            return []
        if action_type == ImageActionType.TEXT_TO_IMAGE:
            return ["希望主体处在什么场景？", "偏写实摄影、插画、海报还是角色设定风格？", "需要指定画幅比例或文字内容吗？"]
        return ["需要保留原图哪些区域？", "要修改的区域和目标效果分别是什么？"]

    @staticmethod
    def _edit_actions() -> set[ImageActionType]:
        return {ImageActionType.EDIT, ImageActionType.INPAINT, ImageActionType.OUTPAINT, ImageActionType.STYLE_TRANSFER}
