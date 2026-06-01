# Phase 20 Review: Media Branch Comparison

## Scope

This phase adds a professional before/after review layer for canvas-native media branches. The goal is to make edited images and regenerated videos inspectable without opening raw JSON or separate tabs.

## Implemented

- Added `MediaBranchComparison` to the canvas Inspector.
- Edited image nodes now show a before/source image, optional mask image, and after/result image in one compact comparison panel.
- Generated video nodes now show the source frame and regenerated video output side by side.
- The comparison panel reuses the existing safe `MediaPreview` component and asset map.
- Added source/mask/result visual roles for the comparison cards.
- Added dedicated Inspector styling for source/result/mask comparison blocks.
- Hardened `safeDisplayUrl()` so arbitrary cross-origin HTTPS media URLs no longer flow into image/video previews.

## Industrial-grade assessment

This phase improves review ergonomics for professional designers. A designer can now select a media result on the canvas and immediately understand what it came from, what changed, and which mask or source frame was involved. This makes the canvas feel closer to a production review surface rather than a generic node editor.

## Review findings addressed

- Fixed unsafe media URL handling by rejecting arbitrary cross-origin HTTPS URLs in canvas media previews.
- Confirmed comparison UI remains valid when unsafe URLs are rejected because `MediaPreview` falls back to a non-network placeholder.

## Static review result

- `code-reviewer`: no CRITICAL/HIGH/MEDIUM issues after fixes.
- `security-reviewer`: no CRITICAL/HIGH/MEDIUM issues after fixes.

## Verification

No pytest, npm build, browser validation, or E2E verification was run, following the standing constraint that tests are not run unless explicitly requested.

## Remaining risks

- Browser validation is still needed before release to confirm the comparison panel layout under real source/mask/result asset combinations.
- The comparison panel is visual and metadata-based; it does not yet compute pixel-level or semantic visual diffs.

## Next recommendation

Proceed to a production-path approval workflow for media branches: allow designers to mark an edited image or regenerated video as approved, expose approved media in Final JSON more prominently, and connect approval decisions to the branch governance log.
