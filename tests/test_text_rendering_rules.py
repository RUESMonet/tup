from src.agents.text_rendering_rules import TextRenderingRules


def test_extract_text_literals_from_quotes_and_cn_patterns():
    literals = TextRenderingRules.extract_text_literals('海报标题写着"SUMMER LATTE"，按钮文字为立即购买，logo 是 ACME')

    assert "SUMMER LATTE" in literals
    assert "立即购买" in literals
    assert "ACME" in literals


def test_text_rendering_constraints_quote_requested_text_only():
    payload = {"prompt": {"subject": "咖啡店夏季海报，标题写着 SUMMER LATTE"}}

    enriched = TextRenderingRules.apply_constraints(payload, ["SUMMER LATTE"])

    constraints = enriched["prompt"]["text_and_logo_constraints"]
    assert '"SUMMER LATTE"' in constraints
    assert "do not invent extra text" in constraints
    assert "clear readable typography" in constraints


def test_text_rendering_constraints_do_not_mutate_original_payload():
    payload = {"prompt": {"subject": "一只猫"}}

    enriched = TextRenderingRules.apply_constraints(payload, ["CAT CAFE"])

    assert "text_and_logo_constraints" not in payload["prompt"]
    assert enriched["prompt"]["subject"] == "一只猫"


def test_detect_text_rendering_need_avoids_unrelated_prompt():
    assert TextRenderingRules.detect_text_rendering_need("一只橘猫坐在窗台上") is False
    assert TextRenderingRules.detect_text_rendering_need("ultra detailed fabric texture photo") is False
    assert TextRenderingRules.detect_text_rendering_need("生成带有 logo 和标题的产品海报") is True
