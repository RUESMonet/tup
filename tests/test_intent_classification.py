from src.agents.intent_classifier import IntentClassifier
from src.models.prompt_skill import ImageActionType, ImageSource


def test_intent_classifier_detects_edit_with_source_image():
    intent = IntentClassifier().classify(
        "把这张图背景换成星空，保持人物不变",
        source_images=[ImageSource(url="/uploads/image-optimizer/source.png")],
    )

    assert intent.action_type == ImageActionType.EDIT
    assert intent.profile == "portrait"
    assert intent.edit_instruction
    assert "背景" in intent.preserve_directives[0]


def test_intent_classifier_detects_text_rendering_and_literals():
    intent = IntentClassifier().classify('做一张咖啡店海报，标题写着"SUMMER LATTE"，副标题是新品上市')

    assert intent.action_type == ImageActionType.TEXT_TO_IMAGE
    assert intent.profile == "poster"
    assert intent.needs_text_rendering is True
    assert "SUMMER LATTE" in intent.detected_text_literals
    assert intent.confidence >= 0.5


def test_intent_classifier_detects_character_consistency():
    intent = IntentClassifier().classify("保持同一个白发蓝眼角色一致，生成三张不同场景")

    assert intent.needs_character_consistency is True
    assert intent.profile == "character"
    assert any("白发" in anchor or "蓝眼" in anchor for anchor in intent.character_anchors)


def test_intent_classifier_prioritizes_storyboard_over_poster():
    intent = IntentClassifier().classify("生成一个电影海报式 16:9 分镜制作板，包含镜头表和角色动线")

    assert intent.profile == "storyboard"


def test_intent_classifier_marks_short_prompt_for_clarification():
    intent = IntentClassifier().classify("猫")

    assert intent.action_type == ImageActionType.TEXT_TO_IMAGE
    assert intent.profile == "default"
    assert intent.needs_user_clarification is True
    assert intent.clarifying_questions
