# Phase 6 Review: Repair Versioning & Comparison

## 阶段目标

第六阶段目标是把修复生成从“又多了一个图片批次”升级为可识别、可比较、可保护的修复版本链路。

核心链路是：原始精选图 → evaluation → repair Prompt Program → repair image batch → 修复候选图评分变化 → Final JSON repair_versions。

专业设计师需要知道一张修复图从哪里来、相对原图有没有变好、能不能继续修复，而不是只看到普通候选图列表继续膨胀。

## 已完成内容

- 图片批次 API 返回服务端计算的 `repair_context`：
  - `is_repair_version`
  - `repair_prompt_node_id`
  - `repair_prompt_title`
  - `evaluation_node_id`
  - `source_image_node_id`
  - `source_image_title`
  - `baseline_score`
  - `candidate_deltas`
- 候选图 API 返回 `repair_protected`：
  - 如果精选图已经成为修复分支源图，则不能被普通淘汰动作删除。
- 前端 Image Batch Studio 使用服务端字段渲染修复版本：
  - repair batch 会显示 Repair Version 区块。
  - 显示来源修复 Prompt、来源精选图和基准分。
  - 每张修复候选图显示相对原图的 score delta。
  - delta 上升/下降有不同颜色提示。
- Final JSON production lineage 增加 `repair_versions`：
  - 输出修复批次 id、状态、修复 Prompt 节点、evaluation 节点、源精选图节点、基准分。
  - 输出每个修复候选图的 score 和 score_delta。
- 修复保护从 UI 提示升级为后端强约束：
  - PATCH 候选状态时，已保护精选图不能切换到非 selected。
  - DELETE selected_image 节点时，已保护精选图返回 409。
  - DELETE repair evaluation / repair Prompt 节点时，如果它们参与保护链路，会返回 409。
  - DELETE `evaluated_by` / `repair_prompt` 关键边时，如果它们参与保护链路，会返回 409。
- 创建修复分支后会刷新画布产物，确保候选卡上的 `repair_protected` 立即与后端一致。

## 方向复盘

方向是正确的。

这一阶段把修复能力从“生成动作”推进到了“版本管理”。这对专业设计师很关键：他们需要比较版本，而不是在一堆候选图里靠记忆判断哪张来自哪次修复。现在系统能识别修复批次、显示来源、计算相对分数变化，并在 Final JSON 中保留 repair_versions。

更重要的是，这一阶段补上了数据完整性保护。修复链路一旦建立，源精选图和关键修复节点/边不能被随意删除，否则 Final JSON lineage 会断裂。现在 UI 和 API 都有保护，不再只是前端禁用按钮。

## 仍未达到工业级的部分

- 现在只有 score delta，还没有每个维度的 delta，例如构图 +1.2、主体一致性 -0.3、技术质量 +0.8。
- 还没有 side-by-side 放大对比视图，无法细看局部细节是否真的修复。
- 还没有版本树 UI，只是在批次卡片上识别 repair version。
- 还没有 LMM 生成“修复是否解决上一轮 repair_targets”的自然语言差异解释。
- 保护策略现在偏保守：修复分支建立后不能直接删除关键节点，后续需要提供“删除整个修复分支”的显式安全动作。

## 是否继续按当前路线推进

继续。

下一阶段应进入 Phase 7：Side-by-side Review & Dimension Delta。

阶段目标：让设计师能在画布内比较原图与修复图，不只看总分，而是看每个维度是否改善，并能继续选择下一轮修复方向。

建议下一阶段重点：

1. 在 repair candidate 上计算维度级 delta。
2. 增加原图 / 修复图 side-by-side 对比入口。
3. 显示 repair_targets 是否被解决。
4. 为下一轮修复提供“继续修复这个维度”的动作。
5. Final JSON 输出 dimension_deltas 和 resolved_targets。

## 本阶段静态检查

已人工检查关键路径：

- `frontend/src/workspace/CanvasWorkspaceComponents.jsx`
- `frontend/src/workspace/CanvasWorkspaceController.jsx`
- `frontend/src/workspace/canvas-layout.css`
- `src/models/canvas.py`
- `src/api/canvas_routes.py`

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。

## 审查后修复

code-reviewer 静态审查后陆续修复：

- 修复版本推导从前端迁移到后端 API，避免 UI 和 Final JSON 各算一套。
- `repair_context` 成为 Image Batch Studio 和 Final JSON 的统一来源。
- `repair_protected` 成为候选卡禁用淘汰动作的服务端字段。
- PATCH 候选状态增加 409 保护，防止直接 API 淘汰受保护精选图。
- DELETE selected_image 节点增加 409 保护，防止绕过候选状态接口。
- DELETE 修复分支节点和关键边增加 409 保护，防止先拆 lineage 再删除源图。

最终 code-reviewer 复核无 CRITICAL/HIGH/MEDIUM 问题。
