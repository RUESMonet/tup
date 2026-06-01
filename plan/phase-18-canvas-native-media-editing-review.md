# Phase 18 Review: Canvas-native Image Editing & Video Regeneration

## Scope

This phase closes the missing canvas-native media editing loop: selected media nodes can now launch image editing or video regeneration from inside the canvas, and the resulting media is written back as new non-destructive graph nodes with auditable lineage.

## Implemented

- Added/verified canvas-scoped image edit flow at `POST /api/canvases/{canvas_id}/generate/image-edit`.
- Validated image edit source nodes belong to the current canvas.
- Enforced that `source_image_asset_ids` are bound to selected non-archived canvas source nodes.
- Allowed `mask_asset_id` for inpaint without requiring the mask to be node-bound.
- Validated `mask_asset_id` as same owner/project image at route and repository levels.
- Created `edited_image` result nodes with `canvas_image_edit` payload source.
- Created `image_edit` edges from source nodes to edited image result nodes.
- Persisted edited image asset metadata with source nodes, source assets, optional mask asset, task id, and action type.
- Added repository-level defense-in-depth checks for image edit source assets and video source assets before persisting result lineage.
- Preserved edited-image `source_node_ids`, `source_asset_ids`, and `mask_asset_id` in runtime and compacted Final JSON lineage.
- Verified frontend already exposes canvas-native image edit and video remix dialogs.
- Added inpaint mask selection to the canvas image edit dialog and submit payload.
- Confirmed video remix uses the existing canvas video endpoint and clearly presents the interaction as regeneration from the original source image, not direct video-file editing.

## Industrial-grade assessment

This phase is a real workflow upgrade, not just UI decoration. Media edits now behave as versioned graph branches: the original node remains intact, the edited output becomes a new node, and source/mask/task provenance is preserved through Final JSON. That is the right model for professional design work because it supports reviewability, rollback, branching, and production audit trails.

## Review findings addressed

- Fixed persisted Final JSON lineage dropping edited-image source information.
- Added repository-level asset ownership/project validation for persisted image/video lineage.
- Added canvas UI support for inpaint mask selection.
- Fixed inpaint auditability by threading `mask_asset_id` through task execution, asset metadata, node payload, edge payload, runtime lineage, and compacted artifact lineage.

## Static review result

- `code-reviewer`: no CRITICAL/HIGH/MEDIUM issues after fixes.
- `security-reviewer`: no CRITICAL/HIGH/MEDIUM issues after fixes.
- `python-reviewer`: no CRITICAL/HIGH/MEDIUM issues on the Python media edit path before final mask-lineage follow-up; final follow-up was re-reviewed by code/security reviewers.

## Verification

No pytest, npm build, browser validation, or E2E verification was run, following the standing constraint that tests are not run unless explicitly requested.

## Remaining risks

- Browser validation is still needed before release to confirm dialog focus trap, mask select usability, polling completion, and Final JSON preview behavior.
- The current video feature is regeneration/remix from source image, not direct timeline editing or video-to-video repair. The UI copy intentionally avoids over-promising direct video-file editing.
- Mask authoring itself is not implemented; the user must already have a mask image asset in the project.

## Next recommendation

Proceed to a visual/interaction refinement phase for the canvas-native media editing experience: better edited-image node affordances, explicit media branch comparison, stronger lineage visualization, and a more professional mask/repair workflow for designers.
