# Professional Canvas SaaS Design

## Context

The product will evolve the existing local image generation optimizer into a public SaaS for AI creators and studios. The reference direction is a LibTV-like professional canvas workflow, but the implementation must be a second-stage development of the current FastAPI + React/Vite codebase, not a rebuild.

The current project already contains useful foundations:

- Image prompt pre-evaluation, structured prompt optimization, visual scoring, generation iteration, and optimization traces.
- Project, canvas, asset, auth, conversation, generation, video, model settings, and admin modules.
- User/session authentication, project isolation, private asset serving, upload limits, and model configuration boundaries.
- Backend tests around API behavior, prompt evaluation, model routing, canvas behavior, projects, auth, and video routing.

## Product Goal

Build a professional canvas workbench for AI creators and studios where users can manage creative projects and complete a storyboard-level image-to-video workflow:

> creative idea / script -> storyboard -> image prompt optimization and scoring -> reference image generation -> video prompt optimization and scoring -> image-to-video generation -> result review and iteration

The first phase should support public SaaS basics: accounts, project isolation, credits/quotas, review/admin workflows, and model configuration. It should not attempt to deliver a complete video editing suite or public community in the first phase.

## Target Users

The first phase targets AI creators and small studios that need controlled, repeatable production workflows rather than one-click novelty generation.

Primary user needs:

- Organize work by projects and canvas boards.
- Break ideas into storyboard-level units.
- Reuse local prompt scoring and optimization logic.
- Generate consistent reference images and short image-to-video clips.
- Track versions, prompts, model parameters, scores, and generated assets.
- Control generation cost through visible credits and quotas.

## Design Principles

1. Reuse existing code first.
   - Extend the existing FastAPI backend and React/Vite frontend.
   - Reuse current project, canvas, auth, admin, model routing, image pipeline, and prompt scoring modules wherever possible.

2. Make the canvas the main professional workspace.
   - The canvas should become the primary entry point for serious creation.
   - Nodes should represent creative workflow objects, not only uploaded assets.

3. Keep the first phase storyboard-level.
   - The unit of video generation is a short image-to-video storyboard clip.
   - Full timeline editing, final film composition, and export can come later.

4. Treat prompt optimization as a first-class asset.
   - Save prompt versions, scores, suggestions, model-specific adaptations, and trace data.
   - Make image and video prompt quality visible and comparable.

5. Build SaaS safety boundaries early.
   - User/project isolation, private assets, credit checks, task status, review state, and admin visibility are required for a public SaaS.

## Scope

### In Scope for Phase 1

- Professional project canvas as the primary workflow.
- Storyboard nodes with scene intent, subject, environment, style, duration, camera, motion, and consistency constraints.
- Image prompt optimization using the existing local prompt scoring system.
- Image generation using the existing image pipeline.
- Visual scoring and optimization trace reuse.
- Video prompt optimization for image-to-video generation.
- Image-to-video generation for short storyboard clips.
- Model adaptation for image and video prompts.
- Project-level consistency constraints for characters, scene, style, color, and camera language.
- Prompt, generation, score, and asset version history per node.
- Accounts, project ownership, private asset access, and admin/model settings reuse.
- Credit/quota checks and credit transaction records for high-cost actions.
- Review status for generated or uploaded assets and admin visibility.

### Out of Scope for Phase 1

- Complete timeline editing.
- Automatic final film assembly and export.
- Public works community, likes, favorites, and creator profiles.
- Multi-user real-time collaboration.
- Full payment/subscription automation.
- Rebuilding the frontend or backend from scratch.

## Recommended Architecture

The platform should remain a monolithic FastAPI application with the existing React/Vite frontend. New capabilities should be added as focused modules that connect to current service boundaries.

### Backend Areas

1. Existing image pipeline
   - Continue using the current prompt pre-evaluation, prompt drafting/refinement, image generation, visual scoring, and optimization trace pipeline.
   - Expose this pipeline through canvas/storyboard workflows rather than only through the image-only page.

2. Canvas and project modules
   - Extend the current project/canvas data model to support workflow node types:
     - script or creative brief node
     - storyboard node
     - reference image node
     - image generation node
     - image-to-video node
     - prompt score / optimization node
   - Each node should have versioned prompt/generation metadata.

3. Video prompt and routing modules
   - Add a video prompt optimizer that produces image-to-video prompts from storyboard data, reference image metadata, and project-level consistency constraints.
   - Extend or reuse the existing video router for provider calls and mock-mode testing.

4. Credit and quota modules
   - Add credit balance and transaction records.
   - High-cost operations should perform a preflight cost estimate, reserve or deduct credits, then write a transaction record.

5. Review/admin modules
   - Extend existing admin functionality to inspect users, tasks, model settings, assets, review statuses, and failed provider calls.
   - Generated assets should carry a review state suitable for public SaaS operation.

### Frontend Areas

1. Canvas workspace
   - Upgrade the current canvas workspace into the main professional workbench.
   - Show storyboard cards/nodes, prompt score panels, generation buttons, result previews, and version history.

2. Prompt optimization panels
   - Reuse the existing image prompt analysis UI patterns.
   - Add video prompt dimensions: camera motion, subject action, temporal continuity, clip duration, rhythm, transition intent, stability, and consistency constraints.

3. Generation result panels
   - Show image and video assets with model, prompt, parameters, score, review state, cost, and task status.
   - Allow applying optimized prompts back to storyboard nodes.

4. Admin and account surfaces
   - Reuse current auth and admin screens.
   - Add credit balance visibility and generation cost feedback before expensive actions.

## Core Workflow

1. User signs in.
2. User creates or opens a project.
3. User opens a canvas.
4. User creates a storyboard node from a creative brief or manual input.
5. The storyboard node reads project-level consistency constraints.
6. User optimizes the image prompt.
   - The existing prompt scoring system evaluates the prompt.
   - The optimizer generates structured prompt variants and suggestions.
   - The score report and optimized prompt are saved as a node version.
7. User generates a reference image.
   - The existing image generation pipeline is used.
   - The generated image, prompt, model parameters, visual score, and trace are saved.
8. User optimizes the video prompt.
   - The video optimizer combines storyboard data, reference image context, and consistency constraints.
   - The result includes model-specific prompt text and parameter suggestions.
9. User generates an image-to-video clip.
   - The video provider creates a short clip from the reference image and video prompt.
   - The task stores status, provider metadata, asset URL, review state, cost, and errors if any.
10. User reviews versions and iterates.

## Prompt Optimization Requirements

### Image Prompt Optimization

Use the existing local prompt scoring system as the first-phase image prompt quality engine.

It should continue to support:

- Structured prompt fields.
- Candidate prompts.
- Quality references.
- Missing-dimension detection.
- Prompt suggestions.
- Visual scoring after generation.
- Optimization trace display.

### Video Prompt Optimization

Add a video prompt optimizer that evaluates and improves image-to-video prompts using dimensions that are specific to moving images:

- Reference image role.
- Subject action.
- Camera motion.
- Shot size and composition.
- Clip duration.
- Temporal rhythm.
- Transition or ending state.
- Motion constraints.
- Stability constraints.
- Character, scene, and style consistency.
- Negative prompt for unwanted motion/artifacts.
- Model-specific formatting and parameter recommendations.

### Model Adaptation

A storyboard should be able to produce provider-specific prompt variants. The same creative intent may need different phrasing and parameter defaults for different image or video models.

Model adaptation should be explicit and saved:

- provider/model id
- adapted prompt text
- parameter suggestions
- unsupported feature warnings
- estimated cost

## Data Model Direction

The exact schema should follow current repository/database patterns, but the conceptual entities are:

- User
- Project
- Canvas
- CanvasNode
- StoryboardSpec
- PromptVersion
- GenerationTask
- Asset
- ScoreReport
- CreditBalance
- CreditTransaction
- ReviewStatus
- ModelSettings

Important relationships:

- A user owns projects.
- A project owns canvases and assets.
- A canvas owns nodes.
- A storyboard node can own many prompt versions and generation tasks.
- A generation task can produce one or more assets.
- A prompt version can have image and/or video score reports.
- Credit transactions are linked to user, project, task, and action type.

## Error Handling

- Authentication errors return 401.
- Project or asset ownership failures return 404 where appropriate to avoid leaking existence.
- Credit insufficiency blocks high-cost task creation before provider calls.
- Provider errors are recorded on the task and surfaced to the UI as failed states.
- Prompt optimization failures preserve the original user input and allow retry.
- Video task timeouts move tasks to failed or expired states and keep error context.
- Review failures prevent public or downstream usage where required.
- Upload and asset access must keep existing file type, size, and ownership boundaries.
- External URL handling must keep SSRF protections.

## Security and SaaS Requirements

Public SaaS operation requires these boundaries in phase 1:

- Session authentication for all project and generation workflows.
- Strict user ownership checks for projects, canvases, assets, and tasks.
- Private asset serving only to the owner or authorized user.
- Upload limits and MIME/type validation.
- High-cost action protection through credits/quotas and rate limits.
- Admin-only access to model settings and review tools.
- No hardcoded provider keys in source code.
- Provider errors should not leak secrets or internal credentials.
- Review status should be stored for generated and uploaded assets.

## Testing Strategy

Backend tests should extend the existing pytest suite.

Recommended test areas:

- API tests for storyboard node creation, image prompt optimization, video prompt optimization, image generation, video generation, and task polling.
- Auth and ownership tests for cross-user project, canvas, asset, and task access.
- Credit tests for sufficient balance, insufficient balance, deduction, failed task handling, and transaction records.
- Pipeline tests for reusing current image prompt scoring and trace output.
- Video prompt tests for structure, consistency constraint injection, and model adaptation.
- Router tests for mock image/video generation, provider failure, timeout, and retry behavior.
- Admin tests for model settings, review status, and task visibility.

Frontend verification should include a manual checklist until frontend test tooling is added:

1. Sign in.
2. Create project.
3. Open canvas.
4. Create storyboard node.
5. Optimize image prompt.
6. Generate reference image.
7. View image score and trace.
8. Optimize video prompt.
9. Generate image-to-video clip.
10. View task status, asset, score, cost, and review state.
11. Confirm version history is preserved.
12. Confirm unauthorized project/asset access is blocked.

If Playwright is added later, this checklist should become the first critical E2E journey.

## Phase Plan

### Phase 1A: Canvas Prompt Workflow

- Make project canvas the main workbench.
- Add storyboard node fields and prompt versions.
- Reuse image prompt scoring and optimization inside storyboard nodes.
- Display optimization trace and candidate prompts in canvas context.

### Phase 1B: Reference Image Generation

- Connect storyboard nodes to the existing image generation pipeline.
- Save generated images as project assets.
- Preserve prompt, parameters, score, and trace history.

### Phase 1C: Video Prompt Optimization

- Add image-to-video prompt structure and scoring.
- Inject project-level consistency constraints.
- Add model-specific video prompt adaptation.

### Phase 1D: Image-to-Video Generation

- Connect video provider routing and mock mode.
- Generate short storyboard clips from reference images.
- Save tasks, assets, provider metadata, errors, and review status.

### Phase 1E: SaaS Controls

- Add credits/quotas and transaction records.
- Enforce preflight credit checks for high-cost actions.
- Extend admin visibility for users, tasks, review statuses, and model settings.

## Open Decisions for Implementation Planning

These are implementation details to decide during planning, not blockers for this design:

- Exact database migration strategy for new canvas node metadata.
- Whether credit deduction is immediate, reserved, or finalized after task success.
- Which video provider is enabled first beyond mock mode.
- Whether video scoring is heuristic-only in phase 1 or uses a multimodal evaluator when configured.
- How much of the current image-only page remains visible once canvas becomes the main workflow.
