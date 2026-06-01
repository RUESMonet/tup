# Phase 15 Review: Branch Governance Console & Reasoned Operations

## 阶段目标

第十五阶段目标是把 Phase 14 中 Repair Version Tree 内的治理日志摘要，升级为更接近专业生产场景的 Branch Governance Console，并让 pin / archive / restore 不再是直接点击即执行，而是进入带 reason 和 affected scope preview 的确认流程。

Phase 14 已经完成独立 `branch_operations` append log、CanvasDetail 最近治理记录、Final JSON governance summary 和基础 UI 摘要。Phase 15 继续补齐专业设计师团队在真实项目中需要的操作语义：执行前看清影响范围、说明操作原因、提交后能在控制台按操作类型和范围追踪治理事件。

核心链路是：repair version action → reason dialog → affected scope preview → existing governance API → branch operation log refresh → Branch Governance Console filtering / impact summary。

## 已完成内容

- 前端增加 reasoned branch operation dialog：
  - 新增 `branchOperationDialog` 状态。
  - 新增 `branchOperationSubmitting` 状态，避免 pin / archive / restore 重复提交。
  - 新增 `openBranchOperationDialog(...)`、`closeBranchOperationDialog(...)`、`setBranchOperationReason(...)`、`submitBranchOperationDialog(...)`。
  - dialog 内展示目标版本、影响范围、状态变化和可编辑操作原因。
  - reason 为空时禁止提交，确保治理日志不是无语义点击记录。
- 增加 affected scope preview：
  - `repairVersionAncestors(...)` 用于 pin path 预览完整 ancestor path。
  - `repairVersionDescendants(...)` 用于 archive / restore subtree 预览子树范围。
  - `branchOperationPreview(...)` 根据 operation 和 includeDescendants 计算 dialog 影响节点。
- Inspector repair-version actions 改为 reasoned flow：
  - “设为主生产路径”打开 pin path dialog。
  - “归档修复分支 / 归档子树”打开 archive dialog。
  - “恢复修复分支 / 恢复子树”打开 restore dialog。
  - 原有后端治理 API 不变，提交时继续写入 Phase 14 的独立 branch operation log。
- Repair Version Tree actions 改为 reasoned flow：
  - Tree 内主线、归档、恢复、归档子树、恢复子树都不再直接 mutate。
  - 所有操作统一走 Branch Governance dialog。
- Branch Governance Console 替换基础日志摘要：
  - 显示 operation 总数、pin 数、archive 数。
  - 支持按 operation 过滤：materialize / pin / archive / restore。
  - 支持按 scope 过滤：single / subtree / path。
  - 展示最新主线、最近归档、最近恢复的 impact summary。
  - 每条日志展示 operation、scope、target、affected count、reason、created_at。
  - 对 repair version target 提供“定位版本”操作。
- 治理记录排序修正：
  - Console 不再假设 API 返回顺序。
  - 前端按 `created_at` 降序排序后再计算 latest summaries、过滤和截取可见列表。
  - 避免未来分页或后端顺序变化导致“最新主线 / 最近归档 / 最近恢复”显示错误。
- CSS 增加治理控制台与 reason dialog 样式：
  - `.canvas-branch-governance-console`
  - `.canvas-governance-filter-row`
  - `.canvas-governance-impact-grid`
  - `.branch-operation-dialog`
  - `.branch-operation-impact`
  - `.branch-operation-affected-list`

## 方向复盘

方向是正确的。

Phase 15 把治理从“日志可见”推进到“操作前可解释、操作后可审计”。这比简单增加按钮更重要：专业设计师在多分支版本生产中，需要知道自己归档的是单个版本还是整个子树，固定的是哪个完整 production path，以及为什么做这个决定。

本阶段仍保持 Phase 13/14 的非破坏式原则：archive / restore / pin 都不删除节点、不覆盖媒体、不绕过后端治理边界。前端只提供更专业的操作入口和操作语义，实际状态变更仍走 server-managed API 和独立 branch operation log。

## 本阶段修正的关键问题

静态审查发现并修复了以下问题：

1. Branch Governance Console 默认信任 operation 输入顺序。
   - 问题：`latestOperationLabel(...)` 和 visible log 使用数组原始顺序；如果后端未来不是 newest-first，会显示过期的“最新”治理事件。
   - 已修复：新增 `sortedOperations`，按 `created_at` 降序排序后再计算 counts、latest summary、filters 和 visible rows。

最终复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

## 仍未达到工业级的部分

- Branch Governance Console 仍嵌在 Repair Version Tree 内，还不是独立全屏或侧栏级治理工作台。
- Operation list 仍来自 CanvasDetail 最近 80 条，没有独立分页 endpoint。
- Actor 仍未在 UI 中展示；当前后端仍主要隐含在 owner/user 维度。
- Impact summary 目前是 latest target 摘要，还没有展示操作前后 active path、pinned path、archived count 的精确 diff。
- Reason dialog 目前是自由文本，还没有模板、必填语义结构、客户确认状态或审批流。
- 还没有批量治理队列，例如一次性筛选多个低分分支后统一 archive。
- 还没有 safe branch delete；仍坚持 archive-only 的非破坏式治理。
- 没有数据库级 append-only trigger 禁止 `branch_operations` update/delete。
- 没有数据库级 one repair_version per batch invariant；仍依赖 repository 事务和 batch lookup。

## 是否继续按当前路线推进

继续。

下一阶段建议进入 Phase 16：Dedicated Branch Operation Endpoint & Actor-Aware Governance。

阶段目标：把治理控制台从 CanvasDetail 附带最近 80 条，升级为独立可分页、可过滤、带 actor display 和更明确 impact summary 的治理数据源，为团队协作、客户确认和审计导出打基础。

建议下一阶段重点：

1. 增加 branch operation list endpoint，支持分页、operation filter、scope filter、target node filter。
2. API response 增加 actor display 字段，至少明确当前 owner/actor。
3. Branch Governance Console 使用独立 endpoint，不再只依赖 CanvasDetail 最近 80 条。
4. Operation impact summary 增加 active path / pinned path / archived count 的前后变化摘要。
5. Reason dialog 增加结构化 reason 模板：客户确认、质量淘汰、主体漂移、风格偏离、合规原因。
6. 增加 operation detail view：显示 payload、affected nodes、path nodes、batch ids 和关联媒体。
7. 设计但默认不开放 safe branch delete，继续坚持 archive-only。
8. 增加数据库层 one repair_version per batch invariant。
9. 评估 append-only 数据库保护：trigger 或权限层禁止 branch operation update/delete。

## 本阶段静态检查

已使用 code-reviewer 做 Phase 15 静态审查。

第一轮发现并修复：

- Branch Governance Console operation ordering 可能导致 latest summaries 显示旧记录。

复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。
