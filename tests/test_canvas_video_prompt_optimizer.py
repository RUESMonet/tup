from src.agents.canvas_graph_compiler import CanvasCompileProduct, CreativeGraph
from src.agents.canvas_video_prompt_optimizer import build_storyboard_video_prompt
from src.models.canvas import CanvasNodeResponse


def _node(payload: dict) -> CanvasNodeResponse:
    return CanvasNodeResponse(
        id="node-1",
        canvas_id="canvas-1",
        type="storyboard",
        title="Shot 01",
        position={"x": 0, "y": 0},
        size={"width": 280, "height": 160},
        payload=payload,
        created_at="2026-05-21T00:00:00Z",
        updated_at="2026-05-21T00:00:00Z",
    )


def _compiled() -> CanvasCompileProduct:
    return CanvasCompileProduct(
        creative_graph=CreativeGraph(
            canvas_id="canvas-1",
            project_id="project-1",
            primary_brief="Compiled canvas prompt for a perfume hero frame",
            nodes=[],
            edges=[],
        ),
        prompt_spec={"task": "storyboard_video"},
        final_prompt="Compiled canvas prompt for a perfume hero frame",
    )


def test_video_prompt_optimizer_uses_storyboard_motion_fields():
    draft = build_storyboard_video_prompt(
        _node(
            {
                "scene": "black gold studio",
                "camera_motion": "slow dolly in",
                "subject_action": "perfume bottle stays stable while highlights move",
                "shot_size": "medium close-up",
                "temporal_rhythm": "calm commercial pacing",
                "ending_state": "clean hero frame",
                "duration": "5",
                "aspect_ratio": "16:9",
            }
        ),
        _compiled(),
        {"candidate_id": "candidate-1", "prompt": "crisp product image", "score": 8.7},
        duration=5,
        aspect_ratio="16:9",
    )

    assert "slow dolly in" in draft.final_prompt
    assert "perfume bottle stays stable" in draft.final_prompt
    assert "clean hero frame" in draft.final_prompt
    assert draft.video_report["score"] >= 8.0
    assert draft.source_context["candidate_id"] == "candidate-1"


def test_video_prompt_optimizer_degrades_with_sparse_storyboard_fields():
    draft = build_storyboard_video_prompt(
        _node({"prompt": "minimal product motion"}),
        _compiled(),
        {},
        duration=None,
        aspect_ratio=None,
    )

    assert "minimal product motion" in draft.final_prompt
    assert "steady motion" in draft.final_prompt
    assert draft.video_report["missing"]


def test_video_prompt_optimizer_bounds_oversized_storyboard_text():
    draft = build_storyboard_video_prompt(
        _node(
            {
                "prompt": "x" * 13000,
                "camera_motion": "slow dolly in",
                "subject_action": "stable product motion",
                "shot_size": "medium close-up",
                "temporal_rhythm": "calm pacing",
                "ending_state": "clean hero frame",
            }
        ),
        _compiled(),
        {"candidate_id": "candidate-1", "prompt": "crisp product image", "score": 8.7},
        duration=5,
        aspect_ratio="16:9",
    )

    assert len(draft.final_prompt) <= 12000
    assert "slow dolly in" in draft.final_prompt
    assert "clean hero frame" in draft.final_prompt
