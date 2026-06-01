import re

from pydantic import BaseModel, Field


class ExtractedCharacterSheet(BaseModel):
    name: str = "主角色"
    identity_anchors: list[str] = Field(default_factory=list)
    visual_traits: dict[str, list[str]] = Field(default_factory=dict)
    locked_prompt_text: str = ""


class CharacterSheetExtractor:
    TRAIT_PATTERNS: dict[str, tuple[str, ...]] = {
        "hair": ("白发", "黑发", "金发", "银发", "红发", "蓝发", "长发", "短发", "卷发", "双马尾"),
        "eyes": ("蓝眼", "绿眼", "红眼", "金色眼睛", "紫色眼睛", "异色瞳"),
        "outfit": ("黑色制服", "白色制服", "校服", "盔甲", "披风", "风衣", "连帽衫", "礼服"),
        "accessories": ("银色耳机", "耳机", "眼镜", "项链", "发卡", "机械臂", "手套"),
        "identity": ("少女", "少年", "女性", "男性", "机器人", "骑士", "魔法师", "侦探"),
    }
    CONSISTENCY_TERMS = ("保持角色一致", "角色一致", "同一个角色", "同一个人", "identity consistency", "same character")

    def extract(self, text: str, *, existing_anchors: list[str] | None = None) -> ExtractedCharacterSheet:
        traits: dict[str, list[str]] = {}
        anchors: list[str] = list(existing_anchors or [])
        for group, terms in self.TRAIT_PATTERNS.items():
            matched = [term for term in terms if term.lower() in text.lower() or term in text]
            if matched:
                traits[group] = matched
                anchors.extend(matched)
        anchors.extend(self._compact_descriptive_phrases(text))
        anchors = list(dict.fromkeys(anchor for anchor in anchors if anchor))[:20]
        locked = "Character identity anchors: " + "; ".join(anchors) if anchors else ""
        return ExtractedCharacterSheet(identity_anchors=anchors, visual_traits=traits, locked_prompt_text=locked)

    def should_extract(self, text: str) -> bool:
        normalized = text.lower()
        return any(term.lower() in normalized or term in text for term in self.CONSISTENCY_TERMS) or bool(self.extract(text).identity_anchors)

    @staticmethod
    def _compact_descriptive_phrases(text: str) -> list[str]:
        phrases: list[str] = []
        for match in re.finditer(r"[^，。；;,.\n]{0,12}(?:角色|少女|少年|人物|同一个人)[^，。；;,.\n]{0,12}", text):
            phrase = match.group(0).strip()
            if 2 <= len(phrase) <= 28:
                phrases.append(phrase)
        return phrases[:4]
