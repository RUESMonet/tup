# Phase 14 Review: Dedicated Branch Operation Log & Governance Console

## 阶段目标

第十四阶段目标是把 Phase 13 中存放在 repair version node payload 内的 compact audit trail，提升为独立的 branch operation log，并让画布、Final JSON 和治理 UI 都能表达 pin / archive / restore / materialize 的操作历史。

Phase 13 已经完成 designer-pinned production path、子树 archive / restore、server-managed repair version materialization 和 production input governance。Phase 14 继续解决专业设计师团队在真实项目中需要的治理问题：谁做过哪些 branch 操作、操作范围是什么、原因是什么、这些操作如何影响 active production path，以及最终交付 JSON 是否能携带可审计的治理摘要。

核心链路是：branch operation append log → CanvasDetail branch_operations → materialize/archive/restore/pin 写日志 → Final JSON governance summary → Repair Version Tree governance log。

## 已完成内容

- 增加独立 `branch_operations` 表：
  - 记录 `owner_id`、`project_id`、`canvas_id`、`operation`、`reason`、`scope`、`target_node_id`、`affected_node_ids_json`、`payload_json`、`created_at`。
  - 通过 canvas owner/project 外键约束绑定同一项目和画布。
  - 增加 `idx_branch_operations_canvas_created` 索引，用于按 canvas 拉取最近治理记录。
- 增加 API response model：
  - 新增 `BranchOperationResponse`。
  - `CanvasDetailResponse` 增加 `branch_operations`，返回最近 80 条 operation log。
- Repository 接入 branch operation log：
  - `get_canvas(...)` 加载 `branch_operations`。
  - 新增 `create_branch_operation(...)`。
  - 约束 operation 只能是 `materialize`、`archive`、`restore`、`pin`、`unpin`。
  - 约束 scope 只能是 `single`、`subtree`、`path`。
  - 对 affected node ids 去重并限制最多 200 个。
  - 对 operation payload 做深度和字节大小限制，避免日志 payload 无界增长。
- Repair version materialize 写入 operation log：
  - 新 repair version 物化时写 `operation="materialize"`。
  - 记录 batch id、parent batch id、version node 和 source nodes。
  - 如果 batch 已经物化，只做 idempotent reconcile，不再追加伪 materialize 日志。
- Branch archive / restore 写入 operation log：
  - 单节点 archive / restore 记录 `scope="single"`。
  - 子树 archive / restore 记录 `scope="subtree"`。
  - `affected_node_ids` 对应实际发生状态变化的 repair version nodes。
  - reason 继续来自 API 字段或前端固定文案。
- Pin production path 写入 operation log：
  - pin 主线记录 `operation="pin"`、`scope="path"`。
  - `affected_node_ids` 包含完整 ancestor path nodes 和实际被 pin/unpin 的节点。
  - payload 记录 `pinned_node_id`、`path_node_ids` 和 `unpin_count`。
- Final JSON production lineage 增加治理摘要：
  - 输出 `branch_operation_log`。
  - 包含 `latest_operations`、`operation_counts`、`scope_counts`、`latest_pin`、`latest_archive`、`latest_restore`。
  - 只纳入当前 selected lineage scope 相关的 operation。
  - 每条 operation 限制 reason、affected nodes 和 payload 字段，避免交付 JSON 膨胀。
- Final submission artifact 使用 compact lineage：
  - API response 仍返回完整 `production_lineage` 供前端预览。
  - 持久化到 `prompt_artifacts` 的 payload 使用 `_compact_production_lineage_for_artifact(...)`。
  - 避免大画布完整 lineage 超过 repository 60KB artifact 上限导致合法 final-submit 失败。
- 前端增加 Branch Governance Log：
  - Repair Version Tree 下展示最近 governance operations。
  - 显示 operation 类型、scope、目标版本、affected count、reason 和时间。
  - Final JSON Preview 增加 Governance 摘要，显示 operation 数和是否存在 pin。
- 前端 archive / restore / pin 后重新拉取完整 canvas：
  - 避免只更新 nodes 时丢失最新 `branch_operations`。
  - 保证治理日志在操作后立即刷新。

## 方向复盘

方向是正确的。

Phase 14 让 branch governance 从“节点 payload 上的最近几条备注”进入“独立治理事件流”。这一步很关键，因为专业生产不是单人随手调参，而是持续比较、选择、归档、恢复和确认主线的过程。只有独立 operation log，后续才能做团队协作、客户确认、可追溯审批、批量治理和最终交付审计。

本阶段没有把 node-level `branch_audit_trail` 删除，而是保留为 compact local summary，同时新增独立 branch operation log。这是合理的双层结构：节点 payload 适合快速读局部状态，operation log 适合审计和治理视图。

## 本阶段修正的关键问题

静态审查发现并修复了以下问题：

1. Final JSON lineage 可能超过 artifact 60KB 存储上限。
   - 已修复：API response 保留完整 lineage，但持久化 artifact 使用 compact lineage。
   - compact lineage 保留关键治理、路径、媒体和边摘要，删除候选 prompt/evaluation 等重字段。
2. 重复 materialize 已存在 repair batch 时会追加一条不真实的 materialize log。
   - 已修复：如果 repair version 已经存在，只执行 idempotent reconcile，不再创建新的 materialize operation。
3. Pin operation 标为 path scope，但 affected ids 没有包含完整 path。
   - 已修复：pin log 的 `affected_node_ids` 现在包含 ancestor path nodes 和实际 pin/unpin nodes；payload 额外记录 `path_node_ids`。

最终复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

## 仍未达到工业级的部分

- Branch operation log 现在是 append-style 表，但还没有数据库 trigger 或权限层彻底禁止 update/delete；repository 层没有提供修改接口。
- Reason 仍主要来自前端固定文案或 API 字段，还没有用户输入 dialog、批量范围预览和操作者身份展示。
- UI 目前是 Repair Version Tree 内的治理日志摘要，还不是完整 Branch Governance Console。
- Operation log 记录 actor 仍隐含在 `owner_id`，没有单独 actor profile / team member / role 字段。
- 没有支持 operation diff view，例如 archive subtree 前后 active path 如何变化。
- 没有把 operation log 独立分页查询；当前随 CanvasDetail 返回最近 80 条。
- 没有 safe branch delete，只继续坚持 archive-only。
- 仍未增加 one repair_version per batch 的数据库唯一约束；当前仍依赖 repository 事务和 batch lookup。

## 是否继续按当前路线推进

继续。

下一阶段应进入 Phase 15：Branch Governance Console & Reasoned Operations。

阶段目标：把当前 Repair Version Tree 内的治理摘要升级为专业治理控制台，补齐 reason dialog、操作范围预览、actor/time/filter、operation impact summary，并继续保持 archive-only 的非破坏式生产治理。

建议下一阶段重点：

1. UI 增加 Branch Governance Console：按时间线、operation、scope、status 和 target version 过滤。
2. archive subtree / restore subtree / pin path 增加 reason dialog 和 affected scope preview。
3. Operation log 增加 actor display 字段，至少在 API response 中明确 owner/actor。
4. Operation impact summary：展示操作前后 active path / pinned path / archived count 的变化。
5. 增加 branch operation list endpoint，支持分页，不再只依赖 CanvasDetail 最近 80 条。
6. 继续保留 node-level compact audit trail，但以 branch_operations 为主审计源。
7. 设计 safe branch delete，但默认仍不提供 destructive delete。
8. 增加数据库级 one repair_version per batch invariant。

## 本阶段静态检查

已使用 code-reviewer 做 Phase 14 静态审查。

第一轮发现并修复：

- Final JSON lineage 可能超过 artifact payload 上限。
- duplicate materialize 会产生不真实 governance log。
- pin path operation 没有记录完整 path affected scope。

复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。
