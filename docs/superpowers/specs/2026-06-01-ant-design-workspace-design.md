# Ant Design Workspace Redesign

## Context

The current project workspace uses a custom dark creative-canvas interface with three visually separate regions: command panel, canvas stage, and inspector. In the screenshot, the page feels crowded because the top workspace tabs float above the canvas, the left panel contains several dense sections with nested scrolling, and the stage/inspector/command panels feel like independent surfaces rather than one coherent product workspace.

The requested redesign switches the page to Ant Design and uses a light Ant Design Pro style. The selected layout direction is a single integrated workbench card: all workspace functions live inside one large Ant Design container.

## Goals

- Convert the project creative workspace to a light Ant Design visual system.
- Place all workspace functions inside one unified workbench frame.
- Improve readability, spacing, hierarchy, and perceived polish.
- Keep existing business logic and API behavior intact.
- Preserve the canvas-first workflow while making tools, inspector details, and production actions easier to scan.
- Apply the Ant Design direction broadly across the visible app shell, not only the canvas page, so the experience feels consistent.

## Non-goals

- Do not rewrite backend APIs.
- Do not redesign the data model.
- Do not replace the custom canvas drag/pan/node behavior with a third-party graph library in this pass.
- Do not change generation, upload, polling, approval, or task orchestration semantics.

## Design Direction

Use a light Ant Design Pro-inspired interface:

- Page background: soft light gray (`#f5f7fb`-style).
- Primary work surfaces: white Cards with subtle borders and shadows.
- Primary action color: Ant Design blue.
- Canvas background: light grid on an off-white surface.
- Node cards: white cards with Ant Design-like borders, shadows, and colored Tags for node types.
- Errors, warnings, loading, and empty states: Ant Design `Alert`, `Spin`, and `Empty` patterns.

## Scope

### 1. Dependencies and global Ant Design setup

Add Ant Design to the frontend and load its reset stylesheet. Wrap the app with `ConfigProvider` so the light theme is controlled by Ant Design tokens rather than scattered custom values.

The first theme pass should use default Ant Design light mode with modest custom tokens for border radius, page background, and primary color. Avoid heavy custom theming that would recreate the current bespoke style.

### 2. App shell consistency

Update the main app surfaces enough that the Ant Design workspace does not feel visually isolated. This includes the project workspace top-level shell and, where practical, adjacent project/account/admin/auth surfaces that currently share the same custom visual language.

The implementation can be phased internally, but the end state should feel like one Ant Design application rather than one Ant Design page inside an old custom app.

### 3. Project workspace frame

Replace the current floating workspace structure with a single large workbench container:

```text
┌────────────────────────────────────────────────────────────┐
│ Header: back, project title, tabs, credits, counts, status  │
├──────────────┬──────────────────────────────┬──────────────┤
│ Creative     │ Canvas stage                 │ Inspector    │
│ tools        │ toolbar + light grid         │ details      │
├──────────────┴──────────────────────────────┴──────────────┤
│ Production tray: image batches / series / final JSON        │
└────────────────────────────────────────────────────────────┘
```

The header should contain the current project name, return action, workspace tabs, account credits, asset/task counts, and status pill. Tabs should no longer float above the stage; they should be part of the workbench header.

### 4. Left creative tools area

Convert the left command panel to Ant Design components:

- Use `Card`, `Typography`, `Input.TextArea`, `Button`, `Space`, `Divider`, and `Segmented` or `Radio.Group`.
- Keep brief input, add-to-canvas, storyboard node, semantic skeleton, media upload, reference-role selection, reference instruction, and media asset insertion.
- Reduce visual noise by grouping related actions:
  - Brief actions
  - Semantic skeleton action
  - Media references
- Avoid internal scrollbars unless content exceeds the viewport. Prefer a clean panel with consistent spacing.

### 5. Central canvas stage

Keep the existing canvas behavior and state management. Restyle the stage to a light Ant Design-compatible surface:

- Toolbar becomes a Card header-style row with title, node/edge counts, selected graph count, and zoom controls.
- Zoom controls use Ant Design buttons.
- Grid becomes light gray/blue instead of dark neon.
- Node cards become Ant Design-like cards with clear selected and in-scope states.
- Type differentiation uses subtle border colors and Tags rather than heavy gradients.

### 6. Right inspector area

Convert the inspector to Ant Design components:

- Use `Card`, `Empty`, `Button`, `Space`, `Tag`, `Descriptions`, `Collapse`, or lightweight sections as appropriate.
- Keep current inspector functionality: node details, prompt optimization panel, image edit, video remix, media approval, repair branch actions, prompt program generation, and graph-based image generation.
- Use Ant Design empty state when no node is selected.
- Keep action availability and disabled logic unchanged.

### 7. Bottom production tray

Keep the existing production features but place them in the same workbench frame:

- Image Batch Studio
- Series Director
- Final JSON

Use a three-column Card layout on desktop and stack responsively on smaller screens. Use Ant Design buttons, cards, tags, and empty/loading states where practical.

### 8. Dialogs and overlays

Convert custom modal-like overlays to Ant Design `Modal` or `Drawer` where practical without changing behavior:

- Image batch settings
- Branch operation confirmation
- Media approval
- Image edit
- Video from candidate
- Video remix

Use Modal for focused confirmation/settings flows and Drawer for workflows that benefit from keeping canvas context visible.

### 9. Asset tab and adjacent visible pages

Because the user requested doing the broader Ant Design conversion, include the media asset tab and visible project-level pages in the polish pass. These should use Ant Design lists/cards/tables/forms where practical while preserving existing functionality.

Priority order:

1. Project workspace and canvas page.
2. Asset gallery tab.
3. Project list and creation flow.
4. Auth/admin/account surfaces if they are visually inconsistent after the workspace conversion.

## Data Flow and Behavior

No API contract changes are required. The React state and existing action handlers remain the source of truth.

- `ProjectWorkspace` continues loading assets, tasks, credits, and status.
- `CanvasWorkspaceController` continues owning canvas state, action handlers, polling, uploads, and dialogs.
- `CanvasWorkspaceView` remains the main render boundary but uses Ant Design components and updated CSS.
- Existing CSS modules/files may be simplified or replaced with Ant Design-oriented layout CSS.

## Error Handling

- Preserve current try/catch handling in controllers.
- Show user-facing failures with Ant Design `Alert`, message text, or status components.
- Do not silently swallow API errors.
- Keep disabled states for actions requiring selected nodes, available canvas, or non-loading state.

## Responsive Behavior

Desktop is the primary target. The workbench should remain usable at common laptop widths.

- At wide widths: left tools, center canvas, right inspector in one row.
- At medium widths: reduce side panel widths and allow the bottom tray to stack.
- At narrow widths: stack tools, canvas, inspector, and production sections vertically or use drawers where needed.

## Testing and Verification

Default verification should be manual unless the user explicitly asks to run tests.

Manual verification should include:

- App launches successfully.
- Project workspace opens.
- Canvas tab renders inside one unified Ant Design workbench frame.
- Asset tab still works.
- Brief input, buttons, reference upload controls, canvas toolbar, inspector actions, and production tray remain visible and usable.
- Existing dialogs still open and close correctly.
- No obvious console/runtime crash during page load.

If the user asks for automated tests, add or update tests around changed boundaries and run the relevant suite.

## Implementation Risks

- `CanvasWorkspaceComponents.jsx` is large and contains many nested render helpers, so a full component migration could be error-prone. Keep behavior changes minimal and favor mechanical UI replacement plus CSS updates.
- Ant Design CSS can conflict with existing global styles. Load `antd/dist/reset.css` and scope remaining custom workspace CSS to workspace-specific class names.
- The canvas relies on custom pointer handling. Do not wrap the stage in components that interfere with pointer events.
- Broad app-wide Ant Design conversion can grow in scope. Prioritize the workspace, then polish adjacent pages if time remains.

## Acceptance Criteria

- The selected workspace uses a light Ant Design style.
- All workspace functions are visually contained inside one large workbench card/frame.
- The top tabs are integrated into the workbench header.
- The central canvas uses a light grid and Ant Design-like node styling.
- Left tools, right inspector, and bottom production tray use Ant Design component styling.
- Existing core canvas actions remain connected to their current handlers.
- The broader visible app no longer feels like a mix of unrelated dark custom UI and light Ant Design UI.
