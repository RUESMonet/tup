# Phase 12 Review: Branch Layout, Audit Trail & Active Production Path

## 阶段目标

第十二阶段目标是把 Phase 11 的分支治理继续推进到画布布局、操作审计和主生产路径表达。

Phase 11 已经提供显式 repair version 分支状态接口、侧栏树直接定位 / 归档 / 恢复，以及 Final JSON 的 branch diff report。Phase 12 要进一步解决三个专业设计师真正会遇到的问题：版本节点在画布里如何排布、分支操作是否可审计、Final JSON 如何标出当前推荐的 active production path。

核心链路是：branch status operation → audit trail → branch tree auto-layout → active production path → Final JSON production lineage。

## 已完成内容

- Repair version 分支状态接口增加审计记录：
  - archive / restore 时会追加 `branch_audit_trail`。
  - 每条审计记录包含：
    - `operation`
    - `from_status`
    - `to_status`
    - `at`
  - 审计记录保留最近 12 条，避免 payload 无限增长。
- Canvas payload 校验支持并约束 `branch_audit_trail`：
  - 必须是 list。
  - 每项必须是 object。
  - 必须只包含 `operation`、`from_status`、`to_status`、`at`。
  - `operation` 只允许 `archive` / `restore`。
  - status 值必须在允许集合内。
- Final JSON repair version lineage 输出 `branch_audit_trail`。
- Final JSON branch report 的 version 项也输出 `branch_audit_trail`。
- Final JSON production lineage 增加 `active_production_path`：
  - 从 repair branch reports 中选择当前可用 active path。
  - 只允许全链路都是 active 的 path 进入 active production path。
  - 如果 path 中存在 archived ancestor，则不会被标记为 active production path。
  - 输出 `branch_id`、`version_count`、`score_start`、`score_end`、`score_delta`、`versions`。
- 前端 Image Batch Studio 增加“分支布局”动作：
  - 对已物化的 `repair_version` 节点进行 branch tree layout。
  - 基于 `repair_parent_batch_id` / repair context parent batch chain 构建父子关系。
  - root 到 child 横向展开，同层叶子纵向排列。
  - 父节点 y 坐标居中到子节点集合。
  - 布局结果通过 `updateCanvasNodePositions(...)` 持久化。
- 分支布局增加循环保护：
  - 即使历史 payload 中存在异常 parent cycle，也不会无限递归导致浏览器栈溢出。
- Final JSON Preview 增加 Active Path 摘要：
  - 展示 active production path 的 version 数和最终分数。

## 方向复盘

方向是正确的。

Phase 12 解决的是专业工作台里很关键的“生产治理”问题：设计师不只需要看到版本，还需要知道哪个版本链是当前主生产路径、谁被归档过、归档/恢复发生过几次、画布节点是否能形成可读的分支结构。

这一步让平台继续远离“图片列表工具”，更接近专业设计师使用的创作图谱系统：画布负责空间化表达，Final JSON 负责可审计交付，branch operation 负责版本治理。

## 本阶段修正的关键问题

首次静态审查发现 2 个 HIGH 和 1 个 MEDIUM：

1. `branch_audit_trail` 只加入 allowed fields，但没有强校验结构。
2. archived parent 后，active descendant 仍可能被导出为 active production path，导致路径里混入 archived 祖先。
3. 前端分支布局没有 cycle protection，异常 parent link 可能导致递归溢出。

已修复：

- 增加 `_validate_branch_audit_trail(...)`，严格校验审计记录结构。
- `active_production_path` 只接受所有 ancestor 都是 active 的 path。
- `repairVersionLayoutPositions()` 增加 path 检测和未布局节点兜底，避免循环递归。

复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

## 仍未达到工业级的部分

- 当前 audit trail 存在 node payload 中，还不是独立 audit log 表。
- 审计记录没有记录操作者身份展示、原因、备注或批量操作范围。
- 分支布局是前端触发的 layout，不是后端保存的 layout strategy 或自动维护的 graph layout engine。
- 分支布局只处理已物化 repair_version node，未物化版本不会在画布中占位。
- active production path 目前按最高 `score_end` 选择，没有引入更多专业策略，例如稳定性、退化维度数量、归档历史、人工 pin 主分支。
- 还没有事务式子树 archive / restore。
- 还没有 safe delete branch 的事务边界。

## 是否继续按当前路线推进

继续。

下一阶段应进入 Phase 13：Pinned Production Path & Subtree Branch Operations。

阶段目标：让设计师能够显式 pin 当前主生产路径，并把 archive / restore 从单节点操作扩展为可控的子树级事务操作。

建议下一阶段重点：

1. 增加 `pinned_production_path` / `is_primary_path` 状态，允许设计师人工指定主分支。
2. Final JSON 优先输出 pinned path；没有 pinned 时再按分数选择 active path。
3. 增加 subtree archive / restore 操作，明确是否包含 descendants。
4. 增加操作原因 reason 字段，写入 audit trail。
5. 设计独立 branch operation log 表，为多人协作和审计做准备。
6. 在 UI 上区分 auto-selected active path 与 designer-pinned path。

## 本阶段静态检查

已使用 code-reviewer 做 Phase 12 静态审查。

首次审查发现并修复：

- `branch_audit_trail` 校验不足；已增加严格结构校验。
- active production path 可能包含 archived ancestor；已改为只接受全 active 链路。
- 分支布局递归缺少 cycle protection；已增加循环保护和未布局节点兜底。

修复后复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。
