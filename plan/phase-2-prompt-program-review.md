# Phase 2 Review: Prompt Program 与 @资产感知结构

## 阶段目标

第二阶段目标不是继续做表面 UI，而是把画布从“节点摆放工具”推进到专业设计师可使用的 Prompt 生产系统：选中一个简报、语义规格或参考资产图谱后，可以生成可编辑的 Prompt Program，并把主体、场景、构图、光线、镜头和负面约束拆成可控生产块。

## 已完成内容

- 前端新增从当前选中图谱生成 `prompt_program` 节点的动作。
- Prompt Program 会记录：
  - `subject_block`
  - `scene_block`
  - `composition_block`
  - `lighting_block`
  - `camera_block`
  - `negative_prompt`
  - `reference_instruction`
  - `referenced_asset_ids`
  - `referenced_asset_mentions`
  - `source_node_ids`
- Inspector 对 `prompt_program` 使用专门编辑面板，不再只显示安全字段。
- Prompt Program 编辑保存走 canvas node PATCH，不新建孤立状态。
- 后端 canvas payload 白名单已允许 Prompt Program 字段和 @资产引用字段。
- Canvas Graph Compiler 已把 Prompt Program 编入 `prompt_spec` 上下文。
- Final JSON lineage 已包含 Prompt Program 关键字段和引用列表。

## 方向复盘

方向是正确的。

这一步解决了画布“存在意义”的核心问题之一：画布节点不只是视觉元素，而是能形成可审计、可编辑、可编译的专业生成结构。Prompt Program 让后续图片批量生成不再只依赖一段自然语言，而是可以从画布图谱中获得结构化约束。

## 仍未达到工业级的部分

- 当前 Prompt Program 生成仍是前端本地模板编排，尚未真正调用 LMM/LLM 对 brief 和 @资产进行深层语义拆解。
- Inspector 已可编辑生产块，但还没有版本对比、评分反馈回写、自动修复建议。
- @资产引用已进入 Prompt Program，但还没有把不同 reference role 转换为更细粒度的模型参数或多模态 attention 策略。
- Final JSON 已包含 prompt program lineage，但还没有形成完整的“评分 → 修复 → 再生成”闭环。

## 是否继续按当前路线推进

继续，但下一阶段不能继续扩表单或堆按钮。

下一阶段应进入 Image Optimization Board / LMM Evaluation：

1. 对图片批次候选建立专业评分节点或评价摘要。
2. 把评分维度和缺陷解释回写画布，而不是只显示分数。
3. 允许从评分结果生成修复 Prompt Program 或编辑分支。
4. 让精选图、淘汰图、评分原因、修复目标都进入 Final JSON lineage。

这比继续打磨普通样式更接近专业平台的核心能力。

## 本阶段静态检查

已人工检查关键路径：

- `frontend/src/workspace/CanvasWorkspaceController.jsx`
- `frontend/src/workspace/CanvasWorkspaceComponents.jsx`
- `frontend/src/api/canvas.js`
- `src/models/canvas.py`
- `src/agents/canvas_graph_compiler.py`
- `src/api/canvas_routes.py`

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。

## 审查后修复

代码审查后已补齐以下问题：

- Prompt Program 和 semantic spec 不再只进入 artifact，而是会压平成 `subject`、`environment`、`camera_and_composition`、`lighting`、`style`、`negative_prompt` 等实际生成字段。
- `PromptSpecCompiler` 的最终 Prompt 会包含来自 Prompt Program 的负面约束。
- Canvas payload 从“只校验已知字段类型”调整为拒绝未知字段，同时保留现有图片、视频、Prompt Program、series frame 和 lineage payload 字段。
- Prompt Program 创建时如果边创建失败，会回滚刚创建的节点，避免留下孤立节点。
- Final JSON lineage 保留 `source_node_ids`、`series_lineage` 和 `series_frame`，避免系列分镜链路丢失。
- 最终 code-reviewer 复核无 CRITICAL/HIGH/MEDIUM 问题。

## 下一阶段建议

进入 Phase 3：Image Optimization Board 与 LMM Evaluation 节点。

阶段目标：让每张候选图在画布中形成“可比较、可解释、可修复”的优化对象，而不是只作为缩略图列表存在。