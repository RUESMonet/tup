# Phase 13 Review: Pinned Production Path & Subtree Branch Operations

## 阶段目标

第十三阶段目标是在 Phase 12 的 active production path 基础上加入设计师显式主线决策，并把 branch operation 从单节点扩展到受控子树级操作。

Phase 12 已经提供 branch audit trail、分支自动布局和 Final JSON active production path。Phase 13 继续解决专业设计师真正需要的生产治理问题：哪条链路是人工确认的主生产路径、归档/恢复能否作用于子树、操作原因是否能被审计、以及 branch governance 是否能抵御客户端绕过。

核心链路是：server-managed repair version materialization → branch archive / restore subtree → designer-pinned production path → governed production input validation → Final JSON pinned lineage。

## 已完成内容

- Repair version 物化改为专用后端接口：
  - 新增 `POST /api/canvases/{canvas_id}/repair-versions/materialize`。
  - Generic node create 禁止创建 `repair_version`。
  - 前端“版本图谱”改为调用专用 materialize 接口，不再用通用 node/edge API 直接创建 repair governance 节点。
- Repair version 物化进入 repository 单事务：
  - 同一个 batch 在事务内只会复用或创建一个 repair version 节点。
  - 每次物化都会补齐 server-managed `repair_version_source` 和 `repair_version_child` 边。
  - 支持子节点先物化、父节点后物化时回填缺失 parent-child edge。
- Branch status operation 支持子树级 archive / restore：
  - `CanvasRepairVersionStatusRequest` 增加 `include_descendants`。
  - UI 在 Inspector 和 Repair Version Tree 中增加“归档子树 / 恢复子树”。
  - 子树遍历同时基于 `repair_parent_batch_id` 和 server-managed child edge，并有 visited 保护。
- Branch audit trail 支持 `reason`：
  - archive / restore / pin / unpin 都可写入 reason。
  - 审计记录仍保留最近 12 条，避免 payload 无限增长。
  - 校验允许可选 reason，但继续约束字段集合、operation、status 和时间字段。
- Designer-pinned production path：
  - 新增 `POST /api/canvases/{canvas_id}/repair-versions/{node_id}/pin`。
  - repair version payload 增加 `is_primary_path`。
  - pin 新主线时会自动 unpin 旧主线。
  - archived repair version 无法被 pin。
  - pin 前要求整条 ancestor path 都是 active。
- Final JSON production lineage 增加 pinned path 表达：
  - 输出 `pinned_production_path`。
  - `active_production_path` 优先采用合法 designer-pinned path。
  - 如果 pinned path 不合法或不存在，则 fallback 到 auto-score active path。
  - path payload 增加 `selection_strategy`，区分 `designer_pinned` 和 `auto_score`。
- 前端 Repair Version Tree 和 Inspector 增加主线表达：
  - 显示 primary count。
  - primary repair version 有独立视觉样式。
  - active repair version 可点击“主线”。
  - Final JSON Preview 显示 `Pinned` / `Auto` active path 来源。
- 生产输入治理收紧：
  - Generic node create 禁止创建 server-managed production media nodes：`selected_image`、`edited_image`、`generated_image`、`generated_video`、`repair_version`。
  - Generic node patch 禁止修改这些 server-managed media node 的 payload。
  - Generic edge create 禁止创建 `repair_version_source` 和 `repair_version_child`。
  - Archived repair branch 及其 governed downstream nodes 不能作为 compile / image generation / image batch / image edit / video / series / final-submit 输入。
  - Image edit 和 video 的 asset 输入必须绑定到已选择且未归档治理的 server-managed canvas media node。
  - Direct video raw asset 模式要求 selected source nodes，避免空节点绕过。
- Repair workflow 信任边界收紧：
  - Repair protection 不再信任客户端自建 `evaluated_by` / `repair_prompt` edge。
  - 后端 repair batch 校验 prompt / evaluation / selected_image 的 payload 绑定关系。
  - 前端 source graph 不再用客户端 repair edges 推导 repair source image，改用 repair prompt / evaluation payload 和 server-managed repair_version_source。

## 方向复盘

方向是正确的。

Phase 13 让平台从“能展示分支”进一步进入“能治理生产主线”。专业设计师不仅需要系统自动推荐最高分链路，也需要在真实项目中人工指定主线，因为主线选择往往受客户偏好、品牌一致性、风险规避、交付策略影响，不一定等于最高分。

本阶段最重要的收获不是 UI 增加几个按钮，而是把 branch governance 的信任边界从客户端显式迁移到后端 server-managed 操作：repair version、production media node、branch edge、asset binding、archive/pin status 都不能再靠客户端随意 payload/edge 声明。这是工业级工作台必须具备的底层约束。

## 本阶段修正的关键问题

静态审查多轮发现并修复了以下问题：

1. Generic node create 可伪造 `repair_version` 和 governance payload。
   - 已修复：repair_version 改为专用 materialize endpoint；generic create 禁止 repair_version。
2. Archived repair branch 可被继续作为 production input。
   - 已修复：增加 archived governed node 检测，覆盖 repair version、batch 关联节点和 downstream nodes。
3. Restore 可在 archived ancestor 下创建 active descendant。
   - 已修复：restore 前校验 ancestor 必须 active。
4. Generic edge create 可伪造 `repair_version_source` / `repair_version_child`。
   - 已修复：这些边只能通过 server-managed materialization 创建。
5. Repair version materialize 非事务幂等，可能并发创建 duplicate version node。
   - 已修复：物化逻辑移入 repository `BEGIN IMMEDIATE` 事务，按 batch 复用已有节点。
6. 子节点先物化、父节点后物化会永久缺失 child edge。
   - 已修复：每次 materialize 都会 reconcile 缺失 source/child edges。
7. Asset-backed image edit / video 可通过 raw asset 绕过 archived branch governance。
   - 已修复：asset 输入必须绑定到 selected/source server-managed media node，且这些节点不能在 archived governed set 中。
8. Repair protection 仍信任客户端创建的 `evaluated_by` / `repair_prompt` 边。
   - 已修复：保护逻辑改为信任 repair_version payload 和 server-managed repair_version_source；repair batch 增加 payload 一致性校验。
9. Server-managed media node payload 可 PATCH，重新打开 asset forgery。
   - 已修复：selected/edited/generated image/video payload 全部禁止 generic PATCH。

最终复审结果：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

## 仍未达到工业级的部分

- Branch operation audit trail 仍存放在 node payload 中，还不是独立 append-only audit log 表。
- 目前 reason 是前端固定文案或 API 字段，还没有专门的 reason dialog / 操作者身份 / 批量范围展示。
- 子树 archive / restore 已有事务式 payload 更新，但还没有独立 branch operation transaction record。
- Pin 策略只允许单一 primary path，没有提供“候选主线 / 审核中主线 / 客户确认主线”等多状态。
- Archived governed node 检测已覆盖当前生产链路，但未来如果新增边类型，需要继续纳入 source graph/lineage governance。
- 没有数据库唯一索引强制 one repair_version per batch；当前依赖 `BEGIN IMMEDIATE` 事务内检查。
- 前端子树操作还没有交互式确认 dialog 和 reason 输入框。

## 是否继续按当前路线推进

继续。

下一阶段应进入 Phase 14：Dedicated Branch Operation Log & Governance Console。

阶段目标：把当前 payload 内审计提升为独立 branch operation log，并提供一个专业治理视图，让设计师/团队能按时间线查看 pin/archive/restore/subtree 操作、原因、范围和对 Final JSON active path 的影响。

建议下一阶段重点：

1. 增加独立 `branch_operations` 表，append-only 记录 operation、actor、reason、scope、affected_node_ids、created_at。
2. Branch status / pin / materialize 都写 operation log，而不只写 node payload audit trail。
3. Final JSON 输出 operation log summary，并保留 node-level compact audit trail。
4. UI 增加 Branch Governance Console，展示主线、归档子树、恢复记录和 path strategy。
5. 给 archive subtree / restore subtree / pin path 增加 reason dialog。
6. 增加 safe branch delete 的设计，但继续默认 archive-only，不做 destructive delete。
7. 为 one repair_version per batch 增加数据库级唯一约束或 repository invariant migration。

## 本阶段静态检查

已使用 code-reviewer 做多轮 Phase 13 静态审查。

发现并修复：

- Generic create 伪造 repair_version governance。
- Archived branches 可作为 production input。
- Restore 可绕过 archived ancestor。
- Generic edge 伪造 repair_version topology。
- Materialization 非事务幂等。
- Parent/child 乱序物化缺 edge。
- Asset-backed endpoints 绕过 archived governance。
- Repair protection 信任 client-created repair edges。
- Server-managed media payload 可 PATCH 伪造 asset binding。

最终复审：

- 无 CRITICAL 问题。
- 无 HIGH 问题。
- 无 MEDIUM 问题。

本阶段只运行了 Python 文件语法编译检查：`python -m py_compile src/models/canvas.py src/api/canvas_routes.py src/services/canvas_repository.py`。

未运行 pytest、npm build 或浏览器验证，因为用户已明确要求：没有明确要求时默认不做测试。
