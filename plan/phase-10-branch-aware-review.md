# Phase 10 Review: Branch-aware Review & Safe Branch Operations

## 阶段目标

第十阶段目标是把 Phase 9 的画布内修复版本图谱推进到分支级管理。

Phase 9 已经支持把 repair batch 物化为 `repair_version` canvas node，并通过 `repair_version_source` / `repair_version_child` 表达来源和父子关系；Phase 10 要让设计师能区分 active / archived 分支，恢复归档分支，并在 Final JSON 中明确表达 active 与 archived 的生产状态。

核心链路是：repair_version node status → active / archived UI → restore archive → branch trend → Final JSON active_repair_versions / archived_repair_versions。

## 已完成内容

- Image Batch Studio 的 Repair Version Tree 支持分支状态统计：
  - `active`
  - `archived`
  - `unmaterialized`
- Repair Version Tree 行内显示版本状态：
  - 已物化 active 版本显示为 Active。
  - 已归档版本显示为 Archived，并使用弱化视觉状态。
  - 尚未物化到画布的 repair batch 显示为 Unmaterialized。
- Inspector 支持安全恢复归档分支：
  - active `repair_version` 节点显示“归档修复分支”。
  - archived `repair_version` 节点显示“恢复修复分支”。
  - 两个动作都只更新 `repair_version.payload.status`，不删除源图、evaluation、repair prompt、repair batch 或 lineage edge。
- 增加 Branch Trend 摘要：
  - 只统计已物化的 active 版本。
  - 沿当前 active parent chain 计算，不混合 archived / unmaterialized / sibling 分支。
  - 使用 baseline score + best repair delta 得到可比较的绝对最佳分数，而不是跨不同 baseline 直接比较 delta。
- Final JSON production lineage 增加分支状态分离：
  - `repair_versions` 保留全部 repair version lineage。
  - `active_repair_versions` 只包含 `version_status == "active"` 的已物化版本。
  - `archived_repair_versions` 只包含 `version_status == "archived"` 的已归档版本。
  - `version_status == "unmaterialized"` 的版本不会被误归入 active 分支。

## 方向复盘

方向是正确的。

Phase 10 解决了 Phase 9 之后最关键的产品语义问题：画布里不只是“有版本节点”，而是能表达设计师对版本分支的决策状态。active 分支代表仍在生产路径中的候选修复链，archived 分支代表保留审计和回溯价值但不作为主生产推荐，unmaterialized 则表示后台有 repair batch 但设计师还没有把它纳入画布版本图谱。

这让 Final JSON 更接近专业交付物：它不再只是一组候选图片和视频，而是包含清晰的版本治理信息，能区分当前有效分支和历史归档分支。

## 本阶段修正的关键问题

静态审查首次发现一个 HIGH 问题：未物化的 repair batch 被错误归入 active 分支。

已修复：

- 前端 `RepairVersionTree` 不再把缺少 `repair_version` node 的 repair batch 默认当作 active。
- 后端 Final JSON 不再把 `version_status == "unmaterialized"` 的版本归入 `active_repair_versions`。
- Branch Trend 不再用跨 baseline 的 delta 做趋势比较，改为使用绝对最佳分数，并限制在当前 active parent chain 内。

复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

## 仍未达到工业级的部分

- Repair Version Tree 目前仍在侧栏内展示，不是真正的画布内自动分支树布局。
- archived 分支恢复动作目前需要先选中画布节点，侧栏树行本身还不能直接点击恢复。
- Branch Trend 仍是摘要级指标，还不是完整的分支级 diff report。
- 还没有后端事务式“安全删除整个修复分支”接口。
- archived 分支目前只影响状态表达和 Final JSON 分离，还没有影响推荐、过滤、自动布局或批量操作。
- Final JSON 还没有输出完整 branch report，例如每轮 score、dimension delta、resolved targets 的趋势表。

## 是否继续按当前路线推进

继续。

下一阶段应进入 Phase 11：Transactional Branch Operations & Branch Diff Report。

阶段目标：把当前 archive / restore 的节点级状态管理升级为真正的分支级操作能力，并为专业设计师提供可审计的分支对比报告。

建议下一阶段重点：

1. 在 Repair Version Tree 中支持直接选择 / 定位 / 恢复分支节点。
2. 增加分支级 diff report：按 parent chain 输出每轮 score、dimension delta、resolved targets、退化维度。
3. 增加后端显式 branch operation 接口，避免前端直接写任意 node payload status。
4. 设计安全删除整个修复分支的事务式接口，但默认仍以 archive 为主。
5. 让 archived 状态影响 UI 过滤、推荐排序和 Final JSON active production path。
6. 在画布内实现真正的 repair version branch layout，而不是仅通过侧栏摘要表达。

## 本阶段静态检查

已使用 code-reviewer 做 Phase 10 静态审查。

首次审查发现并修复：

- 未物化 repair batch 被错误归为 active；已改为显式 `unmaterialized` 状态。
- Branch Trend 使用跨 baseline delta，趋势方向可能错误；已改为绝对最佳分数并限制在 active parent chain。

修复后复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。
