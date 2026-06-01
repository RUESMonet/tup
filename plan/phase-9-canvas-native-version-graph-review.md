# Phase 9 Review: Canvas-native Version Graph & Branch Archive

## 阶段目标

第九阶段目标是把修复版本从侧栏摘要推进到真正的画布内版本图谱。

Phase 8 已经能从维度 delta 继续生成定向修复 Prompt Program，并在 Image Batch Studio 中显示 Repair Version Tree。但那个 tree 仍然是侧栏摘要，不是画布图谱的一部分。Phase 9 要让修复版本成为 canvas node，并用 edge 表达来源和父子关系，同时提供非破坏式的分支归档动作。

核心链路是：repair batch → repair_version node → repair_version_source edge / repair_version_child edge → archive-only branch operation → Final JSON version_status。

## 已完成内容

- 前端 Image Batch Studio 增加“版本图谱”动作：
  - 根据当前 repair image batches 物化 `repair_version` 画布节点。
  - 已存在的 repair_version 节点不会重复创建。
- 新增 `repair_version` canvas node：
  - `batch_id`
  - `repair_prompt_node_id`
  - `evaluation_node_id`
  - `source_image_node_id`
  - `source_image_asset_id`
  - `source_image_title`
  - `repair_focus_key`
  - `repair_focus_label`
  - `repair_parent_batch_id`
  - `repair_iteration`
  - `status`
- 新增版本图谱边：
  - `repair_version_source`：源精选图 / evaluation / repair prompt 指向 repair version。
  - `repair_version_child`：父 repair version 指向子 repair version。
- Canvas node UI 支持 `repair_version`：
  - 新 node type label。
  - 专属视觉样式。
  - 节点摘要显示归档状态、修复焦点和源精选图。
- Inspector 增加“归档修复分支”：
  - 只更新 `repair_version.payload.status = archived`。
  - 不删除源图、evaluation、repair prompt、repair batch 或任何关键 lineage。
- 后端 payload 白名单支持 repair version graph 字段。
- 后端 Final JSON lineage 支持 repair version graph：
  - `semantic_manifest.repair_version_nodes` 输出画布中的 repair version 节点。
  - `lineage_edges` 输出 `repair_version_source` 和 `repair_version_child`。
  - 通过 repair_version node 选中图谱时，能把对应 batch 纳入 `repair_versions`。
  - `repair_versions` 区分 `batch_status` 和 `version_status`，避免归档状态与任务状态冲突。
- 后端删除保护升级：
  - `repair_version` 节点不能 DELETE，只能归档。
  - `repair_version_source` / `repair_version_child` 边不能 DELETE。
- 前端图谱选择修复：
  - 选择 `repair_version` 节点后，`selectedSourceNodeIds` 会保留其源精选图，避免后续生成/Final JSON 变成 text-only。

## 方向复盘

方向是正确的。

Phase 9 把修复版本真正放进画布图谱，强化了这个产品的核心差异：不是图片列表工具，而是专业设计师可审计、可分支、可回溯的创作图谱。修复版本现在不仅存在于批次列表和 Final JSON，也可以作为 canvas node 被选择、连线、归档和提交。

本阶段没有实现直接删除整个修复分支，而是先提供 archive-only 操作，这是正确的安全取舍。当前修复链路已经有源图保护、repair prompt/evaluation 保护和版本节点保护，优先保证生产 lineage 不被意外破坏。

## 仍未达到工业级的部分

- 版本图谱目前通过按钮物化，还不是批次生成完成后自动布局。
- 版本边布局仍是线性竖排，没有真正的分支树自动布局。
- 归档状态目前只作用于 `repair_version` node 和 Final JSON 状态表达，还没有影响 UI 列表过滤或生成推荐。
- 还没有“恢复归档分支”。
- 还没有安全删除整个修复分支的事务式后端操作。
- 还没有分支级 diff report，例如比较 V1、V2、V3 的维度趋势。

## 是否继续按当前路线推进

继续。

下一阶段应进入 Phase 10：Branch-aware Review & Safe Branch Operations。

阶段目标：让设计师不仅能看到版本图谱，还能对整个修复分支做专业级操作，包括归档过滤、恢复归档、分支级对比和安全删除整个分支。

建议下一阶段重点：

1. UI 中区分 active / archived repair versions。
2. 增加恢复归档动作。
3. 增加分支级对比报告：每轮 score / dimension delta 趋势。
4. 设计后端“删除整个修复分支”的显式安全接口，确保事务内删除版本节点、修复批次、候选图引用和相关边。
5. Final JSON 输出 archived branch 和 active branch 的分离结构。

## 本阶段静态检查

已使用 code-reviewer 做 Phase 9 静态审查。

首次审查发现并修复：

- 选择 `repair_version` 节点后，源精选图会从 downstream generate / final-submit 的 selected source set 中丢失；已修复。
- 后端仍允许直接 DELETE `repair_version` 节点和版本边，会绕过 archive-only 设计；已修复。
- `repair_versions.status` 使用 batch 执行状态，不能表达归档状态；已改为输出 `status`、`batch_status`、`version_status`。

修复后复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。
