# Phase 4 Review: Evaluation-to-Repair Branch

## 阶段目标

第四阶段目标是把 Image Optimization Board 里的评分结果变成可执行的画布分支，而不是只把分数展示在候选卡上。核心链路是：精选候选图 → 评价节点 → 修复 Prompt Program → 后续再生成 / Final JSON lineage。

这一步让系统从“能看出问题”推进到“能基于问题继续生产”。

## 已完成内容

- 候选图卡片新增“从评分生成修复分支”动作：
  - 仅允许已精选、已回写画布节点的候选图发起。
  - 动作执行中会显示候选级 loading 状态。
- 前端会从候选图 evaluation metadata 生成画布原生节点：
  - `evaluation` 节点：记录总分、维度分、修复目标、优化建议、优化 Prompt。
  - `prompt_program` 节点：记录基于低分维度和修复建议生成的修复 Prompt Program。
- 画布边关系新增并接入 lineage：
  - `evaluated_by`：精选图 → 评价节点。
  - `repair_prompt`：评价节点 → 修复 Prompt Program。
- 修复 Prompt Program 会保留源候选图资产引用：
  - `referenced_asset_ids`
  - `source_node_ids`
  - `optimization_prompt`
  - `workflow: evaluation_repair_phase_4`
- Final JSON lineage 已包含修复链路：
  - `repair_prompt` edge。
  - `evaluation` 节点中的 `optimization_prompt`、`score`、`total_score`、`repair_targets`。
  - 修复 Prompt Program 的语义字段和来源节点。
- 图谱选区逻辑已修复：
  - 选中修复 Prompt Program 或 evaluation 节点时，当前编译作用域会保留原始 `selected_image`。
  - 避免修复分支退化成不带源图的纯文本重写。
- 精选图保护已补齐：
  - 如果精选图已有下游修复分支，候选卡禁用“淘汰”动作。
  - 避免删除源精选图后留下孤立 evaluation / repair Prompt Program 节点。

## 方向复盘

方向是正确的。

这一阶段真正把“评分”变成了“生产动作”。候选图不再只是被动结果，而是可以进入专业设计师常见的分支式工作流：看到低分维度、生成修复目标、保留原图、创建修复版本链路，再把链路提交进最终生产 JSON。

这比单纯在 UI 上显示一个“优化建议”更接近工业级图片优化器，因为系统开始具备可追踪、可审计、可继续生成的优化闭环。

## 仍未达到工业级的部分

- 修复 Prompt Program 目前由前端基于 evaluation metadata 组装，还没有调用 LMM 对局部缺陷进行二次诊断。
- `evaluation` 节点是从候选图已有评分 materialize 而来，还不是完整的独立评估任务节点。
- 修复分支目前生成的是 Prompt Program，后续仍需要一键发起编辑 / 再生成任务，形成“修复 Prompt → 新候选图”的闭环。
- 还没有 side-by-side 放大对比、局部区域标注、版本差异解释。
- 还没有按项目目标调整评分维度权重，例如主体一致性优先、文字准确优先、构图探索优先。

## 是否继续按当前路线推进

继续。

下一阶段应进入 Phase 5：Repair-to-Generation Loop。

阶段目标：让修复 Prompt Program 不只是节点，而是可以直接驱动图片编辑或再生成，把“评价 → 修复 Prompt”推进到“评价 → 修复 Prompt → 新图片候选 → 再评价”。

建议下一阶段重点：

1. 从修复 Prompt Program 一键发起图片编辑或再生成。
2. 新生成的修复图作为新候选 / edited image 节点回写画布。
3. 用 `repair_generated` 或 `image_edit` edge 连接修复 Prompt 和新图。
4. 让新图继续带 evaluation metadata，支持多轮修复。
5. Final JSON 中区分原始候选图、修复 Prompt、修复生成图和最终入选图。

## 本阶段静态检查

已人工检查关键路径：

- `frontend/src/workspace/CanvasWorkspaceController.jsx`
- `frontend/src/workspace/CanvasWorkspaceComponents.jsx`
- `frontend/src/workspace/canvasUtils.js`
- `src/models/canvas.py`
- `src/agents/canvas_graph_compiler.py`
- `src/api/canvas_routes.py`

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。

## 审查后修复

第一次 code-reviewer 静态审查发现：

- 高优先级：选中修复 Prompt Program 后，图谱作用域会丢失源 `selected_image`，导致后续生成退化为纯文本修复。
- 中优先级：已有修复分支后仍可淘汰精选图，可能留下孤立 evaluation / repair Prompt Program 节点。

已修复：

- `selectedSourceNodeIds()` 支持沿 `selected_image → evaluation → prompt_program` 的修复分支保留源精选图。
- 候选卡会识别已有下游 `repair_prompt` lineage 的精选图，并禁用淘汰动作。
- 补齐 `repairingCandidateId` 的 state 解构，避免页面渲染时 ReferenceError。

最终 code-reviewer 复核无 CRITICAL/HIGH/MEDIUM 问题。
