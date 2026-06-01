from src.agents.optimization_guide import OptimizationGuideBuilder


def test_optimization_guide_uses_missing_dimensions_and_candidates():
    reference_payload = {
        "quality": {
            "profile": "product",
            "matched_dimensions": ["subject"],
            "missing_dimensions": ["lighting", "composition", "constraints"],
            "score": 4.5,
        },
        "optimization_hints": [
            "补充主光、辅光、氛围光、阴影或时间段，让模型稳定控制画面情绪。",
            "补充镜头、景别、构图、焦点层级或留白要求，减少随机构图。",
        ],
        "candidate_prompts": [
            {"id": "original", "title": "原始提示词"},
            {
                "id": "product_subject_anchor",
                "title": "主体锚定",
                "summary": {"主体": "透明香水瓶", "文字/logo": "避免标签变形"},
            },
        ],
    }

    guide = OptimizationGuideBuilder().build("一张香水产品图", reference_payload)
    payload = guide.model_dump(mode="json")

    assert payload["summary"].startswith("当前提示词适合 product 方向")
    assert [issue["dimension"] for issue in payload["issues"]] == ["lighting", "composition", "constraints"]
    assert payload["issues"][0]["severity"] == "high"
    assert payload["actions"][0]["title"] == "补充光影与氛围"
    assert "主体锚定" in payload["actions"][-1]["example"]
    assert "先应用评分最高的候选提示词" in payload["next_steps"]


def test_optimization_guide_recommends_highest_scored_candidate():
    reference_payload = {
        "quality": {
            "profile": "product",
            "matched_dimensions": ["subject"],
            "missing_dimensions": ["lighting"],
        },
        "candidate_prompts": [
            {"id": "original", "title": "原始提示词", "estimated_score": 0},
            {"id": "low", "title": "低分方案", "estimated_score": 6.2},
            {"id": "high", "title": "高分方案", "estimated_score": 8.9, "summary": {"光影": "柔和棚拍"}},
        ],
    }

    guide = OptimizationGuideBuilder().build("一张香水产品图", reference_payload)
    candidate_action = guide.actions[-1]

    assert candidate_action.title == "套用候选提示词"
    assert "高分方案" in candidate_action.example


def test_optimization_guide_returns_stable_shape_for_strong_prompt():
    reference_payload = {
        "quality": {
            "profile": "poster",
            "matched_dimensions": ["subject", "style", "lighting", "composition", "constraints"],
            "missing_dimensions": [],
            "score": 8.0,
        },
        "optimization_hints": [],
        "candidate_prompts": [],
    }

    guide = OptimizationGuideBuilder().build(
        "未来城市旅游海报，cinematic illustration，neon lighting，dynamic composition，negative prompt: watermark",
        reference_payload,
    )
    payload = guide.model_dump(mode="json")

    assert payload["summary"] == "当前提示词结构较完整，可以直接生成并根据视觉评分做小幅迭代。"
    assert payload["issues"] == []
    assert payload["actions"][0]["title"] == "直接生成并观察评分"
    assert payload["next_steps"] == ["生成图片后查看视觉评分最低项", "只针对低分项补充约束，避免一次改动过多"]


def test_optimization_guide_handles_missing_payload_fields():
    guide = OptimizationGuideBuilder().build("一只橘猫坐在窗台上", {})
    payload = guide.model_dump(mode="json")

    assert payload["summary"]
    assert payload["issues"]
    assert payload["actions"]
    assert payload["next_steps"]
