# Phase 1 Review: LMM Semantic Canvas Skeleton

## 本阶段目标

把画布从“媒体节点板”推进到“语义生产图谱”的第一阶段骨架，而不是继续在现有图片/视频节点上堆按钮。

## 已完成

### 1. 前端语义骨架初始化

新增画布动作：初始化 LMM 语义生产骨架。

依赖已有 brief 节点，自动创建：

- `semantic_spec`：LMM 语义规格
- `prompt_program`：Prompt Program
- `evaluation`：LMM 评分规则
- `scene`：场景容器
- `shot`：镜头节点
- `final_json`：Production JSON 节点

并创建语义边：

- `brief -> semantic_spec`：semantic_analysis
- `semantic_spec -> prompt_program`：compiled_to_prompt
- `prompt_program -> evaluation`：evaluated_by
- `semantic_spec -> scene`：plans_scene
- `scene -> shot`：contains_shot
- `shot/evaluation -> final_json`：included_in_final

### 2. 前端节点表达升级

新增语义节点显示标签和样式：

- Semantic
- Prompt Program
- Evaluation
- Scene
- Shot
- Final JSON

Inspector 现在能展示：

- 生产目标
- 主体语义
- 视觉风格
- Prompt 结构
- 评分维度
- JSON 章节

### 3. Canvas 编译器保留语义 payload

`CanvasGraphCompiler` 的安全 payload 白名单扩展为支持：

- semantic spec 字段：`goal`、`subject`、`must_keep`、`can_change`、`negative_constraints`
- prompt program 字段：`subject_block`、`scene_block`、`composition_block`、`lighting_block`、`camera_block`
- shot/final 字段：`motion_prompt`、`duration`、`aspect_ratio`、`manifest_sections`

同时把 semantic spec / prompt program 放入 prompt payload，后续可继续深化为真实 Prompt Program Builder。

### 4. Final JSON production_lineage 升级

`production_lineage` 增加：

```json
{
  "semantic_manifest": {
    "briefs": [],
    "semantic_specs": [],
    "prompt_programs": [],
    "evaluations": [],
    "scenes": [],
    "shots": [],
    "final_json_nodes": []
  }
}
```

并把语义边纳入 lineage：

- semantic_analysis
- compiled_to_prompt
- evaluated_by
- plans_scene
- contains_shot
- included_in_final

## 本阶段审视

方向是正确的。

原因：

1. 没有继续做浅层“图片/视频编辑按钮”。
2. 先把画布信息架构改成专业生产图谱。
3. 当前实现不依赖真实 LMM 调用，风险低，但已经让数据结构、UI 和 Final JSON 都能承载后续阶段。
4. 后续 Prompt Program、图片优化、视频 Shot 都有明确挂载点。

## 当前不足

本阶段仍然是“骨架”，不是完整智能化：

1. `semantic_spec` 还是模板节点，没有真实 LMM 语义分析。
2. `prompt_program` 还是结构化占位，没有接入 RAG/PromptOptimizer 自动编译。
3. `evaluation` 是评分规则节点，还没有自动为候选图创建 evaluation 节点。
4. `scene/shot` 只是视频生产结构，还没有替代旧的 Series Director / 视频候选流程。
5. UI 已经可承载语义节点，但左侧仍然偏“控制面板”，后续需要升级成 Production Rail。

## 是否继续按原路线进行

继续，但下一阶段必须进入 Prompt Program，而不是继续做样式。

正确的下一阶段是：

## Phase 2: Prompt Program + @资产引用深化

目标：

- 把 prompt 从一段 textarea 变成可编辑的专业 Prompt Program。
- 把 @资产引用写入 Prompt Program payload，而不是只存在 brief 字符串里。
- 为图片批次生成提供更明确的 prompt block 输入。

建议实现：

1. 新增 Prompt Program inspector：
   - 主体 block
   - 场景 block
   - 构图 block
   - 光线 block
   - 镜头 block
   - 负面约束 block
2. 从 selected brief + asset nodes 生成/更新 Prompt Program 节点。
3. `createImageBatchFromSelection` 优先读取 Prompt Program 结构。
4. Final JSON 中新增 `prompt_programs` 的更完整结构。

## 代码审查后修正

阶段代码审查发现并已修正：

1. 图片批次初始 `pending` 状态没有进入自动刷新范围，导致候选图可能看起来卡住；已把 `pending` 纳入前端 active batch 状态。
2. Final JSON 的 `production_lineage` 原先按整张画布收集，可能混入其他分支；已改为只收集提交图谱的 selected node 范围、范围内边和关联批次。
3. edge payload 原先原样写入 lineage；已改为只保留安全标量/短列表并截断长文本。
4. 复审发现 Final JSON 如果只提交源图谱会漏掉下游图片编辑/视频结果；已改为从提交节点沿生产边向下游追踪结果节点。
5. 复审发现宽批次候选可能混入窄范围提交；已改为批次 source node 必须完整包含在 lineage 范围内才进入 Final JSON。
6. 终审发现先取最近 20 个批次再过滤可能漏掉旧的相关批次；已改为 Final JSON 先取全部批次、按 lineage 过滤后再截断到 20。

## 测试策略

按用户约束：没有明确要求，不主动运行测试或 build。

建议用户需要验证时手动运行：

```bash
npm run build
.venv/bin/python -m pytest tests/test_canvas_routes.py tests/test_canvas_graph_compiler.py
```
