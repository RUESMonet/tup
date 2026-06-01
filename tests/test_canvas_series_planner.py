from datetime import datetime, timezone

from src.agents.canvas_graph_compiler import CanvasGraphCompiler
from src.agents.canvas_series_planner import CanvasSeriesPlanner
from src.models.canvas import CanvasDetailResponse, CanvasEdgeResponse, CanvasNodeResponse, CanvasPosition, CanvasSize


NOW = datetime(2026, 5, 19, tzinfo=timezone.utc)


def _node(node_id: str, node_type: str, title: str, payload: dict):
    return CanvasNodeResponse(
        id=node_id,
        canvas_id="canvas-1",
        type=node_type,
        title=title,
        position=CanvasPosition(x=0, y=0),
        size=CanvasSize(width=320, height=180),
        payload=payload,
        created_at=NOW,
        updated_at=NOW,
    )


def _edge(edge_id: str, source_id: str, target_id: str, edge_type: str = "influences"):
    return CanvasEdgeResponse(
        id=edge_id,
        canvas_id="canvas-1",
        source_node_id=source_id,
        target_node_id=target_id,
        type=edge_type,
        payload={"weight": 0.8},
        created_at=NOW,
    )


def _canvas(nodes: list[CanvasNodeResponse], edges: list[CanvasEdgeResponse]):
    return CanvasDetailResponse(
        id="canvas-1",
        project_id="project-1",
        name="Campaign Canvas",
        description="",
        created_at=NOW,
        updated_at=NOW,
        nodes=nodes,
        edges=edges,
    )


def test_canvas_series_planner_preserves_character_style_references_and_text():
    brief = _node(
        "brief",
        "brief",
        "Series brief",
        {
            "prompt": "为同一个白发蓝眼角色制作高端香水系列广告，主标题写着\"NOIR BLOOM\"",
            "profile": "campaign_series",
            "character_anchors": ["白发", "蓝眼", "黑色制服"],
            "text_literals": ["NOIR BLOOM"],
        },
    )
    style = _node(
        "style",
        "style_system",
        "Luxury noir style",
        {"style": "premium fragrance campaign", "lighting": "dramatic gold rim light", "color_palette": "black, gold, deep amber"},
    )
    product = _node(
        "product",
        "asset",
        "Bottle reference",
        {"asset_id": "asset-1", "media_type": "image/png", "mention_label": "bottle", "reference_role": "product", "reference_instruction": "锁定瓶身轮廓和标签比例"},
    )
    character = _node(
        "character",
        "asset",
        "Character reference",
        {"asset_id": "asset-2", "media_type": "image/png", "mention_label": "hero", "reference_role": "character", "reference_instruction": "保持同一人物脸型、发型和制服"},
    )
    canvas = _canvas([brief, style, product, character], [_edge("edge-1", "brief", "style"), _edge("edge-2", "brief", "product"), _edge("edge-3", "brief", "character")])
    compiled = CanvasGraphCompiler().compile(canvas, [brief.id, style.id, product.id, character.id], profile="campaign_series")

    plan = CanvasSeriesPlanner().plan(compiled, frame_count=4)

    assert plan.character_lock == ["白发", "蓝眼", "黑色制服"]
    assert plan.style_lock["lighting"] == "dramatic gold rim light"
    assert plan.style_lock["style"] == "premium fragrance campaign"
    assert plan.reference_policy[0].startswith("@bottle as product_reference")
    assert plan.reference_policy[1].startswith("@hero as character_reference")
    assert plan.text_literals == ["NOIR BLOOM"]
    assert len(plan.frames) == 4
    assert [frame.index for frame in plan.frames] == [1, 2, 3, 4]
    assert len({frame.prompt for frame in plan.frames}) == 4
    for frame in plan.frames:
        assert "白发" in frame.prompt
        assert "蓝眼" in frame.prompt
        assert "dramatic gold rim light" in frame.prompt
        assert "NOIR BLOOM" in frame.prompt
        assert "@bottle as product_reference" in frame.prompt


def test_canvas_series_planner_clamps_frame_count_and_is_deterministic():
    brief = _node("brief", "brief", "Brief", {"prompt": "制作一组产品系列图", "character_anchors": ["银色耳机"], "style": "clean editorial"})
    canvas = _canvas([brief], [])
    compiled = CanvasGraphCompiler().compile(canvas, [brief.id])
    planner = CanvasSeriesPlanner()

    lower = planner.plan(compiled, frame_count=1)
    upper = planner.plan(compiled, frame_count=12)
    repeated = planner.plan(compiled, frame_count=8)

    assert len(lower.frames) == 3
    assert len(upper.frames) == 8
    assert upper.model_dump() == repeated.model_dump()


def test_canvas_series_planner_does_not_leak_unsafe_payload_fields():
    brief = _node(
        "brief",
        "brief",
        "Brief",
        {
            "prompt": "产品系列视觉",
            "secret": "sk-test-secret",
            "url": "https://example.com/private.png",
            "nested": {"unsafe": "value"},
        },
    )
    canvas = _canvas([brief], [])
    compiled = CanvasGraphCompiler().compile(canvas, [brief.id])

    plan = CanvasSeriesPlanner().plan(compiled, frame_count=3)
    serialized = str(plan.model_dump())

    assert "sk-test-secret" not in serialized
    assert "private.png" not in serialized
    assert "unsafe" not in serialized
