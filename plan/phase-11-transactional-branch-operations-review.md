# Phase 11 Review: Transactional Branch Operations & Branch Diff Report

## 阶段目标

第十一阶段目标是把 Phase 10 的 active / archived 状态表达升级为更专业的分支治理能力。

Phase 10 已经能在 UI 和 Final JSON 中区分 active、archived、unmaterialized repair versions，但归档 / 恢复仍然由前端直接 patch node payload，分支趋势也只是轻量摘要。Phase 11 要把分支状态变成显式后端操作，并让设计师能直接在版本树里定位、归档、恢复和阅读分支级 diff。

核心链路是：显式 branch status API → repair_version payload 托管 → 版本树直接操作 → branch diff report → Final JSON repair_branch_reports。

## 已完成内容

- 新增后端 repair version 分支状态接口：
  - `POST /api/canvases/{canvas_id}/repair-versions/{node_id}/status`
  - 请求体只允许 `active` / `archived`。
  - 只允许操作 `repair_version` 节点。
  - 只更新 `repair_version.payload.status`，不删除节点、边、批次、候选图或源资产。
- 通用节点 PATCH 增加保护：
  - `repair_version` 的 payload 被视为 branch-managed metadata。
  - 通用 `PATCH /nodes/{node_id}` 不再允许改写 repair version payload，避免绕过显式分支操作并破坏 lineage。
- 前端 API 增加：
  - `setCanvasRepairVersionStatus(canvasId, nodeId, status)`。
- 前端 Controller 改为使用显式分支状态接口：
  - `setRepairVersionArchiveStatus(...)` 不再通过通用 `updateCanvasNode(...)` 改 payload。
- Repair Version Tree 支持直接操作：
  - 已物化节点可直接“定位”。
  - active 节点可直接“归档”。
  - archived 节点可直接“恢复”。
- 画布定位能力：
  - 从版本树点击“定位”会选中 repair version node，并把画布视图居中到该节点。
- Branch Trend 升级为分支 diff 摘要：
  - 沿 parent batch chain 重建当前分支。
  - 不再只看 active 节点；归档祖先和未物化后代不会让链路断掉。
  - 展示每轮版本的最佳分、score delta、关键 dimension delta。
- Final JSON production lineage 增加：
  - `repair_branch_reports`
  - 每个 report 包含：
    - `branch_id`
    - `status`
    - `version_count`
    - `score_start`
    - `score_end`
    - `score_delta`
    - `versions`
  - 每个 version report 包含：
    - `batch_id`
    - `version_status`
    - `iteration`
    - `focus_key`
    - `focus_label`
    - `baseline_score`
    - `best_score`
    - `best_score_delta`
    - `dimension_deltas`
    - `resolved_targets`
- Final JSON branch reports 会保留 `unmaterialized` 版本语义，不会静默只报告旧的已物化 tip。

## 方向复盘

方向是正确的。

Phase 11 的关键进展不是“多了几个按钮”，而是把 repair version 从普通 canvas node payload 推进到了受控的分支操作模型。专业设计师需要的是可审计、可恢复、可解释的版本治理，而不是任意节点字段编辑。显式 branch status API 让后续扩展事务式分支操作成为可能。

分支 diff report 也让 Final JSON 更像生产交付物：它不仅保存图片候选和版本节点，还能解释每条修复链如何从 baseline 走到当前版本、哪些维度改善、哪些目标被解决。

## 本阶段修正的关键问题

首次静态审查发现 3 个 MEDIUM 问题：

1. 通用节点 PATCH 仍可改写 repair version 的 lineage 字段。
2. Final JSON branch report 只统计已物化版本，可能漏掉未物化的最新修复批次。
3. 前端 Branch Trend 只沿 active 节点重建链路，归档祖先会让分支 diff 断链。

已修复：

- `repair_version` payload 现在由显式分支操作托管，通用 PATCH 不允许改 payload。
- `_repair_branch_reports(...)` 改为基于全部 repair_versions 构建分支链，保留 `unmaterialized` 状态。
- 前端 `RepairBranchTrend` 改为基于完整版本集合沿 parent batch chain 重建链路，不只看 active。

复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

## 仍未达到工业级的部分

- 分支状态接口目前只支持单节点 active / archived，还不是整条分支的事务式批量操作。
- 还没有“安全删除整个修复分支”的后端事务接口。
- 还没有 branch operation audit log，例如谁在什么时间归档 / 恢复了哪条分支。
- Branch diff 仍是摘要级，不是完整的矩阵对比视图。
- 画布内 repair version 节点仍是线性物化，尚未实现真正的自动 branch layout。
- archived 状态还没有影响候选推荐排序、批次过滤、自动推荐 active production path。

## 是否继续按当前路线推进

继续。

下一阶段应进入 Phase 12：Branch Layout, Audit Trail & Active Production Path。

阶段目标：把当前分支治理从侧栏树和 Final JSON 推进到真正的画布布局、审计记录和生产路径推荐。

建议下一阶段重点：

1. 实现 repair version branch auto-layout，把父子版本在画布内排成可读的树状结构。
2. 增加 branch operation audit trail，记录 archive / restore / future delete 操作。
3. 增加 active production path 标记，让 Final JSON 明确指出当前推荐主分支。
4. archived 分支默认从推荐路径中排除，但仍保留在审计和 diff report 中。
5. 设计事务式 branch archive / restore：可选整条子树，而不是只改单个版本节点。
6. 为未来 safe delete branch 做后端事务边界设计。

## 本阶段静态检查

已使用 code-reviewer 做 Phase 11 静态审查。

首次审查发现并修复：

- 通用节点 PATCH 仍可破坏 repair version lineage；已禁止 repair_version payload 通过通用 PATCH 更新。
- branch report 漏掉 unmaterialized 版本；已改为保留完整状态。
- 前端 diff 只看 active 导致归档祖先断链；已改为沿完整 parent chain 重建。

修复后复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。
