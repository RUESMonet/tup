# Phase 5 Review: Repair-to-Generation Loop

## 阶段目标

第五阶段目标是让 Phase 4 生成的修复 Prompt Program 不停留在“可编辑节点”，而是可以直接驱动新一轮图片候选生成，形成最小闭环：

精选候选图 → 评价节点 → 修复 Prompt Program → 修复候选图批次 → 再精选 / 再评价 / Final JSON。

核心不是新增一个按钮，而是确保修复分支在编译时真的以修复 Prompt Program 为主语，同时不丢失原始 brief 和源候选图。

## 已完成内容

- 修复 Prompt Program Inspector 区域新增“生成修复候选图”入口：
  - 仅在选中 `workflow: evaluation_repair_phase_4` 的 `prompt_program` 节点时出现。
  - 点击后创建一个 2 张图的修复候选图批次。
  - 批次仍复用现有 Image Batch pipeline，因此候选图会继续进入 Image Optimization Board。
- 修复候选图批次使用画布原生选区：
  - `selectedSourceNodeIds(canvas, repairPrompt.id)` 会保留修复 Prompt、evaluation 节点、原始精选图和相关源图谱。
  - `root_node_id` 指向当前修复 Prompt Program，确保本轮生成以修复 Prompt 为优先 Prompt Program。
- 后端编译请求新增 `root_node_id`：
  - `CanvasCompileRequest`
  - `CanvasGenerateImageRequest`
  - `CanvasFinalSubmitRequest`
- 后端路由已校验 `root_node_id` 必须属于 `selected_node_ids`：
  - `/api/canvases/{canvas_id}/compile`
  - `/api/canvases/{canvas_id}/generate/image`
  - `/api/canvases/{canvas_id}/image-batches`
  - `/api/canvases/{canvas_id}/final-submit`
- Final JSON 提交也会发送当前选中节点作为 `root_node_id`：
  - 选中修复 Prompt Program 预览/提交 JSON 时，会以该修复 Prompt 作为当前生产分支主语。
- 编译器已收窄 root 的影响范围：
  - `root_node_id` 仍可让修复 Prompt Program 在多个 Prompt Program 中优先生效。
  - 真实 `brief` 节点仍优先作为 `primary_brief`，避免修复 Prompt 覆盖原始创意简报。
- `CanvasGenerateImageRequest.root_node_id` 已做 strip/blank 校验，与 compile/final-submit 请求保持一致。

## 方向复盘

方向是正确的。

这一阶段把系统推进到“闭环优化”的第一版：设计师不需要复制优化建议，也不需要手动重建上下文。只要选中修复 Prompt Program，就可以直接生成新候选图；新候选图仍会保留候选评分、精选、淘汰、视频延展和 Final JSON lineage。

关键改进是 `root_node_id`。如果没有它，修复分支虽然在画布上存在，但后端编译时可能仍按旧 brief / 旧 Prompt Program 顺序取主语，导致“看起来在修复，实际还在按旧 Prompt 生成”。现在修复分支可以成为当前生产主语，同时原始 brief 不被覆盖。

## 仍未达到工业级的部分

- 修复候选图目前默认生成 2 张，还没有为修复分支提供独立参数面板，例如修复强度、保留/可变区域、局部编辑模式。
- 修复生成仍是批次级再生成，还没有自动把新候选图与修复 Prompt Program 建立专门的 `repair_generated` edge；目前 lineage 主要通过 batch `source_node_ids` 和候选精选后的 `selected_candidate` edges 保留。
- 新候选图完成后还没有自动展开 side-by-side 对比原图和修复图。
- 还没有让 LMM 针对新修复图自动生成“是否解决了上一轮 repair_targets”的差异解释。
- 还没有版本树视图，设计师无法一眼看到同一候选图的多轮修复分支深度。

## 是否继续按当前路线推进

继续。

下一阶段应进入 Phase 6：Repair Versioning & Comparison。

阶段目标：把多轮修复从“批次列表”升级为可比较的版本树。专业设计师需要看到原图、修复 Prompt、新图、评分变化、低分项是否改善，而不是只看到又多了几张候选图。

建议下一阶段重点：

1. 为修复批次和候选图标记 repair lineage profile，区分普通探索批次与修复批次。
2. 在 Image Optimization Board 中展示“来自哪个修复 Prompt Program”。
3. 增加原候选图 vs 修复候选图的 score delta。
4. 增加 side-by-side 对比入口。
5. Final JSON 中明确输出 repair iterations / repair_versions。

## 本阶段静态检查

已人工检查关键路径：

- `frontend/src/workspace/CanvasWorkspaceController.jsx`
- `frontend/src/workspace/CanvasWorkspaceComponents.jsx`
- `frontend/src/workspace/canvasUtils.js`
- `src/models/canvas.py`
- `src/api/canvas_routes.py`
- `src/agents/canvas_graph_compiler.py`

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。

## 审查后修复

第一次 code-reviewer 静态审查发现：

- 高优先级：`root_node_id` 影响了整个节点排序，可能让修复 Prompt Program 覆盖真实创意 brief。
- 中优先级：`CanvasGenerateImageRequest.root_node_id` 没有像 compile/final-submit 一样做 strip/blank 校验。

已修复：

- `_primary_brief()` 现在优先选择真实 `brief` 节点；只有没有 brief 时才回退到其他带 prompt/brief/instruction 的节点。
- 修复 Prompt Program 仍可通过 `root_node_id` 在 Prompt Program 提取中优先，但不会替代真实创意 brief。
- `CanvasGenerateImageRequest.root_node_id` 已补齐 strip 和空值校验。

最终 code-reviewer 复核无 CRITICAL/HIGH/MEDIUM 问题。
