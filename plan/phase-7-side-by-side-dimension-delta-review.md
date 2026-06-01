# Phase 7 Review: Side-by-side Review & Dimension Delta

## 阶段目标

第七阶段目标是把修复版本从“总分是否变高”推进到“设计师能判断具体哪里变好”。

核心链路是：原始精选图 → 修复候选图 → 维度级评分变化 → side-by-side 视觉对比 → repair targets 是否解决 → Final JSON 输出可审计差异。

专业设计师不应该只看到一个 score delta。他们需要知道构图、主体一致性、风格一致性、技术质量等维度分别发生了什么变化，并能在画布内直接放大对比原图和修复图。

## 已完成内容

- 后端 `repair_context` 从总分 delta 扩展为维度级 repair review：
  - `source_image_asset_id`
  - `source_image_url`
  - `source_image_media_type`
  - `baseline_dimensions`
  - `baseline_repair_targets`
  - 每个候选图的 `dimension_deltas`
  - 每个候选图的 `resolved_targets`
- 修复批次创建后立即用完整批次列表回填 repair context：
  - 避免刚创建的修复批次缺失 baseline candidate 信息。
  - 避免维度 delta 只能在下一次列表刷新后才完整。
- Final JSON 的 `production_lineage.repair_versions` 输出 Phase 7 差异信息：
  - 源精选图 asset id / url / media type。
  - baseline dimensions。
  - baseline repair targets。
  - 每个修复候选图的 dimension deltas 和 resolved targets。
- 前端 Image Batch Studio 显示维度级 delta：
  - 每张修复候选图在卡片内显示最多 4 个维度变化。
  - delta 上升/下降继续使用不同颜色提示。
- 前端新增原图 / 修复图 side-by-side 对比入口：
  - repair candidate 卡片增加对比按钮。
  - 对比弹窗展示 Original 和 Repair 两列。
  - 展示总分变化、各维度 baseline → current → delta。
  - 展示已解决的 repair targets。
- 对比弹窗的原图显示不只依赖当前资产 map：
  - 优先使用 `assetById`。
  - 如果资产列表短暂缺失，使用后端 `repair_context` 携带的源图 url/media type 构造回退预览。

## 方向复盘

方向是正确的。

Phase 7 继续沿着“专业设计师判断链路”推进，而不是增加表层按钮。修复版本现在不只是一个新的图片批次，而是能表达：它基于哪张原图、针对哪些问题、哪些维度改善了、哪些 repair targets 被解决，以及这些信息如何进入最终交付 JSON。

side-by-side 对比也把修复从列表浏览提升到了设计审阅动作。设计师可以在同一个画布工作台中做原图和修复图的决策，不需要跳出到单独页面或靠记忆判断。

## 仍未达到工业级的部分

- `resolved_targets` 现在是基于 repair target 文本是否仍出现在新一轮 evaluation 中的启发式判断，还不是 LMM 自然语言判定。
- side-by-side 目前是整图对比，还没有局部放大镜、同步缩放、差异热区或局部 crop 对比。
- 维度 delta 依赖候选图 evaluation metadata，如果原始精选图没有完整维度评分，则只能显示总分变化。
- 还没有“继续修复这个维度”的一键动作。
- 还没有版本树视图，设计师仍需要在修复批次卡片里查看版本关系。

## 是否继续按当前路线推进

继续。

下一阶段应进入 Phase 8：Targeted Dimension Repair & Version Tree。

阶段目标：让设计师能从某个低分维度直接发起下一轮定向修复，并在画布里看到修复版本树，而不是只在批次列表中查看平铺版本。

建议下一阶段重点：

1. 在维度 delta 和对比弹窗中增加“继续修复此维度”动作。
2. 根据选中维度生成更聚焦的 repair Prompt Program。
3. 增加修复版本树或版本链路视图。
4. 输出 Final JSON 的 repair iteration lineage。
5. 为删除/归档整个修复分支提供显式安全动作。

## 本阶段静态检查

已使用 code-reviewer 做 Phase 7 静态审查。

首次审查发现并修复：

- `_repair_version_lineage` 缺失 early return 且缩进错误，会导致后端模块无法导入。
- side-by-side 对比原图只依赖 `assetById`，资产 map 短暂缺失时会丢失原图。
- `_repair_version_lineage` fallback 只传当前 batch，无法从历史 batch 找到 baseline candidate。

修复后复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。
