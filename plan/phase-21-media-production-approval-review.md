# Phase 21 Review: Media Production Approval

## Scope

This phase adds a production approval workflow for canvas-native media branches. Designers can approve or revoke edited images and regenerated videos directly from the Inspector, and that approval state is preserved in node payloads and Final JSON lineage.

## Implemented

- Added `CanvasMediaApprovalRequest` with bounded, trimmed approval reason text.
- Added `POST /api/canvases/{canvas_id}/media/{node_id}/approval`.
- Restricted approval mutations to server-managed production media nodes:
  - `edited_image`
  - `generated_video`
- Preserved the existing general PATCH restriction that prevents arbitrary client mutation of production media payloads.
- Added frontend API wrapper `setCanvasMediaApproval(...)`.
- Added Inspector approval/revoke action for approvable production media nodes.
- Added local canvas state update after approval mutation.
- Added approval badges and Inspector fields for approved media.
- Exported approval fields into runtime lineage for edited images and videos:
  - `approval_status`
  - `approved_at`
  - `approval_reason`
- Preserved approval fields in compacted Final JSON media lineage.
- Fixed `branch_audit_trail` payload validation so its specialized schema validation does not incorrectly recurse into audit-entry keys.

## Industrial-grade assessment

This phase moves media branches from generation artifacts toward production decisions. A designer can now mark an edited image or regenerated video as approved without losing graph lineage, and Final JSON can carry those approval decisions downstream. This is important for professional production workflows where many alternatives exist but only approved media should guide delivery.

## Review findings addressed

- Fixed a HIGH payload-validation compatibility issue where `branch_audit_trail` entries were declared valid but rejected by generic recursive payload validation.
- Confirmed media payloads remain server-managed through the general node PATCH route.
- Confirmed the approval endpoint is owner-scoped and only updates edited images / generated videos.

## Static review result

- `code-reviewer`: no CRITICAL/HIGH/MEDIUM issues after fixes.
- `security-reviewer`: no CRITICAL/HIGH/MEDIUM issues.
- `python-reviewer`: no CRITICAL/HIGH/MEDIUM issues after fixes.

## Verification

No pytest, npm build, browser validation, or E2E verification was run, following the standing constraint that tests are not run unless explicitly requested.

## Remaining risks

- Browser validation is still needed before release to confirm approval button states, local canvas refresh behavior, and Final JSON preview display.
- Approval currently writes a fixed reason string from the Inspector action. A future phase should let designers enter a custom approval note.
- Approval is independent from branch governance logs. A future phase should connect media approval to the governance operation timeline for stronger auditability.

## Next recommendation

Proceed to an approval-governance integration phase: add reasoned approval dialogs, persist media approval operations in the branch/governance log, and surface approved production media more prominently in Final JSON preview.
