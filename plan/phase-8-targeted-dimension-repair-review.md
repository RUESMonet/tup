# Phase 8 Review: Targeted Dimension Repair & Version Tree

## 阶段目标

第八阶段目标是让修复从“看见差异”进入“基于差异继续行动”。

Phase 7 已经能展示原图 / 修复图对比、总分 delta、维度 delta 和 resolved targets；Phase 8 要把这些审阅信息变成下一轮生产动作：设计师可以从某个低分或仍需增强的维度直接生成定向修复 Prompt Program，并在批次区域看到修复版本链路。

核心链路是：维度 delta → 继续修复此维度 → focused evaluation → focused repair Prompt Program → repair image batch → Final JSON repair_focus lineage。

## 已完成内容

- 前端候选卡的维度 delta 增加“继续修复”动作：
  - 只在候选图已经精选并回写为 canvas node 时显示。
  - 避免未回写画布的候选出现无效动作。
- side-by-side 对比弹窗增加维度级继续修复动作：
  - 每个 dimension delta 都可以成为下一轮修复焦点。
  - 同样只在候选图有 canvas node 时显示。
- `createRepairBranchFromCandidate` 支持定向维度参数：
  - 生成 focused evaluation node。
  - 生成 focused repair Prompt Program。
  - payload 写入 `repair_focus_key`、`repair_focus_label`、`repair_parent_batch_id`。
  - repair Prompt Program 写入 `repair_iteration`。
- 定向修复 Prompt Program 会把维度差异编译为明确的修复指令：
  - 包含 baseline score、current score、delta。
  - 明确“只强化这个维度并保持其他维度稳定”。
- 后端 canvas payload 白名单支持新增修复元数据：
  - `repair_focus_key`
  - `repair_focus_label`
  - `repair_parent_batch_id`
  - `repair_iteration`
- 后端 `repair_context` 增加 `repair_focus`：
  - `key`
  - `label`
  - `parent_batch_id`
  - `iteration`
- Final JSON 的 `production_lineage.repair_versions` 输出 `repair_focus`。
- 前端 Image Batch Studio 增加 Repair Version Tree：
  - 展示最多 6 个修复版本。
  - 使用后端 `repair_focus.iteration` 显示真实迭代序号。
  - 使用 `repair_focus.parent_batch_id` 表达父子链路。
  - 展示每个版本的最佳 score delta 和候选数量。

## 方向复盘

方向是正确的。

Phase 8 把修复链路从“评价展示”推进到了“设计决策驱动生产”。这对专业设计师很关键：看到某个维度没有改善时，不需要重新写大段提示词，也不需要猜下一步怎么修，而是可以直接把该维度变成下一轮修复 Prompt Program。

版本树虽然还不是完整无限画布图形版本树，但已经开始使用真实 lineage 元数据，而不是简单按列表顺序展示。这样后续可以自然升级为节点式版本树、分支归档、分支删除和多轮修复比较。

## 仍未达到工业级的部分

- Repair Version Tree 目前仍是侧栏摘要，不是画布内可折叠的图形版本树。
- 定向修复 Prompt Program 由现有评分 delta 生成，还没有调用 LMM 对“为什么这个维度失败”做二次解释。
- 还没有把局部区域、mask 或 crop 与某个维度绑定。
- 还没有自动建议“最应该继续修复的维度”。
- 删除/归档修复分支仍没有显式安全动作，后端当前仍偏保守地锁定关键节点和边。

## 是否继续按当前路线推进

继续。

下一阶段应进入 Phase 9：Canvas-native Version Graph & Branch Operations。

阶段目标：把当前侧栏版 Repair Version Tree 升级为真正的画布内版本图谱，并提供安全的分支级操作。

建议下一阶段重点：

1. 在画布中物化 repair version 节点或 version group。
2. 用边表达 parent repair batch / child repair batch。
3. 提供“归档整个修复分支”和“删除整个修复分支”的显式安全动作。
4. 支持从版本树选择任意版本继续修复。
5. Final JSON 输出 repair branch operations / archived branches。

## 本阶段静态检查

已使用 code-reviewer 做 Phase 8 静态审查。

首次审查发现并修复：

- “继续修复”按钮虽然 disabled，但仍显示在未回写画布的候选图上；已改为完全隐藏。
- Repair Version Tree 使用渲染顺序伪造版本号；已改为使用后端 `repair_focus.iteration` 和 `repair_focus.parent_batch_id`。

修复后复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。
