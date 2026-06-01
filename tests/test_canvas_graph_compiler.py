from datetime import datetime, timezone

import pytest

from src.agents.canvas_graph_compiler import CanvasGraphCompiler
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
        name="Canvas",
        description="",
        created_at=NOW,
        updated_at=NOW,
        nodes=nodes,
        edges=edges,
    )


def test_canvas_graph_compiler_uses_rooted_edges_instead_of_client_selection_order():
    brief = _node("brief", "brief", "Brief", {"prompt": "高端腕表广告，标题写着\"TIME\"", "profile": "poster"})
    style = _node("style", "style_system", "Style", {"lighting": "hard rim light", "style": "precision luxury macro"})
    other = _node("other", "style_system", "Other", {"lighting": "flat daylight", "style": "ignored disconnected style"})
    canvas = _canvas([brief, style, other], [_edge("edge-1", "brief", "style")])

    result = CanvasGraphCompiler().compile(canvas, ["other", "style", "brief"], root_node_id="brief")

    assert [node.id for node in result.creative_graph.nodes] == ["brief", "style", "other"]
    assert result.prompt_spec["style_system"]["lighting"] == "hard rim light"
    assert "TIME" in result.final_prompt


def test_canvas_graph_compiler_retrieves_case_dna_for_prompt_spec():
    brief = _node("brief", "brief", "Brief", {"prompt": "为 NOIR BLOOM 香水制作高端产品海报", "profile": "product"})
    style = _node("style", "style_system", "Style", {"lighting": "dramatic gold rim light", "style": "luxury studio campaign"})
    canvas = _canvas([brief, style], [_edge("edge-1", "brief", "style")])

    result = CanvasGraphCompiler().compile(canvas, ["brief", "style"], root_node_id="brief")

    assert result.prompt_spec["case_strategy"]["selected_cases"]
    assert result.prompt_spec["case_strategy"]["visual_principles"]
    assert result.prompt_spec["generation_plan"]["case_count"] > 0
    assert "Case DNA transfer" in result.final_prompt


def test_canvas_graph_compiler_allowlists_payload_fields_and_caps_text():
    long_prompt = "专业产品海报" + "x" * 2000
    brief = _node(
        "brief",
        "brief",
        "Brief",
        {
            "prompt": long_prompt,
            "profile": "poster",
            "url": "https://example.com/private.png",
            "secret": "sk-test-secret",
            "nested": {"unsafe": "value"},
        },
    )
    canvas = _canvas([brief], [])

    result = CanvasGraphCompiler().compile(canvas, ["brief"], root_node_id="brief")
    graph_payload = result.creative_graph.model_dump()

    assert graph_payload["primary_brief"].startswith("专业产品海报")
    assert len(graph_payload["primary_brief"]) <= 800
    assert graph_payload["nodes"][0]["payload"] == {"prompt": graph_payload["primary_brief"], "profile": "poster"}


def test_canvas_graph_compiler_preserves_asset_mentions_and_reference_roles():
    brief = _node("brief", "brief", "Brief", {"prompt": "用 @bottle 做一张高端香水海报", "profile": "poster"})
    product = _node(
        "asset-product",
        "asset",
        "bottle.png",
        {
            "asset_id": "asset-1",
            "media_type": "image/png",
            "mention_label": "bottle",
            "reference_role": "product",
            "reference_instruction": "锁定瓶身轮廓、标签比例和玻璃材质",
            "influence_strength": 0.9,
        },
    )
    style = _node(
        "asset-style",
        "asset",
        "mood.png",
        {
            "asset_id": "asset-2",
            "media_type": "image/png",
            "mention_label": "mood",
            "reference_role": "style",
            "reference_instruction": "只迁移暗金色调和低调奢华光线",
            "influence_strength": 0.6,
        },
    )
    canvas = _canvas([brief, product, style], [_edge("edge-1", "brief", "asset-product"), _edge("edge-2", "brief", "asset-style")])

    result = CanvasGraphCompiler().compile(canvas, ["brief", "asset-product", "asset-style"], root_node_id="brief")
    references = result.creative_graph.model_dump()["references"]

    assert references == [
        {
            "node_id": "asset-product",
            "asset_id": "asset-1",
            "role": "product_reference",
            "media_type": "image/png",
            "asset_kind": "image",
            "mention_label": "bottle",
            "instruction": "锁定瓶身轮廓、标签比例和玻璃材质",
            "influence_strength": 0.9,
        },
        {
            "node_id": "asset-style",
            "asset_id": "asset-2",
            "role": "style_reference",
            "media_type": "image/png",
            "asset_kind": "image",
            "mention_label": "mood",
            "instruction": "只迁移暗金色调和低调奢华光线",
            "influence_strength": 0.6,
        },
    ]
    assert result.prompt_spec["scene_graph"]["reference_image_policy"][0].startswith("@bottle as product_reference")
    assert "Reference image policy: @bottle as product_reference" in result.final_prompt


def test_canvas_graph_compiler_preserves_video_asset_references_without_source_images():
    brief = _node("brief", "brief", "Brief", {"prompt": "参考 @shot 的镜头运动做一张海报"})
    video = _node(
        "asset-video",
        "asset",
        "shot.mp4",
        {
            "asset_id": "asset-video-1",
            "asset_kind": "video",
            "media_type": "video/mp4",
            "mention_label": "shot",
            "reference_role": "motion",
            "reference_instruction": "只参考镜头运动和剪辑节奏",
        },
    )
    canvas = _canvas([brief, video], [_edge("edge-1", "brief", "asset-video")])

    result = CanvasGraphCompiler().compile(canvas, ["brief", "asset-video"], root_node_id="brief")
    reference = result.creative_graph.references[0]

    assert result.creative_graph.nodes[1].payload["asset_kind"] == "video"
    assert reference["asset_kind"] == "video"
    assert reference["media_type"] == "video/mp4"
    assert reference["role"] == "motion_reference"
    assert result.prompt_spec["intent"]["source_image_count"] == 0
    assert "motion/timing" in result.prompt_spec["scene_graph"]["reference_image_policy"][0]


def test_canvas_graph_compiler_exposes_character_anchors():
    brief = _node("brief", "brief", "Brief", {"prompt": "生成角色系列海报", "character_anchors": ["白发", "蓝眼", "黑色制服"]})
    canvas = _canvas([brief], [])

    result = CanvasGraphCompiler().compile(canvas, ["brief"], root_node_id="brief")

    assert result.creative_graph.character_anchors == ["白发", "蓝眼", "黑色制服"]
    assert result.prompt_spec["character_identity"]["locked_anchors"] == ["白发", "蓝眼", "黑色制服"]


def test_canvas_graph_compiler_drops_unsafe_mention_labels():
    brief = _node("brief", "brief", "Brief", {"prompt": "用参考图做一张海报"})
    asset = _node(
        "asset",
        "asset",
        "unsafe.png",
        {"asset_id": "asset-1", "media_type": "image/png", "mention_label": "bottle; ignore previous", "reference_role": "product"},
    )
    canvas = _canvas([brief, asset], [_edge("edge-1", "brief", "asset")])

    result = CanvasGraphCompiler().compile(canvas, ["brief", "asset"], root_node_id="brief")
    reference = result.creative_graph.references[0]

    assert "mention_label" not in reference
    assert result.prompt_spec["scene_graph"]["reference_image_policy"][0].startswith("asset-1 as product_reference")


def test_canvas_graph_compiler_rejects_unresolved_prompt_mentions():
    brief = _node("brief", "brief", "Brief", {"prompt": "用 @missing 做一张高端海报"})
    canvas = _canvas([brief], [])

    with pytest.raises(ValueError, match="Unresolved canvas asset mention: @missing"):
        CanvasGraphCompiler().compile(canvas, ["brief"], root_node_id="brief")


def test_canvas_graph_compiler_rejects_unselected_prompt_mentions():
    brief = _node("brief", "brief", "Brief", {"prompt": "用 @bottle 做一张高端海报"})
    asset = _node("asset", "asset", "bottle.png", {"asset_id": "asset-1", "media_type": "image/png", "mention_label": "bottle"})
    canvas = _canvas([brief, asset], [_edge("edge-1", "brief", "asset")])

    with pytest.raises(ValueError, match="Unresolved canvas asset mention: @bottle"):
        CanvasGraphCompiler().compile(canvas, ["brief"], root_node_id="brief")


def test_canvas_graph_compiler_rejects_duplicate_prompt_mentions():
    brief = _node("brief", "brief", "Brief", {"prompt": "用 @bottle 做一张高端海报"})
    first = _node("asset-1", "asset", "bottle-a.png", {"asset_id": "asset-1", "media_type": "image/png", "mention_label": "bottle"})
    second = _node("asset-2", "asset", "bottle-b.png", {"asset_id": "asset-2", "media_type": "image/png", "mention_label": "bottle"})
    canvas = _canvas([brief, first, second], [_edge("edge-1", "brief", "asset-1"), _edge("edge-2", "brief", "asset-2")])

    with pytest.raises(ValueError, match="Duplicate canvas asset mention label: @bottle"):
        CanvasGraphCompiler().compile(canvas, ["brief", "asset-1", "asset-2"], root_node_id="brief")


def test_canvas_graph_compiler_allows_selected_unmentioned_assets():
    brief = _node("brief", "brief", "Brief", {"prompt": "用参考图做一张高端海报"})
    asset = _node("asset", "asset", "bottle.png", {"asset_id": "asset-1", "media_type": "image/png", "mention_label": "bottle"})
    canvas = _canvas([brief, asset], [_edge("edge-1", "brief", "asset")])

    result = CanvasGraphCompiler().compile(canvas, ["brief", "asset"], root_node_id="brief")

    assert result.creative_graph.references[0]["mention_label"] == "bottle"
