# Phase 3 Review: Image Optimization Board 与 LMM Evaluation

## 阶段目标

第三阶段目标是把图片候选从“缩略图列表”升级为专业图片优化对象。核心不是多展示几张图，而是让每张候选图都带有可解释评分、维度拆解、修复目标，并能进入最终 JSON 的生产链路。

## 已完成内容

- 图片批次后台任务现在会把视觉评分结果写入候选图 metadata：
  - 总分
  - 构图评分
  - 主体一致性评分
  - 风格一致性评分
  - 技术质量评分
  - 修复目标
  - 优化建议
  - 优化 Prompt
- 前端 `Image Batch Studio` 从简单候选卡升级为 Image Optimization Board：
  - 每张候选图显示评分维度条。
  - 每张候选图显示修复目标。
  - 保留精选、淘汰、图生视频动作。
- Final JSON 的 candidate lineage 会包含候选图 evaluation 摘要，避免评分和修复原因只停留在 UI。

## 方向复盘

方向是正确的。

这个阶段开始把“图片优化器”的核心能力放入画布生产流：候选图不再只是生成结果，而是可比较、可解释、可分支的优化单元。它为后续“从低分维度自动生成修复 Prompt Program / 图片编辑分支”打下了数据基础。

## 仍未达到工业级的部分

- 当前评分来自已有 `VisualReport`，还没有在画布中 materialize 成独立 `evaluation` 节点。
- 修复目标已经展示和进入 JSON，但还不能一键生成修复分支。
- 维度权重目前固定，尚未支持设计师按项目目标调整权重，例如产品一致性优先、构图探索优先、文字准确优先。
- 候选图之间还没有 side-by-side 放大对比、局部细节检查、版本差异解释。

## 是否继续按当前路线推进

继续。

下一阶段应把 Image Optimization Board 的评价结果转化为可执行动作：

1. 从候选图评价生成“修复 Prompt Program”。
2. 从低分维度创建 `evaluation` / `repair_target` 节点。
3. 允许设计师基于某张候选图发起图片编辑分支。
4. 把修复动作与原始候选图通过边连接，进入 Final JSON lineage。

这会让系统从“能看评分”推进到“能基于评分自动优化”。

## 本阶段静态检查

已人工检查关键路径：

- `src/api/canvas_routes.py`
- `frontend/src/workspace/CanvasWorkspaceComponents.jsx`
- `frontend/src/workspace/canvas-layout.css`

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。

## 审查后修复

代码审查后已补齐以下问题：

- Final JSON candidate evaluation 中的总分和维度分数会被归一化到 0-10，非法值会被丢弃为 `null`。
- 前端评分条会防御非数字、NaN 或异常旧数据，避免生成非法 CSS 宽度。
- 最终 code-reviewer 复核无 CRITICAL/HIGH/MEDIUM 问题。

## 下一阶段建议

进入 Phase 4：Evaluation-to-Repair Branch。

阶段目标：把评分最低的维度和修复建议转化为画布节点和可执行生成动作，形成“候选图 → 评价 → 修复 Prompt → 编辑/再生成”的闭环。