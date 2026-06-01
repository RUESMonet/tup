# Phase 22 — Approval Governance Integration Review

## Scope completed

- Media approval and revoke now require a designer reason through a dedicated dialog.
- Approval and revoke are stored as branch governance operations, not just media payload changes.
- Approval payload updates and branch operation inserts are atomic.
- Branch governance now includes approve, revoke, select, reject, candidate, pin, unpin, archive, restore, and materialize operation types.
- Repair branch materialize/status/pin/unpin mutations write governance logs in the same repository transaction.
- Explicit unpin is available through API and UI.
- Candidate select/reject/candidate transitions require reasons and write governance logs.
- Production media approval rejects descendants governed by archived repair branches.
- Server-managed production media nodes, media payloads, and production lineage edges remain protected from generic node/edge APIs.
- Final JSON production lineage includes approved production media, approval summary, generated image lineage, scoped branch operation summaries, and compacted operation payloads.
- Final JSON lineage computes branch operation summaries from scoped lineage operations instead of relying on the bounded canvas detail payload.
- Branch Governance Console can filter and summarize the expanded governance taxonomy.
- Candidate governance labels fall back to candidate/asset IDs when no target node exists.

## Industrial-readiness review

This phase moved approval from a UI-level state toggle to an auditable governance event model. The design now treats production media approval, candidate selection, repair branch lifecycle, and primary path control as governed operations with explicit reasons, actor metadata, operation payloads, and lineage-safe constraints.

The important depth improvement is that governance integrity is enforced server-side:

- client payloads cannot forge approval fields or production media roles;
- generic graph APIs cannot create/delete server-managed media lineage;
- archived repair descendants cannot be promoted through approval;
- source and mask assets must be bound to selected canvas nodes;
- final artifacts preserve compact but reviewable production lineage.

## Static review results

Final static review agents reported no CRITICAL, HIGH, or MEDIUM findings:

- code-reviewer: pass
- security-reviewer: pass
- python-reviewer: pass

No pytest, npm build, browser validation, or E2E was run because the standing user constraint says not to run tests unless explicitly requested.

## Remaining recommendations

- If the user asks for verification, run `.venv/bin/python -m pytest tests/test_canvas_routes.py` and a frontend build.
- Browser validation should cover approval/revoke dialog focus behavior, Branch Governance filters, explicit unpin, candidate governance display, and Final JSON approved media preview.
- If governance history grows very large, consider adding SQL indexes for branch operation `canvas_id`, `operation`, `target_node_id`, and created-at ordering.
