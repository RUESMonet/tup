from src.agents.character_sheet import CharacterSheetExtractor
from src.agents.prompt_skill_agent import PromptSkillAgent
from src.models.prompt_skill import PromptSkillRequest


def test_character_sheet_extractor_locks_visual_traits():
    sheet = CharacterSheetExtractor().extract("一个白发蓝眼、黑色制服、戴银色耳机的少女角色，保持角色一致")

    assert "白发" in sheet.identity_anchors
    assert "蓝眼" in sheet.identity_anchors
    assert "黑色制服" in sheet.identity_anchors
    assert "银色耳机" in sheet.identity_anchors
    assert "白发" in sheet.locked_prompt_text


async def test_prompt_skill_agent_uses_conversation_character_context():
    response = await PromptSkillAgent().optimize(
        PromptSkillRequest(
            prompt="换到雨夜街头，镜头更近一点",
            conversation_context=[{"role": "user", "content": "白发蓝眼黑色制服银色耳机少女，保持角色一致"}],
            character_anchors=["白发", "蓝眼", "黑色制服", "银色耳机"],
        )
    )

    assert response.intent.needs_character_consistency is True
    assert "白发" in response.final_english_prompt
    assert "银色耳机" in response.final_english_prompt
