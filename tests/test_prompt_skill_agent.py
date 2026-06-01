import pytest

from src.agents.prompt_skill_agent import PromptSkillAgent
from src.models.prompt_skill import ImageActionType, ImageSource, PromptSkillRequest


@pytest.mark.asyncio
async def test_prompt_skill_agent_preserves_original_subject_and_entities():
    response = await PromptSkillAgent().optimize(
        PromptSkillRequest(prompt="创作一张超写实海报，主体是 iPhone Air，位于高山草甸中央。")
    )

    serialized = response.model_dump_json()
    assert response.intent.action_type == ImageActionType.TEXT_TO_IMAGE
    assert "iPhone Air" in serialized
    assert "高山草甸" in serialized
    assert "藤蔓" not in serialized
    assert response.final_english_prompt
    assert response.reference_usage.matched_cases


@pytest.mark.asyncio
async def test_prompt_skill_agent_adds_text_rendering_policy():
    response = await PromptSkillAgent().optimize(
        PromptSkillRequest(prompt='做一张咖啡店海报，标题写着"SUMMER LATTE"')
    )

    assert response.intent.needs_text_rendering is True
    assert "SUMMER LATTE" in response.final_english_prompt
    assert "clear readable typography" in response.final_english_prompt
    assert any("文字" in item or "typography" in item for item in response.quality_gates)


@pytest.mark.asyncio
async def test_prompt_skill_agent_builds_edit_policy_for_source_image():
    response = await PromptSkillAgent().optimize(
        PromptSkillRequest(
            prompt="把这张图背景换成星空，保持人物不变",
            source_images=[ImageSource(url="/uploads/image-optimizer/person.png", role="source")],
        )
    )

    assert response.intent.action_type == ImageActionType.EDIT
    assert response.optimized_prompt["task"] == "image_edit"
    assert any("preserve" in item.lower() for item in response.edit_policy["preserve"])
    assert "星空" in response.final_english_prompt


def test_prompt_skill_request_rejects_missing_prompt():
    with pytest.raises(ValueError):
        PromptSkillRequest(prompt="")


def test_prompt_skill_request_requires_source_for_explicit_edit_action():
    with pytest.raises(ValueError):
        PromptSkillRequest(prompt="把背景换成雪山", action_type=ImageActionType.EDIT)


def test_prompt_skill_request_requires_mask_for_inpaint_action():
    with pytest.raises(ValueError):
        PromptSkillRequest(
            prompt="局部重绘衣服颜色",
            action_type=ImageActionType.INPAINT,
            source_images=[ImageSource(url="/uploads/image-optimizer/person.png")],
        )
