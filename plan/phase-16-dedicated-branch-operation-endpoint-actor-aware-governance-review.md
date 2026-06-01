# Phase 16 Review: Dedicated Branch Operation Endpoint & Actor-Aware Governance

## 阶段目标

第十六阶段目标是把 Phase 15 的 Branch Governance Console 从 CanvasDetail 附带的最近治理记录，升级为独立可分页、可过滤、带 actor display 的治理数据源。

Phase 15 已经完成 reasoned pin / archive / restore dialog、affected scope preview 和前端治理控制台。Phase 16 继续解决工业级治理工作台需要的数据边界：operation log 不能永远依赖 CanvasDetail 最近 80 条，必须有专门的查询端点、稳定分页、过滤能力和操作者展示。

核心链路是：branch_operations dedicated endpoint → repository paginated query → actor_display → frontend API wrapper → Branch Governance Console filter / pagination → mutation 后重新拉取 dedicated page。

## 已完成内容

- 增加 branch operation list response model：
  - `BranchOperationListResponse`。
  - 返回 `operations`、`total`、`limit`、`offset`。
- `BranchOperationResponse` 增加 actor 字段：
  - `actor_id`。
  - `actor_display`。
  - 当前使用 `users.username` 作为 actor display。
- 增加 dedicated branch operation endpoint：
  - `GET /api/canvases/{canvas_id}/branch-operations`。
  - 支持 `operation` filter：`materialize`、`archive`、`restore`、`pin`、`unpin`。
  - 支持 `scope` filter：`single`、`subtree`、`path`。
  - 支持 `target_node_id` filter。
  - 支持 `limit` / `offset` 分页。
  - `limit` 最大 100，避免无界拉取。
- Repository 增加 `list_branch_operations(...)`：
  - 先校验 canvas 属于当前 owner，避免 IDOR。
  - operation / scope 在 repository 层再次白名单校验。
  - SQL values 全部参数化，动态 where clause 只由 server-side 固定片段组成。
  - 返回 page rows 和 total count。
- Existing CanvasDetail branch operations 增加 actor_display：
  - `get_canvas(...)` 仍保留最近 80 条 branch operations 作为首屏/兼容摘要。
  - 查询通过 `LEFT JOIN users` 补齐 actor display。
- 稳定分页排序：
  - branch operation 查询统一使用 `ORDER BY bo.created_at DESC, bo.id DESC`。
  - 避免同一 timestamp 下 LIMIT/OFFSET 出现重复或跳过记录。
- 增加查询索引：
  - 保留旧 `idx_branch_operations_canvas_created(canvas_id, created_at)`。
  - 新增 `idx_branch_operations_canvas_created_id(canvas_id, created_at, id)`。
  - 新增 `idx_branch_operations_canvas_target_created(canvas_id, target_node_id, created_at, id)`。
  - 新增 `idx_branch_operations_canvas_operation_scope_created(canvas_id, operation, scope, created_at, id)`。
  - 新增 `idx_branch_operations_canvas_scope_created_id(canvas_id, scope, created_at, id)`。
- 前端 API 增加 wrapper：
  - `fetchCanvasBranchOperations(canvasId, filters)`。
  - 使用 `URLSearchParams` 安全构建 query。
- Canvas controller 增加 dedicated page state：
  - `branchOperationFilters`。
  - `branchOperationPage`。
  - `loadBranchOperations(...)`。
  - Branch Governance Console 不再把 CanvasDetail 最近 80 条作为分页 source of truth。
- 前端 Governance Console 接入 dedicated endpoint：
  - filter 变化时拉取 endpoint。
  - 支持上一页 / 下一页。
  - 显示 `total`、当前 range 和 loading 状态。
  - 每条 operation 显示 actor display。
- 避免 stale async overwrite：
  - `loadBranchOperations(...)` 使用 request id 防止旧请求覆盖新筛选/分页结果。
  - 使用 `latestCanvasIdRef` 防止切换 canvas/project 后旧 branch operation 请求写入新 workspace。
  - archive / restore / pin mutation 成功后也会校验 request canvas id，避免旧 mutation response 覆盖当前 canvas。
- Mutation 后刷新 dedicated governance page：
  - archive / restore / pin 成功后重新通过 `loadBranchOperations(...)` 拉取当前 filter 的第一页。
  - 不再用 `fetchCanvas(...).branch_operations` 覆盖 paginated/filter state。

## 方向复盘

方向是正确的。

Phase 16 把治理控制台的数据源从“CanvasDetail 附带摘要”推进为“独立治理查询”。这是工业级审计能力的基础，因为真实项目中的 branch operations 会不断增长，设计师和团队负责人需要按操作类型、范围、目标节点和时间分页追踪，而不是只能看到最近 80 条。

本阶段没有删除 CanvasDetail 上的 `branch_operations`，这是合理的兼容策略：CanvasDetail 继续提供轻量最近摘要，Dedicated endpoint 负责专业治理控制台和分页过滤。

## 本阶段修正的关键问题

静态审查发现并修复了以下问题：

1. Branch operation filtered endpoint 缺少查询形状索引。
   - 已修复：增加 canvas + target、canvas + operation/scope、canvas + scope 和 canvas + created/id 索引。
2. Pagination order 只按 `created_at`，同 timestamp 下不稳定。
   - 已修复：统一 `ORDER BY created_at DESC, id DESC`。
3. UI page size 与渲染条数不一致。
   - 已修复：不再 `slice(0, 8)`，server page 原样渲染；分页 range 与 page limit 对齐。
4. Refresh / mutation flows 会用 CanvasDetail 最近 80 条覆盖 dedicated page state。
   - 已修复：refresh 不再覆盖 branchOperationPage；mutation 后通过 dedicated endpoint 重新拉取当前 filter。
5. 本页 summary 可能被误解为全局 summary。
   - 已修复：UI 明确标注“本页 pins / archives”和“本页最新主线 / 最近归档 / 最近恢复”。
6. 快速切换 filter/page 时旧请求可能覆盖新结果。
   - 已修复：`loadBranchOperations(...)` 使用 request id 忽略 stale response。
7. 切换 canvas/project 时旧 operation 请求或 mutation 回包可能覆盖新 workspace。
   - 已修复：用 `latestCanvasIdRef` 校验 request canvas id；不匹配则不 set state。
8. BranchGovernanceConsole canvas 切换后 filter 未变时不会自动重拉。
   - 已修复：传入 `canvasId` 并加入 effect dependencies。

最终复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

## 仍未达到工业级的部分

- Console 的 operation counts 和 latest summaries 目前明确是“本页”级别，不是全局 aggregate。
- Endpoint 还没有返回全局 aggregates，例如 operation_counts、scope_counts、latest_pin、latest_archive、latest_restore。
- Actor 目前只显示 owner username；还没有 team member、role、avatar 或真实协作者模型。
- 治理控制台仍嵌在 Repair Version Tree 内，还不是独立的全屏 Governance Workspace。
- Operation detail view 还没有展开 payload、path_node_ids、batch lineage、before/after impact。
- 还没有按时间范围、actor、affected node、reason keyword 搜索。
- 还没有导出 audit report。
- `branch_operations` 仍未在数据库层通过 trigger 禁止 update/delete。
- 仍未增加数据库级 one repair_version per batch invariant。

## 是否继续按当前路线推进

继续。

下一阶段建议进入 Phase 17：Global Governance Aggregates & Operation Detail View。

阶段目标：让 dedicated branch operation endpoint 不只返回 page rows，还返回全局治理摘要与 operation detail 所需数据，解决目前“本页 summary”不等于全局 summary 的限制，并让设计师能展开一次治理操作看到完整影响。

建议下一阶段重点：

1. Endpoint 返回全局 `operation_counts` 和 `scope_counts`。
2. Endpoint 返回全局 `latest_pin`、`latest_archive`、`latest_restore`。
3. 增加 operation detail view，展示 payload、affected nodes、path nodes、batch ids、reason、actor、created_at。
4. Detail view 支持定位每个 affected repair version。
5. 增加 impact detail：active path / pinned path / archived count 的操作后摘要。
6. UI 把本页 summary 和全局 summary 分开显示。
7. 增加 reason keyword search 和 target node filter UI。
8. 评估独立 Governance Console 面板，不再嵌在 Image Batch Studio 下。

## 本阶段静态检查

已使用 code-reviewer、security-reviewer、database-reviewer 做 Phase 16 静态审查。

第一轮发现并修复：

- 缺少 branch operation filtered query indexes。
- Pagination order 不稳定。
- UI page size 与实际渲染条数不一致。
- CanvasDetail 最近 80 条会覆盖 dedicated endpoint page state。

后续复审发现并修复：

- scope-only filter 缺少索引。
- 本页 summary 容易被误解为全局 summary。
- 快速切换 filter/page 可能出现 stale response 覆盖。
- 切换 canvas/project 后旧请求或 mutation 回包可能覆盖新 workspace。
- canvasId 变化但 filter 未变时 governance console 不会自动重新拉取。

最终复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。
