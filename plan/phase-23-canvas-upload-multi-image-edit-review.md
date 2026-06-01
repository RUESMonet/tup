# Phase 23 — Canvas Upload and Multi-Image Edit Review

## Scope completed

- Canvas-native media upload is available from the Creative Canvas command panel.
- Uploaded images and videos are immediately materialized as canvas `asset` nodes.
- Uploaded/asset-library media are inserted into the brief as `@` references.
- Asset nodes carry production context: asset id, media type, mention label, reference role, reference instruction, and image/video URL.
- The upload/materialization flow is isolated in `useCanvasAssetUpload` instead of further enlarging the workspace controller.
- Batch uploads snapshot reference role and instruction so one upload action has stable metadata.
- The `@` mention popup now exposes combobox/listbox semantics for assistive technology.
- Canvas image edit supports multiple source images from the selected graph and `@` image references.
- Image edit requests send multiple source nodes/assets, up to the backend limit of 8 source images.
- Backend image-edit validation canonicalizes source image assets from selected source nodes before task creation.
- Image `asset` nodes are recognized as legitimate image-edit sources in both API validation and repository persistence.
- Inpaint masks must be part of the selected edit graph and are excluded from source image assets.
- The image edit dialog shows the participating source images before submission.
- Selected images are protected from rejection when they have production media descendants or pre-materialized repair evaluation/prompt branches.
- Repair branch summaries preserve negative score deltas instead of dropping regressions.

## Industrial-readiness review

This phase closes the gap between “asset library exists beside the canvas” and “assets are first-class canvas objects.” Designers can now upload or reference multiple media files directly inside the creative graph, use `@` to bind them to briefs and prompts, and launch image edits from the graph rather than a separate tag-like panel.

The important backend integrity improvement is that multi-image edit provenance is now server-derived:

- client-submitted source image asset lists must match the canonical assets bound to selected source nodes;
- mask assets must be present in the selected edit graph;
- image asset nodes are accepted consistently at route and repository boundaries;
- archived repair branch protections still apply before expensive work starts;
- repair branch source images remain protected even before materialization.

## Static review results

Final static review agents reported no CRITICAL, HIGH, or MEDIUM findings:

- code-reviewer: pass
- security-reviewer: pass
- python-reviewer: pass

No pytest, npm build, browser validation, or E2E was run because the standing user constraint says not to run tests unless explicitly requested.

## Remaining recommendations

- If the user asks for verification, run `.venv/bin/python -m pytest tests/test_canvas_routes.py` and a frontend build.
- Browser validation should cover multi-file upload, `@` autocomplete insertion, multi-image edit source cards, inpaint mask selection, edited result node creation, and repair branch rejection protection.
- The next product phase should connect the prompt beautifier case library to Prompt Program generation so `@` references and retrieved high-quality cases shape professional prompts before image generation.
