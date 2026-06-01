import { useEffect, useRef, useState } from "react";
import { Button, Card, Empty, Input, Modal, Radio, Space, Tag } from "antd";
import { Check, Film, ImagePlus, Loader2, Maximize2, MousePointer2, Plus, RefreshCw, RotateCcw, Sparkles, UploadCloud, Video, X, ZoomIn, ZoomOut } from "lucide-react";

import { assetMentionLabel, edgePath, styleLockText, trimInspectorText, ZOOM_STEP } from "./canvasUtils";
import { FinalSubmissionPreview } from "./FinalSubmissionPreview";
import { assetKindLabel, assetLabel, isImageAsset, isVideoAsset, safeDisplayUrl } from "./mediaUrls";
import { StoryboardPromptPanel } from "./StoryboardPromptPanel";

const ACTIVE_BATCH_STATUSES = new Set(["pending", "queued", "running"]);
const REFERENCE_ROLE_LABELS = {
  product: "产品",
  style: "风格",
  character: "角色",
  composition: "构图",
  motion: "运动",
};

const PROMPT_PROGRAM_FIELDS = [
  { key: "subject_block", label: "主体" },
  { key: "scene_block", label: "场景" },
  { key: "composition_block", label: "构图" },
  { key: "lighting_block", label: "光线" },
  { key: "camera_block", label: "镜头" },
  { key: "negative_prompt", label: "负面约束" },
];

const NODE_TYPE_LABELS = {
  brief: "Brief",
  semantic_spec: "Semantic",
  prompt_program: "Prompt Program",
  storyboard: "Storyboard",
  evaluation: "Evaluation",
  scene: "Scene",
  shot: "Shot",
  final_json: "Final JSON",
  asset: "Asset",
  selected_image: "Selected Image",
  edited_image: "Edited Image",
  generated_image: "Generated Image",
  generated_video: "Generated Video",
  series_frame: "Series Frame",
  style_system: "Style System",
  repair_version: "Repair Version",
};

export function CanvasWorkspaceView({ state, actions, refs, referenceRoles }) {
  const {
    activeMentionIndex,
    activeMentionOption,
    approvingMediaNodeId,
    assetById,
    batchDialogOpen,
    batchSettings,
    branchOperationDialog,
    branchOperationPage,
    branchOperationSubmitting,
    brief,
    canvas,
    creating,
    creatingBatch,
    creatingImageEdit,
    creatingPromptProgram,
    creatingRepairBatch,
    creatingSemanticSkeleton,
    creatingVideo,
    finalError,
    finalSubmission,
    finalSubmitting,
    imageBatches,
    imageEditDialogNode,
    imageEditPrompt,
    imageEditSettings,
    loading,
    layingOutRepairGraph,
    mediaApprovalDialog,
    mediaApprovalSubmitting,
    mediaAssets,
    mentionMenu,
    optimizingPromptNodeId,
    optimizingVideoPromptNodeId,
    promptArtifacts,
    referenceInstruction,
    referenceRole,
    repairingCandidateId,
    selectedCandidateCount,
    selectedHighlightIds,
    selectedHighlightNodeCount,
    selectedHighlightSet,
    selectedImageEditSourceCount,
    selectedNode,
    selectedNodeId,
    selectedSourceNodeCount,
    seriesPlan,
    uploadingAssets,
    planningSeries,
    materializingSeries,
    materializingRepairGraph,
    unresolvedBriefMentions,
    updatingCandidateId,
    updatingPromptProgram,
    videoDialogCandidate,
    videoPrompt,
    videoPromptArtifactId,
    videoRemixDialogNode,
    videoRemixPrompt,
    view,
  } = state;
  const { assetUploadInputRef, briefTextareaRef, stageRef } = refs;
  const selectedNodeAsset = selectedNode ? nodeDisplayAsset(selectedNode, assetById) : null;
  const promptOptimizationBusy = Boolean(optimizingPromptNodeId || optimizingVideoPromptNodeId);
  const imageOptimizingSelectedNode = selectedNode ? optimizingPromptNodeId === selectedNode.id : false;
  const selectedNodeIsEditableImage = isEditableImageNode(selectedNode, selectedNodeAsset) || selectedImageEditSourceCount > 0;
  const selectedNodeIsRemixableVideo = isRemixableVideoNode(selectedNode);
  const selectedNodeIsRepairPrompt = isRepairPromptNode(selectedNode);
  const selectedNodeIsRepairVersion = selectedNode?.type === "repair_version";
  const selectedNodeIsApprovableMedia = isApprovableProductionMediaNode(selectedNode);
  return (
    <section className="creative-canvas-shell ant-creative-canvas-shell">
      <Card className="canvas-command-panel ant-canvas-panel" title="Creative Canvas" extra={<Tag color="blue">Tools</Tag>}>
        <div className="canvas-panel-heading">
          <span>Creative Canvas</span>
          <strong>从简报、资产和生成结果构建创作图谱</strong>
        </div>
        <div className="canvas-brief-editor">
          <Input.TextArea ref={briefTextareaRef} value={brief} onChange={actions.handleBriefChange} onKeyDown={actions.handleBriefKeyDown} onKeyUp={actions.handleBriefCursor} onClick={actions.handleBriefCursor} onBlur={actions.closeMentionMenu} role="combobox" aria-autocomplete="list" aria-expanded={Boolean(mentionMenu)} aria-controls={mentionMenu ? "canvas-mention-listbox" : undefined} aria-activedescendant={mentionMenu ? `canvas-mention-option-${activeMentionIndex}` : undefined} aria-haspopup="listbox" aria-label="创意简报，输入 @ 可引用文件；可用上下箭头选择建议，Enter 或 Tab 插入" aria-describedby={mentionMenu ? "canvas-mention-status" : undefined} placeholder="输入专业创意简报：主体、场景、镜头、光线、材质、文字和限制条件… 输入 @ 可引用文件" autoSize={{ minRows: 7, maxRows: 12 }} />
          {mentionMenu ? <MentionMenu menu={mentionMenu} activeIndex={activeMentionIndex} onSelect={actions.selectMentionOption} disabled={creating || loading || uploadingAssets} /> : null}
          {mentionMenu ? <small id="canvas-mention-status" className="canvas-mention-status" role="status" aria-live="polite">当前 @文件建议：@{activeMentionOption?.mentionLabel}，{activeMentionIndex + 1} / {mentionMenu.options.length}。按 Enter 或 Tab 插入。</small> : null}
        </div>
        {unresolvedBriefMentions.length ? <div className="canvas-mention-warning">未解析 @文件：{unresolvedBriefMentions.map((label) => `@${label}`).join("、")}。请选择建议或添加对应资产节点。</div> : null}
        <Space direction="vertical" className="canvas-action-stack" size={8}>
          <Button type="primary" block onClick={actions.addBriefNode} disabled={!brief.trim() || loading || creating} loading={creating} icon={creating ? null : <Sparkles size={18} />}>
            放入画布
          </Button>
          <Button block onClick={actions.addStoryboardNode} disabled={!brief.trim() || loading || creating} loading={creating} icon={creating ? null : <Film size={18} />}>
            创建分镜节点
          </Button>
          <Button block className="canvas-semantic-action" onClick={actions.materializeSemanticSkeleton} disabled={loading || creatingSemanticSkeleton || creating || !canvas?.nodes?.some((node) => node.type === "brief")} loading={creatingSemanticSkeleton} icon={creatingSemanticSkeleton ? null : <Sparkles size={18} />}>
            初始化 LMM 语义生产骨架
          </Button>
        </Space>
        <div className="canvas-reference-strip">
          <div className="canvas-reference-heading">
            <span>@ 媒体引用</span>
            <button className="canvas-reference-upload" type="button" onClick={actions.openCanvasAssetUpload} disabled={loading || creating || uploadingAssets}>
              {uploadingAssets ? <Loader2 className="spinning" size={15} /> : <UploadCloud size={15} />}
              <small>{uploadingAssets ? "上传中" : "上传到画布"}</small>
            </button>
          </div>
          <input ref={assetUploadInputRef} type="file" accept="image/png,image/jpeg,image/webp,video/mp4,video/webm,video/quicktime" multiple hidden onChange={actions.uploadCanvasAssets} />
          <Radio.Group className="canvas-reference-role-grid ant-reference-role-grid" value={referenceRole} onChange={(event) => actions.setReferenceRole(event.target.value)} disabled={loading || creating || uploadingAssets}>
            <Space direction="vertical" size={8}>
              {referenceRoles.map((role) => (
                <Radio.Button key={role.value} value={role.value}>
                  <strong>{role.label}</strong>
                  <small>{role.help}</small>
                </Radio.Button>
              ))}
            </Space>
          </Radio.Group>
          <Input.TextArea className="canvas-reference-instruction" value={referenceInstruction} onChange={(event) => actions.setReferenceInstruction(event.target.value)} disabled={loading || creating || uploadingAssets} aria-label="媒体专业约束，可选" placeholder="可选：写给该媒体的专业约束，例如：只保留瓶身轮廓，或只参考镜头运动节奏。" autoSize={{ minRows: 3, maxRows: 6 }} />
          {mediaAssets.map((asset) => (
            <button type="button" key={asset.id} onClick={() => actions.addAssetNode(asset)} disabled={creating || loading || uploadingAssets}>
              <MediaPreview asset={asset} alt="参考媒体" compact />
              <small>{assetLabel(asset, assetKindLabel(asset))} · @{assetMentionLabel(asset)}</small>
            </button>
          ))}
          {!mediaAssets.length ? <small>生成或上传图片/视频后，可作为产品、风格、角色、构图或运动参考加入画布。</small> : null}
        </div>
      </Card>

      <Card className="canvas-stage-shell ant-canvas-stage-card" styles={{ body: { padding: 0 } }}>
        <div className="canvas-toolbar">
          <div className="canvas-toolbar-title">
            <MousePointer2 size={16} />
            <span>{canvas?.name || "Creative Canvas"}</span>
            <small>{canvas?.nodes?.length || 0} nodes · {canvas?.edges?.length || 0} edges · {selectedHighlightNodeCount || 0} selected graph</small>
          </div>
          <div className="canvas-zoom-controls">
            <button type="button" onClick={actions.fitCanvas} disabled={!canvas?.nodes?.length} aria-label="适配画布"><Maximize2 size={15} /></button>
            <button type="button" onClick={actions.resetView} aria-label="重置视图"><RotateCcw size={15} /></button>
            <button type="button" onClick={() => actions.zoomBy(-ZOOM_STEP)} aria-label="缩小"><ZoomOut size={15} /></button>
            <span>{Math.round(view.scale * 100)}%</span>
            <button type="button" onClick={() => actions.zoomBy(ZOOM_STEP)} aria-label="放大"><ZoomIn size={15} /></button>
          </div>
        </div>
        <div ref={stageRef} className="canvas-stage" onPointerDown={actions.startPan} onPointerMove={actions.movePointer} onPointerUp={actions.endPointer} onPointerCancel={actions.endPointer}>
          <div className="canvas-grid-plane" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}>
            <CanvasEdgeLayer edges={canvas?.edges || []} nodes={canvas?.nodes || []} selectedNodeId={selectedNodeId} selectedSourceIds={selectedHighlightIds} />
            {loading ? <div className="canvas-loading"><Loader2 className="spinning" size={24} />正在同步画布</div> : null}
            {canvas?.nodes.map((node) => (
              <CanvasNodeCard key={node.id} node={node} asset={nodeDisplayAsset(node, assetById)} selected={node.id === selectedNodeId} inScope={selectedHighlightSet.has(node.id)} onSelect={() => actions.setSelectedNodeId(node.id)} onPointerDown={(event) => actions.startNodeDrag(event, node)} />
            ))}
          </div>
        </div>
        <div className="canvas-production-tray">
          <Card className="canvas-image-batch-studio production-card" size="small">
            <div className="canvas-production-heading">
              <span>Image Batch Studio</span>
              <button type="button" onClick={actions.refreshBatchesFromButton} disabled={loading || creatingBatch} aria-label="刷新图片批次"><RefreshCw size={15} /></button>
            </div>
            <p>核心路径是文字生成多张候选图：先大量探索，再精选图片进入画布，最后从精选图延展视频。</p>
            <div className="canvas-series-actions">
              <button className="primary-image-action compact" type="button" onClick={actions.openImageBatchDialog} disabled={loading || creatingBatch || !selectedSourceNodeCount}>
                {creatingBatch ? <Loader2 className="spinning" size={16} /> : <ImagePlus size={16} />}
                <span>生成候选图</span>
              </button>
              <button className="secondary-image-action" type="button" onClick={actions.refreshBatchesFromButton} disabled={loading || creatingBatch}>
                <RefreshCw size={16} />
                <span>同步结果</span>
              </button>
              <button className="secondary-image-action" type="button" onClick={actions.materializeRepairVersionGraph} disabled={loading || materializingRepairGraph || !imageBatches.some((batch) => batch.repair_context?.is_repair_version)}>
                {materializingRepairGraph ? <Loader2 className="spinning" size={16} /> : <Plus size={16} />}
                <span>版本图谱</span>
              </button>
              <button className="secondary-image-action" type="button" onClick={actions.layoutRepairVersionGraph} disabled={loading || layingOutRepairGraph || !canvas?.nodes?.some((node) => node.type === "repair_version")}>
                {layingOutRepairGraph ? <Loader2 className="spinning" size={16} /> : <Maximize2 size={16} />}
                <span>分支布局</span>
              </button>
            </div>
            <ImageBatchTray canvasId={canvas?.id || ""} batches={imageBatches} canvasNodes={canvas?.nodes || []} repairVersionNodes={canvas?.nodes?.filter((node) => node.type === "repair_version") || []} branchOperationPage={branchOperationPage} branchOperations={branchOperationPage?.operations || canvas?.branch_operations || []} assetById={assetById} updatingCandidateId={updatingCandidateId} repairingCandidateId={repairingCandidateId} onSelectCandidate={actions.updateCandidateStatus} onRejectCandidate={actions.updateCandidateStatus} onOpenVideo={actions.openVideoDialog} onCreateRepairBranch={actions.createRepairBranchFromCandidate} onFocusRepairVersion={actions.focusRepairVersionNode} onOpenBranchOperation={actions.openBranchOperationDialog} onLoadBranchOperations={actions.loadBranchOperations} />
          </Card>
          <Card className="canvas-series-director production-card" size="small">
            <span>Series Director</span>
            <p>基于当前选中图谱规划连续分镜，并把分镜节点回写到画布。</p>
            <div className="canvas-series-actions">
              <button className="secondary-image-action" type="button" onClick={actions.planSeries} disabled={loading || planningSeries || materializingSeries || !selectedSourceNodeCount}>
                {planningSeries ? <Loader2 className="spinning" size={16} /> : <Film size={16} />}
                <span>规划系列</span>
              </button>
              <button className="primary-image-action compact" type="button" onClick={actions.materializeSeriesFrames} disabled={!seriesPlan?.frames?.length || planningSeries || materializingSeries}>
                {materializingSeries ? <Loader2 className="spinning" size={16} /> : <Plus size={16} />}
                <span>生成分镜节点</span>
              </button>
            </div>
            {seriesPlan ? <SeriesPlanPreview plan={seriesPlan} /> : <small>{selectedSourceNodeCount ? `将基于当前选中图谱的 ${selectedSourceNodeCount} 个节点规划系列。` : "先选择一个简报、风格或参考资产节点，再让系列导演拆解镜头节奏。"}</small>}
          </Card>
          <Card className="canvas-final-submit production-card" size="small">
            <span>Final JSON</span>
            <p>编译可审计 Creative Graph、Prompt Spec、@文件引用、候选图选择、视频产物和生成参数。</p>
            <div className="canvas-series-actions">
              <button className="secondary-image-action" type="button" onClick={() => actions.submitFinalJson(false)} disabled={loading || finalSubmitting || !selectedSourceNodeCount}>
                {finalSubmitting ? <Loader2 className="spinning" size={16} /> : <Sparkles size={16} />}
                <span>预览/提交 JSON</span>
              </button>
              <button className="primary-image-action compact" type="button" onClick={() => actions.submitFinalJson(true)} disabled={loading || finalSubmitting || !selectedSourceNodeCount}>
                {finalSubmitting ? <Loader2 className="spinning" size={16} /> : <Plus size={16} />}
                <span>提交并生成</span>
              </button>
            </div>
            {finalError ? <small className="canvas-final-error">{finalError}</small> : null}
            {finalSubmission ? <FinalSubmissionPreview submission={finalSubmission} /> : <small>{selectedSourceNodeCount ? `将提交当前选中图谱的 ${selectedSourceNodeCount} 个源节点，包含 ${selectedCandidateCount} 张精选图。` : "先选择一个简报或资产节点，再提交最终 JSON。"}</small>}
          </Card>
        </div>
      </Card>

      <Card className="canvas-inspector-panel ant-canvas-panel" title="Inspector">
        {selectedNode ? <NodeInspector node={selectedNode} edges={canvas?.edges || []} assetById={assetById} updatingPromptProgram={updatingPromptProgram} onSavePromptProgram={actions.updatePromptProgramNode} /> : <Empty description="选择节点查看 Prompt、参考资产和后续编译信息。" />}
        <StoryboardPromptPanel
          selectedNode={selectedNode}
          artifacts={promptArtifacts || []}
          optimizingNodeId={optimizingPromptNodeId}
          optimizingVideoNodeId={optimizingVideoPromptNodeId}
          onOptimize={actions.optimizeStoryboardImagePrompt}
          onOptimizeVideo={actions.optimizeStoryboardVideoPrompt}
        />
        <div className="canvas-inspector-actions">
          {selectedNodeIsEditableImage ? (
            <button className="primary-image-action compact" type="button" onClick={() => actions.openImageEditDialog(selectedNode)} disabled={loading || creatingImageEdit}>
              {creatingImageEdit ? <Loader2 className="spinning" size={16} /> : <Sparkles size={16} />}
              <span>{selectedImageEditSourceCount > 1 ? `多图编辑 · ${selectedImageEditSourceCount}` : "编辑图片"}</span>
            </button>
          ) : null}
          {selectedNodeIsRemixableVideo ? (
            <button className="secondary-image-action" type="button" onClick={() => actions.openVideoRemixDialog(selectedNode)} disabled={loading || creatingVideo}>
              {creatingVideo ? <Loader2 className="spinning" size={16} /> : <Video size={16} />}
              <span>调整视频 / 重新生成</span>
            </button>
          ) : null}
          {selectedNodeIsApprovableMedia ? (
            <button className={selectedNode.payload?.approval_status === "approved" ? "secondary-image-action" : "primary-image-action compact"} type="button" onClick={() => actions.openMediaApprovalDialog(selectedNode, selectedNode.payload?.approval_status !== "approved")} disabled={loading || approvingMediaNodeId === selectedNode.id}>
              {approvingMediaNodeId === selectedNode.id ? <Loader2 className="spinning" size={16} /> : <Check size={16} />}
              <span>{selectedNode.payload?.approval_status === "approved" ? "撤销生产批准" : "批准为生产媒体"}</span>
            </button>
          ) : null}
          {selectedNodeIsRepairPrompt ? (
            <button className="primary-image-action compact" type="button" onClick={() => actions.createRepairImageBatchFromNode(selectedNode)} disabled={loading || creatingRepairBatch || !selectedSourceNodeCount}>
              {creatingRepairBatch ? <Loader2 className="spinning" size={16} /> : <ImagePlus size={16} />}
              <span>生成修复候选图</span>
            </button>
          ) : null}
          {selectedNodeIsRepairVersion && selectedNode.payload?.status !== "archived" ? (
            <>
              <button className="primary-image-action compact" type="button" onClick={() => actions.openBranchOperationDialog(selectedNode, "pin")} disabled={loading || selectedNode.payload?.is_primary_path}>
                <Check size={16} />
                <span>{selectedNode.payload?.is_primary_path ? "已是主生产路径" : "设为主生产路径"}</span>
              </button>
              {selectedNode.payload?.is_primary_path ? (
                <button className="secondary-image-action" type="button" onClick={() => actions.openBranchOperationDialog(selectedNode, "unpin")} disabled={loading}>
                  <X size={16} />
                  <span>取消主生产路径</span>
                </button>
              ) : null}
              <button className="secondary-image-action" type="button" onClick={() => actions.openBranchOperationDialog(selectedNode, "archive")} disabled={loading}>
                <X size={16} />
                <span>归档修复分支</span>
              </button>
              <button className="secondary-image-action" type="button" onClick={() => actions.openBranchOperationDialog(selectedNode, "archive", { includeDescendants: true })} disabled={loading}>
                <X size={16} />
                <span>归档子树</span>
              </button>
            </>
          ) : null}
          {selectedNodeIsRepairVersion && selectedNode.payload?.status === "archived" ? (
            <>
              <button className="primary-image-action compact" type="button" onClick={() => actions.openBranchOperationDialog(selectedNode, "restore")} disabled={loading}>
                <RefreshCw size={16} />
                <span>恢复修复分支</span>
              </button>
              <button className="secondary-image-action" type="button" onClick={() => actions.openBranchOperationDialog(selectedNode, "restore", { includeDescendants: true })} disabled={loading}>
                <RefreshCw size={16} />
                <span>恢复子树</span>
              </button>
            </>
          ) : null}
          {selectedNode && ["brief", "storyboard", "series_frame", "shot", "prompt_program", "semantic_spec"].includes(selectedNode.type) ? (
            <button className="secondary-image-action" type="button" onClick={() => actions.optimizeStoryboardImagePrompt(selectedNode)} disabled={loading || promptOptimizationBusy}>
              {imageOptimizingSelectedNode ? <Loader2 className="spinning" size={16} /> : <Sparkles size={16} />}
              <span>优化图像 Prompt</span>
            </button>
          ) : null}
          <button className="secondary-image-action" type="button" onClick={actions.createPromptProgramFromSelection} disabled={loading || creatingPromptProgram || !selectedSourceNodeCount}>
            {creatingPromptProgram ? <Loader2 className="spinning" size={16} /> : <Sparkles size={16} />}
            <span>生成 Prompt Program</span>
          </button>
          <button className="primary-image-action compact" type="button" onClick={actions.openImageBatchDialog} disabled={loading || creatingBatch || !selectedSourceNodeCount}>
            {creatingBatch ? <Loader2 className="spinning" size={16} /> : <ImagePlus size={16} />}
            <span>基于当前图谱出图</span>
          </button>
          <small>{selectedSourceNodeCount ? `当前图谱包含 ${selectedSourceNodeCount} 个源节点` : "选择节点后可生成候选图。"}</small>
        </div>
      </Card>

      {batchDialogOpen ? <ImageBatchDialog settings={batchSettings} selectedCount={selectedSourceNodeCount} creating={creatingBatch} onChange={actions.setBatchSettings} onClose={actions.closeImageBatchDialog} onSubmit={actions.createImageBatchFromSelection} /> : null}
      {branchOperationDialog ? <BranchOperationDialog operation={branchOperationDialog} busy={loading || branchOperationSubmitting} onReasonChange={actions.setBranchOperationReason} onClose={actions.closeBranchOperationDialog} onSubmit={actions.submitBranchOperationDialog} /> : null}
      {mediaApprovalDialog ? <MediaApprovalDialog approval={mediaApprovalDialog} busy={loading || mediaApprovalSubmitting} onReasonChange={actions.setMediaApprovalReason} onClose={actions.closeMediaApprovalDialog} onSubmit={actions.submitMediaApprovalDialog} /> : null}
      {imageEditDialogNode ? <ImageEditDialog node={imageEditDialogNode.node || imageEditDialogNode} sources={imageEditDialogNode.sources || []} asset={(imageEditDialogNode.sources || [])[0]?.asset || nodeDisplayAsset(imageEditDialogNode.node || imageEditDialogNode, assetById)} maskAssets={mediaAssets.filter(isImageAsset)} prompt={imageEditPrompt} settings={imageEditSettings} creating={creatingImageEdit} onPromptChange={actions.setImageEditPrompt} onSettingsChange={actions.setImageEditSettings} onClose={actions.closeImageEditDialog} onSubmit={actions.createImageEditFromNode} /> : null}
      {videoDialogCandidate ? (
        <VideoFromCandidateDialog
          candidate={videoDialogCandidate}
          prompt={videoPrompt}
          promptArtifactId={videoPromptArtifactId}
          optimizing={Boolean(optimizingVideoPromptNodeId)}
          creating={creatingVideo}
          onOptimizePrompt={() => {
            const targetNode = videoDialogCandidate.node_id ? canvas?.nodes?.find((node) => node.id === videoDialogCandidate.node_id) : selectedNode;
            actions.optimizeStoryboardVideoPrompt(targetNode || selectedNode, videoDialogCandidate);
          }}
          onPromptChange={actions.setVideoPrompt}
          onClose={actions.closeVideoDialog}
          onSubmit={actions.createVideoFromCandidate}
        />
      ) : null}
      {videoRemixDialogNode ? <VideoRemixDialog node={videoRemixDialogNode} asset={nodeDisplayAsset(videoRemixDialogNode, assetById)} prompt={videoRemixPrompt} creating={creatingVideo} onPromptChange={actions.setVideoRemixPrompt} onClose={actions.closeVideoRemixDialog} onSubmit={actions.createVideoRemixFromNode} /> : null}
    </section>
  );
}

export function MentionMenu({ menu, activeIndex, onSelect, disabled }) {
  return (
    <div id="canvas-mention-listbox" className="canvas-mention-menu" role="listbox" aria-label="@文件建议，点击选择或在输入框内用上下箭头选择后按 Enter 插入">
      {menu.options.map((option, index) => (
        <button id={`canvas-mention-option-${index}`} className={index === activeIndex ? "active" : ""} type="button" role="option" aria-selected={index === activeIndex} key={`${option.asset.id}-${option.mentionLabel}`} onMouseDown={(event) => event.preventDefault()} onClick={() => onSelect(option)} disabled={disabled}>
          <MediaPreview asset={option.asset} alt="@文件" compact />
          <span>
            <strong>@{option.mentionLabel}</strong>
            <small>{assetLabel(option.asset, assetKindLabel(option.asset))}{option.existingNodeId ? " · 已在画布" : " · 添加为媒体引用"}</small>
          </span>
        </button>
      ))}
    </div>
  );
}

export function ImageBatchTray({ canvasId = "", batches, canvasNodes = [], repairVersionNodes = [], branchOperations = [], branchOperationPage = null, assetById, updatingCandidateId, repairingCandidateId, onSelectCandidate, onRejectCandidate, onOpenVideo, onCreateRepairBranch, onFocusRepairVersion, onOpenBranchOperation, onLoadBranchOperations }) {
  const [comparison, setComparison] = useState(null);
  if (!batches.length) {
    return <small>还没有画布内图片批次。选择简报或参考节点后生成 4 张候选图，再把精选图放回画布。</small>;
  }
  return (
    <>
    <RepairVersionTree canvasId={canvasId} batches={batches} canvasNodes={canvasNodes} repairVersionNodes={repairVersionNodes} branchOperations={branchOperations} branchOperationPage={branchOperationPage} onFocusRepairVersion={onFocusRepairVersion} onOpenBranchOperation={onOpenBranchOperation} onLoadBranchOperations={onLoadBranchOperations} />
    <div className="canvas-image-batch-tray">
      {batches.slice(0, 6).map((batch) => {
        const repairContext = repairBatchContext(batch);
        return (
          <article className={["canvas-image-batch-card", repairContext ? "repair-version" : ""].filter(Boolean).join(" ")} key={batch.id}>
            <div className="canvas-batch-card-header">
              <span>{repairContext ? "repair" : batch.status}</span>
              <strong>{batch.candidates?.length || 0} / {batch.params?.n || "?"} candidates</strong>
            </div>
            {repairContext ? (
              <div className="canvas-repair-version-meta">
                <span>Repair Version</span>
                <strong>{repairContext.repairPromptTitle}</strong>
                <small>基准分：{repairContext.baselineScore == null ? "未评分" : formatScore(repairContext.baselineScore)} · 来自 {repairContext.sourceImageTitle}</small>
              </div>
            ) : null}
            <p>{trimInspectorText(batch.prompt || "")}</p>
            <div className="canvas-candidate-grid">
              {(batch.candidates || []).map((candidate) => (
                <CandidateCard
                  key={candidate.id}
                  batch={batch}
                  candidate={candidate}
                  asset={candidateAsset(candidate, assetById)}
                  repairContext={repairContext}
                  updating={updatingCandidateId === candidate.id}
                  repairing={repairingCandidateId === candidate.id}
                  repairProtected={candidate.repair_protected}
                  onOpenCompare={() => setComparison(repairComparisonPayload(candidate, candidateAsset(candidate, assetById), repairContext, assetById, (dimension) => onCreateRepairBranch(batch, candidate, { dimension })))}
                  onCreateTargetedRepair={(dimension) => onCreateRepairBranch(batch, candidate, { dimension })}
                  onSelect={onSelectCandidate}
                  onReject={onRejectCandidate}
                  onOpenVideo={onOpenVideo}
                  onCreateRepairBranch={onCreateRepairBranch}
                />
              ))}
            {ACTIVE_BATCH_STATUSES.has(batch.status) && !(batch.candidates || []).length ? <div className="canvas-candidate-skeleton"><Loader2 className="spinning" size={18} />生成候选图中</div> : null}
          </div>
        </article>
        );
      })}
    </div>
    {comparison ? <RepairComparisonDialog comparison={comparison} onClose={() => setComparison(null)} onCreateTargetedRepair={comparison.onCreateTargetedRepair} /> : null}
    </>
  );
}

function RepairVersionTree({ canvasId, batches, canvasNodes, repairVersionNodes, branchOperations, branchOperationPage, onFocusRepairVersion, onOpenBranchOperation, onLoadBranchOperations }) {
  const versionNodeByBatchId = new Map(repairVersionNodes.filter((node) => node.payload?.batch_id).map((node) => [node.payload.batch_id, node]));
  const repairVersions = batches
    .map((batch) => ({ batch, context: repairBatchContext(batch), node: versionNodeByBatchId.get(batch.id) || null }))
    .filter((item) => item.context)
    .sort((left, right) => repairVersionIteration(left.context) - repairVersionIteration(right.context))
    .slice(-8);
  if (!repairVersions.length) {
    return <BranchGovernanceConsole canvasId={canvasId} operations={branchOperations} page={branchOperationPage} canvasNodes={canvasNodes} repairVersionNodes={repairVersionNodes} onFocusRepairVersion={onFocusRepairVersion} onLoadOperations={onLoadBranchOperations} />;
  }
  const labelsByBatchId = new Map(repairVersions.map(({ batch, context }) => [batch.id, context.repairFocus?.label || context.repairPromptTitle]));
  const activeCount = repairVersions.filter((item) => repairVersionStatus(item) === "active").length;
  const archivedCount = repairVersions.filter((item) => repairVersionStatus(item) === "archived").length;
  const primaryCount = repairVersions.filter((item) => item.node?.payload?.is_primary_path).length;
  const unmaterializedCount = repairVersions.length - activeCount - archivedCount;
  return (
    <div className="canvas-repair-version-tree" aria-label="修复版本链路">
      <span>Repair Version Tree · {activeCount} active / {archivedCount} archived / {unmaterializedCount} unmaterialized / {primaryCount} primary</span>
      {repairVersions.map((item) => {
        const { batch, context, node } = item;
        const bestDelta = bestRepairDelta(context);
        const focus = context.repairFocus?.label || context.repairFocus?.key || "整体修复";
        const iteration = repairVersionIteration(context);
        const parentBatchId = context.repairFocus?.parent_batch_id || "";
        const status = repairVersionStatus(item);
        const isPrimary = Boolean(node?.payload?.is_primary_path);
        const statusLabel = isPrimary ? "Primary" : status === "archived" ? "Archived" : status === "active" ? "Active" : "Unmaterialized";
        return (
          <article className={[status === "archived" ? "archived" : "", isPrimary ? "primary" : ""].filter(Boolean).join(" ")} key={batch.id}>
            <div>
              <strong>Iteration {iteration || "?"} · {focus}</strong>
              {node ? (
                <div className="canvas-repair-version-actions">
                  <button type="button" onClick={() => onFocusRepairVersion?.(node)}>定位</button>
                  {status === "active" && !isPrimary ? <button type="button" onClick={() => onOpenBranchOperation?.(node, "pin")}>主线</button> : null}
                  {status === "active" && isPrimary ? <button type="button" onClick={() => onOpenBranchOperation?.(node, "unpin")}>取消主线</button> : null}
                  {status === "archived" ? <button type="button" onClick={() => onOpenBranchOperation?.(node, "restore")}>恢复</button> : <button type="button" onClick={() => onOpenBranchOperation?.(node, "archive")}>归档</button>}
                  {status === "archived" ? <button type="button" onClick={() => onOpenBranchOperation?.(node, "restore", { includeDescendants: true })}>恢复子树</button> : <button type="button" onClick={() => onOpenBranchOperation?.(node, "archive", { includeDescendants: true })}>归档子树</button>}
                </div>
              ) : null}
            </div>
            <small>{statusLabel} · {parentBatchId ? `来自 ${labelsByBatchId.get(parentBatchId) || parentBatchId}` : `${context.sourceImageTitle} → ${context.repairPromptTitle}`}</small>
            <small className={bestDelta == null ? "" : bestDelta >= 0 ? "score-up" : "score-down"}>最佳变化 {formatScoreDelta(bestDelta)} · {batch.candidates?.length || 0} 张候选{node ? " · 已在画布" : " · 未物化"}</small>
          </article>
        );
      })}
      <RepairBranchTrend versions={repairVersions} />
      <BranchGovernanceConsole canvasId={canvasId} operations={branchOperations} page={branchOperationPage} canvasNodes={canvasNodes} repairVersionNodes={repairVersionNodes} onFocusRepairVersion={onFocusRepairVersion} onLoadOperations={onLoadBranchOperations} />
    </div>
  );
}

function BranchGovernanceConsole({ canvasId, operations, page, canvasNodes = [], repairVersionNodes = [], onFocusRepairVersion, onLoadOperations }) {
  const [operationFilter, setOperationFilter] = useState("all");
  const [scopeFilter, setScopeFilter] = useState("all");
  const [detailOperationId, setDetailOperationId] = useState("");
  const offset = page?.offset || 0;
  const limit = page?.limit || 40;
  useEffect(() => {
    if (canvasId) {
      onLoadOperations?.({ operation: operationFilter, scope: scopeFilter, limit, offset: 0 });
    }
  }, [canvasId, operationFilter, scopeFilter]);
  const governanceNodes = canvasNodes.length ? canvasNodes : repairVersionNodes;
  const labelsByNodeId = new Map(governanceNodes.map((node) => [node.id, node.payload?.repair_focus_label || node.title || node.id.slice(0, 8)]));
  const nodesById = new Map(governanceNodes.map((node) => [node.id, node]));
  const sortedOperations = [...(operations || [])].sort((left, right) => operationTimestamp(right.created_at) - operationTimestamp(left.created_at));
  const filtered = sortedOperations.filter((operation) => (operationFilter === "all" || operation.operation === operationFilter) && (scopeFilter === "all" || operation.scope === scopeFilter));
  const summary = page?.summary || {};
  const counts = summary.operation_counts || governanceOperationCounts(sortedOperations);
  const scopes = summary.scope_counts || {};
  const detailOperation = sortedOperations.find((operation) => operation.id === detailOperationId) || null;
  const total = page?.total || sortedOperations.length;
  const rangeStart = total ? offset + 1 : 0;
  const rangeEnd = Math.min(offset + limit, total);
  if (!sortedOperations.length && operationFilter === "all" && scopeFilter === "all") {
    return <small>治理控制台会记录 materialize / pin / archive / restore / approve / revoke 操作、范围、原因、actor 和对主生产路径及生产媒体审批的影响。</small>;
  }
  return (
    <div className="canvas-branch-governance-console" aria-label="Branch governance console">
      <div className="canvas-governance-console-heading">
        <span>Branch Governance Console</span>
        <strong>{page?.loading ? "Loading" : `${total} ops`} · 全局 {counts.pin || 0} pins · {counts.unpin || 0} unpins · {counts.archive || 0} archives · {counts.approve || 0} approvals · {counts.select || 0} selects</strong>
      </div>
      <div className="canvas-governance-filter-row">
        <select value={operationFilter} onChange={(event) => setOperationFilter(event.target.value)} aria-label="筛选操作类型">
          <option value="all">全部操作</option>
          <option value="materialize">物化</option>
          <option value="pin">主线</option>
          <option value="unpin">取消主线</option>
          <option value="archive">归档</option>
          <option value="restore">恢复</option>
          <option value="approve">生产批准</option>
          <option value="revoke">撤销批准</option>
          <option value="select">精选图片</option>
          <option value="reject">拒绝图片</option>
          <option value="candidate">候选状态</option>
        </select>
        <select value={scopeFilter} onChange={(event) => setScopeFilter(event.target.value)} aria-label="筛选操作范围">
          <option value="all">全部范围</option>
          <option value="single">单节点</option>
          <option value="subtree">子树</option>
          <option value="path">路径</option>
        </select>
      </div>
      <div className="canvas-governance-impact-grid">
        <div><span>全局最新主线</span><strong>{operationTargetLabel(summary.latest_pin, labelsByNodeId)}</strong></div>
        <div><span>最近取消主线</span><strong>{operationTargetLabel(summary.latest_unpin, labelsByNodeId)}</strong></div>
        <div><span>全局最近归档</span><strong>{operationTargetLabel(summary.latest_archive, labelsByNodeId)}</strong></div>
        <div><span>最近生产批准</span><strong>{operationTargetLabel(summary.latest_approve, labelsByNodeId)}</strong></div>
        <div><span>最近精选图片</span><strong>{operationTargetLabel(summary.latest_select, labelsByNodeId)}</strong></div>
        <div><span>最近拒绝图片</span><strong>{operationTargetLabel(summary.latest_reject, labelsByNodeId)}</strong></div>
        <div><span>最近候选状态</span><strong>{operationTargetLabel(summary.latest_candidate, labelsByNodeId)}</strong></div>
      </div>
      <div className="canvas-governance-scope-grid">
        <small>Scope: single {scopes.single || 0} · subtree {scopes.subtree || 0} · path {scopes.path || 0}</small>
      </div>
      <div className="canvas-branch-operation-log">
        {filtered.map((operation) => {
          const node = nodesById.get(operation.target_node_id);
          const label = operationTargetLabel(operation, labelsByNodeId);
          return (
            <article key={operation.id}>
              <div>
                <strong>{branchOperationLabel(operation.operation)} · {branchScopeLabel(operation.scope)}</strong>
                <small>{formatBranchOperationDate(operation.created_at)}</small>
              </div>
              <small>{label} · {operation.affected_node_ids?.length || 0} affected · {operation.actor_display || "Owner"}</small>
              {operation.reason ? <p>{trimCandidateText(operation.reason, 128)}</p> : null}
              <div className="canvas-branch-operation-actions">
                {node ? <button type="button" onClick={() => onFocusRepairVersion?.(node)}>{node.type === "repair_version" ? "定位版本" : "定位节点"}</button> : null}
                <button type="button" onClick={() => setDetailOperationId(detailOperationId === operation.id ? "" : operation.id)}>{detailOperationId === operation.id ? "收起详情" : "查看详情"}</button>
              </div>
            </article>
          );
        })}
        {!filtered.length ? <small>没有符合当前筛选的治理记录。</small> : null}
      </div>
      {detailOperation ? <BranchOperationDetail operation={detailOperation} nodesById={nodesById} labelsByNodeId={labelsByNodeId} onFocusRepairVersion={onFocusRepairVersion} /> : null}
      <div className="canvas-governance-pagination">
        <button type="button" onClick={() => onLoadOperations?.({ operation: operationFilter, scope: scopeFilter, limit, offset: Math.max(0, offset - limit) })} disabled={page?.loading || offset <= 0}>上一页</button>
        <small>{rangeStart}-{rangeEnd} / {total}</small>
        <button type="button" onClick={() => onLoadOperations?.({ operation: operationFilter, scope: scopeFilter, limit, offset: offset + limit })} disabled={page?.loading || offset + limit >= total}>下一页</button>
      </div>
    </div>
  );
}

function BranchOperationDetail({ operation, nodesById, labelsByNodeId, onFocusRepairVersion }) {
  const payloadEntries = Object.entries(operation.payload || {}).slice(0, 8);
  const affectedNodes = (operation.affected_node_ids || []).map((nodeId) => ({ id: nodeId, node: nodesById.get(nodeId), label: labelsByNodeId.get(nodeId) || nodeId.slice(0, 8) }));
  return (
    <div className="canvas-branch-operation-detail" aria-label="Branch operation detail">
      <div>
        <span>Operation Detail</span>
        <strong>{branchOperationLabel(operation.operation)} · {branchScopeLabel(operation.scope)} · {operation.actor_display || "Owner"}</strong>
      </div>
      <small>{formatBranchOperationDate(operation.created_at)} · {operation.id.slice(0, 8)}</small>
      {operation.reason ? <p>{operation.reason}</p> : null}
      {payloadEntries.length ? (
        <div className="canvas-branch-operation-payload">
          {payloadEntries.map(([key, value]) => <small key={key}>{key}: {trimCandidateText(Array.isArray(value) ? value.join(" / ") : JSON.stringify(value), 120)}</small>)}
        </div>
      ) : null}
      <div className="canvas-branch-operation-affected">
        {affectedNodes.slice(0, 12).map((item) => (
          <button key={item.id} type="button" onClick={() => item.node && onFocusRepairVersion?.(item.node)} disabled={!item.node}>{item.label}</button>
        ))}
        {!affectedNodes.length ? <small>没有记录 affected nodes。</small> : null}
      </div>
    </div>
  );
}

function RepairBranchTrend({ versions }) {
  const versionsByBatchId = new Map(versions.map((item) => [item.batch.id, item]));
  const latest = versions[versions.length - 1];
  const branchVersions = [];
  let cursor = latest;
  while (cursor) {
    branchVersions.unshift(cursor);
    const parentBatchId = cursor.context.repairFocus?.parent_batch_id;
    cursor = parentBatchId ? versionsByBatchId.get(parentBatchId) : null;
  }
  if (branchVersions.length < 2) {
    return <small>至少两个修复版本后显示分支趋势。</small>;
  }
  const first = bestRepairScore(branchVersions[0].context);
  const last = bestRepairScore(branchVersions[branchVersions.length - 1].context);
  const trend = first == null || last == null ? null : last - first;
  return (
    <div className="canvas-repair-branch-trend">
      <span>Branch Trend</span>
      <strong className={trend == null ? "" : trend >= 0 ? "score-up" : "score-down"}>{formatScoreDelta(trend)}</strong>
      <small>{branchVersions.length} 个版本 · 从 {formatScore(first)} 到 {formatScore(last)}</small>
      <div className="canvas-branch-diff-report">
        {branchVersions.map((item) => {
          const bestCandidate = bestRepairCandidateDelta(item.context);
          const score = bestRepairScore(item.context);
          const status = repairVersionStatus(item);
          return (
            <article className={status === "archived" ? "archived" : ""} key={item.batch.id}>
              <strong>V{repairVersionIteration(item.context) || "?"} · {item.context.repairFocus?.label || item.context.repairPromptTitle}</strong>
              <small>{status} · <span className={score == null ? "" : score >= Number(item.context.baselineScore || 0) ? "score-up" : "score-down"}>最佳分 {formatScore(score)} · {formatScoreDelta(bestCandidate?.score_delta)}</span></small>
              {(bestCandidate?.dimension_deltas || []).slice(0, 2).map((dimension) => (
                <small key={dimension.key || dimension.label}>{dimension.label || dimension.key}: {formatScore(dimension.baseline_score)} → {formatScore(dimension.score)} ({formatScoreDelta(dimension.delta)})</small>
              ))}
            </article>
          );
        })}
      </div>
    </div>
  );
}

function repairVersionStatus(item) {
  if (!item.node) {
    return "unmaterialized";
  }
  return item.node.payload?.status === "archived" ? "archived" : "active";
}

function repairVersionIteration(repairContext) {
  const iteration = Number(repairContext?.repairFocus?.iteration);
  return Number.isFinite(iteration) ? iteration : 0;
}

function bestRepairDelta(repairContext) {
  const bestCandidate = bestRepairCandidateDelta(repairContext);
  return bestCandidate ? numericScore(bestCandidate.score_delta) : null;
}

function bestRepairCandidateDelta(repairContext) {
  const candidates = Object.values(repairContext?.candidateDeltas || {});
  const scored = candidates.map((item) => ({ item, score: numericScore(item?.score) })).filter(({ score }) => score != null);
  if (!scored.length) {
    return null;
  }
  return scored.reduce((best, current) => (current.score > best.score ? current : best)).item;
}

function bestRepairScore(repairContext) {
  const bestCandidate = bestRepairCandidateDelta(repairContext);
  if (bestCandidate) {
    return numericScore(bestCandidate.score);
  }
  return numericScore(repairContext?.baselineScore);
}

function CandidateCard({ batch, candidate, asset, repairContext, updating, repairing, repairProtected, onOpenCompare, onCreateTargetedRepair, onSelect, onReject, onOpenVideo, onCreateRepairBranch }) {
  const isSelected = candidate.status === "selected";
  const isRejected = candidate.status === "rejected";
  const evaluation = candidateEvaluation(candidate);
  const dimensions = evaluation.dimensions.slice(0, 4);
  const repairTargets = evaluation.repairTargets.slice(0, 3);
  const candidateDelta = repairContext?.candidateDeltas?.[candidate.id] || null;
  const delta = numericScore(candidateDelta?.score_delta);
  const dimensionDeltas = Array.isArray(candidateDelta?.dimension_deltas) ? candidateDelta.dimension_deltas.slice(0, 4) : [];
  return (
    <article className={["canvas-candidate-card", isSelected ? "selected" : "", isRejected ? "rejected" : ""].filter(Boolean).join(" ")}>
      <MediaPreview asset={asset} alt={`候选图 ${candidate.index + 1}`} />
      <div className="canvas-candidate-summary">
        <span>#{candidate.index + 1} · {candidate.status}</span>
        <strong>{candidate.score == null ? "未评分" : `Score ${formatScore(candidate.score)}`}</strong>
        {repairContext ? <small className={delta == null ? "" : delta >= 0 ? "score-up" : "score-down"}>相对原图 {formatScoreDelta(delta)}</small> : null}
        {evaluation.suggestion ? <small>{trimCandidateText(evaluation.suggestion, 90)}</small> : null}
      </div>
      {dimensions.length ? (
        <div className="canvas-candidate-score-grid" aria-label="候选图评分维度">
          {dimensions.map((dimension) => (
            <div key={dimension.key || dimension.label}>
              <span>{dimension.label || dimension.key}</span>
              <strong>{formatScore(dimension.score)}</strong>
              <i style={{ width: `${scorePercent(dimension.score)}%` }} />
            </div>
          ))}
        </div>
      ) : null}
      {dimensionDeltas.length ? (
        <div className="canvas-dimension-delta-grid" aria-label="修复维度变化">
          {dimensionDeltas.map((item) => (
            <div key={item.key || item.label}>
              <span>{item.label || item.key}</span>
              <strong className={numericScore(item.delta) == null ? "" : numericScore(item.delta) >= 0 ? "score-up" : "score-down"}>{formatScoreDelta(numericScore(item.delta))}</strong>
              {candidate.node_id ? (
                <button type="button" onClick={() => onCreateTargetedRepair?.(item)} disabled={repairing} aria-label={`继续修复${item.label || item.key}`}>
                  {repairing ? <Loader2 className="spinning" size={12} /> : <Sparkles size={12} />}
                  <small>继续修复</small>
                </button>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
      {repairTargets.length ? (
        <div className="canvas-candidate-repair">
          <span>修复目标</span>
          {repairTargets.map((target) => <small key={target}>{trimCandidateText(target, 72)}</small>)}
        </div>
      ) : null}
      <div className="canvas-candidate-actions">
        <button type="button" onClick={() => onSelect(batch, candidate, "selected")} disabled={updating || isSelected} aria-label="精选候选图">
          {updating ? <Loader2 className="spinning" size={14} /> : <Check size={14} />}
        </button>
        <button type="button" onClick={() => onReject(batch, candidate, "rejected")} disabled={updating || isRejected || repairProtected} aria-label="淘汰候选图" title={repairProtected ? "已有修复或生产媒体分支，不能直接淘汰精选图" : undefined}><X size={14} /></button>
        <button type="button" onClick={() => onCreateRepairBranch(batch, candidate)} disabled={repairing || !isSelected || !candidate.node_id} aria-label="从评分生成修复分支">
          {repairing ? <Loader2 className="spinning" size={14} /> : <Sparkles size={14} />}
        </button>
        {repairContext ? <button type="button" onClick={onOpenCompare} aria-label="对比原图和修复图"><Maximize2 size={14} /></button> : null}
        <button type="button" onClick={() => onOpenVideo(candidate)} disabled={!isSelected || !candidate.node_id} aria-label="从精选图生成视频"><Video size={14} /></button>
      </div>
    </article>
  );
}

function RepairComparisonDialog({ comparison, onClose, onCreateTargetedRepair }) {
  const dialogRef = useRef(null);
  useEffect(() => {
    focusFirstDialogControl(dialogRef.current);
  }, []);
  return (
    <div className="canvas-dialog-backdrop" role="presentation">
      <section ref={dialogRef} className="canvas-dialog repair-comparison-dialog" role="dialog" aria-modal="true" aria-labelledby="canvas-repair-compare-title" onKeyDown={(event) => handleDialogKeyDown(event, dialogRef.current, onClose)}>
        <div className="canvas-dialog-heading">
          <span>Repair Compare</span>
          <strong id="canvas-repair-compare-title">原图 / 修复图对比</strong>
          <p>检查修复 Prompt 是否真的改善了低分维度，而不是只生成了另一张相似图片。</p>
        </div>
        <div className="repair-comparison-grid">
          <div>
            <span>Original</span>
            <MediaPreview asset={comparison.sourceAsset} alt="原始精选图" />
          </div>
          <div>
            <span>Repair</span>
            <MediaPreview asset={comparison.candidateAsset} alt="修复候选图" />
          </div>
        </div>
        <div className="repair-comparison-metrics">
          <strong>总分变化 {formatScoreDelta(numericScore(comparison.delta?.score_delta))}</strong>
          {(comparison.delta?.dimension_deltas || []).map((item) => (
            <div key={item.key || item.label}>
              <span>{item.label || item.key}</span>
              <small>{formatScore(item.baseline_score)} → {formatScore(item.score)}</small>
              <strong className={numericScore(item.delta) == null ? "" : numericScore(item.delta) >= 0 ? "score-up" : "score-down"}>{formatScoreDelta(numericScore(item.delta))}</strong>
              {comparison.candidate?.node_id ? <button type="button" onClick={() => onCreateTargetedRepair?.(item)}>继续修复</button> : null}
            </div>
          ))}
        </div>
        {comparison.delta?.resolved_targets?.length ? (
          <div className="canvas-candidate-repair">
            <span>已解决目标</span>
            {comparison.delta.resolved_targets.map((target) => <small key={target}>{trimCandidateText(target, 100)}</small>)}
          </div>
        ) : null}
        <div className="canvas-dialog-actions">
          <button className="primary-image-action compact" type="button" onClick={onClose}>关闭</button>
        </div>
      </section>
    </div>
  );
}

export function ImageBatchDialog({ settings, selectedCount, creating, onChange, onClose, onSubmit }) {
  return (
    <Modal open title="生成候选图" onCancel={onClose} footer={null} closable={!creating} keyboard={!creating} maskClosable={!creating} destroyOnClose>
      <section className="canvas-dialog">
        <div className="canvas-dialog-heading">
          <span>Text to Image Batch</span>
          <strong id="canvas-image-batch-title">从当前画布图谱生成候选图</strong>
          <p>一次生成多张可比较的专业候选图。不要急着做视频，先用图片探索构图、主体、材质和光影。</p>
        </div>
        <div className="canvas-dialog-grid">
          <label>
            <span>候选数量</span>
            <select value={settings.count} onChange={(event) => onChange({ ...settings, count: Number(event.target.value) })}>
              {[1, 2, 3, 4].map((count) => <option value={count} key={count}>{count} 张</option>)}
            </select>
          </label>
          <label>
            <span>画幅</span>
            <select value={settings.size} onChange={(event) => onChange({ ...settings, size: event.target.value })}>
              <option value="1024x1024">1:1 · 1024</option>
              <option value="1536x1024">3:2 · 横图</option>
              <option value="1024x1536">2:3 · 竖图</option>
              <option value="auto">Auto</option>
            </select>
          </label>
          <label>
            <span>质量</span>
            <select value={settings.quality} onChange={(event) => onChange({ ...settings, quality: event.target.value })}>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="auto">Auto</option>
            </select>
          </label>
        </div>
        <small>将基于当前选中图谱的 {selectedCount} 个源节点生成批次，并把精选候选图回写为画布节点。</small>
        <div className="canvas-dialog-actions">
          <button className="secondary-image-action" type="button" onClick={onClose} disabled={creating}>取消</button>
          <button className="primary-image-action compact" type="button" onClick={onSubmit} disabled={creating || !selectedCount}>
            {creating ? <Loader2 className="spinning" size={16} /> : <ImagePlus size={16} />}
            <span>开始生成</span>
          </button>
        </div>
      </section>
    </Modal>
  );
}

export function BranchOperationDialog({ operation, busy, onReasonChange, onClose, onSubmit }) {
  const affectedNodes = operation.affectedNodes || [];
  return (
    <Modal open title="分支治理确认" onCancel={onClose} footer={null} closable={!busy} keyboard={!busy} maskClosable={!busy} destroyOnClose>
      <section className="canvas-dialog branch-operation-dialog">
        <div className="canvas-dialog-heading">
          <span>Branch Governance</span>
          <strong id="canvas-branch-operation-title">{branchOperationLabel(operation.operation)} · {branchScopeLabel(operation.includeDescendants ? "subtree" : operation.operation === "pin" ? "path" : "single")}</strong>
          <p>提交前确认治理范围和原因。操作会写入独立 branch operation log，并保留非破坏式 lineage。</p>
        </div>
        <div className="branch-operation-impact">
          <div><span>目标版本</span><strong>{operation.node?.title || "Repair Version"}</strong></div>
          <div><span>影响范围</span><strong>{affectedNodes.length} 个版本节点</strong></div>
          <div><span>状态变化</span><strong>{operation.operation === "pin" ? "设为主生产路径" : operation.operation === "unpin" ? "取消主生产路径" : operation.nextStatus === "archived" ? "active → archived" : "archived → active"}</strong></div>
        </div>
        <div className="branch-operation-affected-list" aria-label="受影响版本">
          {affectedNodes.slice(0, 8).map((node) => <small key={node.id}>{node.payload?.repair_focus_label || node.title} · {node.payload?.status || "active"}</small>)}
        </div>
        <label className="canvas-dialog-prompt">
          <span>操作原因</span>
          <textarea value={operation.reason || ""} onChange={(event) => onReasonChange(event.target.value)} placeholder="说明为什么要固定主线、归档或恢复这个分支，例如：客户已确认该方向，或该子树主体漂移严重。" />
        </label>
        <div className="canvas-dialog-actions">
          <button className="secondary-image-action" type="button" onClick={onClose} disabled={busy}>取消</button>
          <button className="primary-image-action compact" type="button" onClick={onSubmit} disabled={busy || !operation.reason?.trim()}>
            {busy ? <Loader2 className="spinning" size={16} /> : <Check size={16} />}
            <span>确认写入治理日志</span>
          </button>
        </div>
      </section>
    </Modal>
  );
}

export function MediaApprovalDialog({ approval, busy, onReasonChange, onClose, onSubmit }) {
  const node = approval.node;
  const approving = Boolean(approval.approved);
  return (
    <Modal open title="生产媒体审批" onCancel={onClose} footer={null} closable={!busy} keyboard={!busy} maskClosable={!busy} destroyOnClose>
      <section className="canvas-dialog media-approval-dialog">
        <div className="canvas-dialog-heading">
          <span>Production Approval</span>
          <strong id="canvas-media-approval-title">{approving ? "批准生产媒体" : "撤销生产批准"}</strong>
          <p>{approving ? "确认该编辑图片或生成视频可以进入最终交付链路。" : "撤销生产批准会保留节点和 lineage，但 Final JSON 会记录撤销治理事件。"}</p>
        </div>
        <div className="branch-operation-impact">
          <div><span>目标媒体</span><strong>{node?.title || "Production media"}</strong></div>
          <div><span>类型</span><strong>{NODE_TYPE_LABELS[node?.type] || node?.type || "Media"}</strong></div>
          <div><span>状态变化</span><strong>{node?.payload?.approval_status === "approved" ? "approved" : "draft"} → {approving ? "approved" : "draft"}</strong></div>
        </div>
        <div className="branch-operation-affected-list" aria-label="审批媒体引用">
          {node?.payload?.asset_id ? <small>asset {String(node.payload.asset_id).slice(0, 8)}</small> : null}
          {node?.payload?.task_id ? <small>task {String(node.payload.task_id).slice(0, 8)}</small> : null}
          {node?.payload?.source_asset_id ? <small>source {String(node.payload.source_asset_id).slice(0, 8)}</small> : null}
        </div>
        <label className="canvas-dialog-prompt">
          <span>审批原因</span>
          <textarea value={approval.reason || ""} onChange={(event) => onReasonChange(event.target.value)} placeholder={approving ? "说明为什么该媒体可进入生产，例如：客户确认、主体稳定、符合投放规格。" : "说明为什么撤销生产批准，例如：客户反馈、画面瑕疵、需重新生成。"} />
        </label>
        <div className="canvas-dialog-actions">
          <button className="secondary-image-action" type="button" onClick={onClose} disabled={busy}>取消</button>
          <button className="primary-image-action compact" type="button" onClick={onSubmit} disabled={busy || !approval.reason?.trim()}>
            {busy ? <Loader2 className="spinning" size={16} /> : <Check size={16} />}
            <span>{approving ? "确认批准并写入治理日志" : "确认撤销并写入治理日志"}</span>
          </button>
        </div>
      </section>
    </Modal>
  );
}

export function ImageEditDialog({ node, sources = [], asset, maskAssets = [], prompt, settings, creating, onPromptChange, onSettingsChange, onClose, onSubmit }) {
  return (
    <Modal open title="编辑图片" onCancel={onClose} footer={null} closable={!creating} keyboard={!creating} maskClosable={!creating} destroyOnClose>
      <section className="canvas-dialog">
        <div className="canvas-dialog-heading">
          <span>Image Edit</span>
          <strong id="canvas-image-edit-title">在画布里编辑图片</strong>
          <p>基于当前图谱的图片与 @引用生成非破坏式编辑版本。结果会作为新节点回写，不覆盖原图。</p>
        </div>
        <div className="canvas-edit-source-stack" aria-label="本次图片编辑源图">
          {(sources.length ? sources : [{ node, asset }]).slice(0, 8).map((source, index) => (
            <div className="canvas-video-source" key={source.node?.id || source.asset?.id || index}>
              <MediaPreview asset={source.asset || asset} alt={source.node?.title || node.title} compact />
              <span>{index === 0 ? "Primary source" : `Reference ${index + 1}`}</span>
              <strong>{source.node?.title || node.title}</strong>
            </div>
          ))}
        </div>
        <div className="canvas-dialog-grid">
          <label>
            <span>编辑类型</span>
            <select value={settings.actionType} onChange={(event) => onSettingsChange({ ...settings, actionType: event.target.value, maskAssetId: event.target.value === "inpaint" ? settings.maskAssetId : "" })}>
              <option value="edit">通用编辑</option>
              <option value="image_to_image">图像重绘</option>
              <option value="style_transfer">风格迁移</option>
              <option value="inpaint">局部修复 · Mask</option>
            </select>
          </label>
          <label>
            <span>画幅</span>
            <select value={settings.size} onChange={(event) => onSettingsChange({ ...settings, size: event.target.value })}>
              <option value="1024x1024">1:1 · 1024</option>
              <option value="1536x1024">3:2 · 横图</option>
              <option value="1024x1536">2:3 · 竖图</option>
              <option value="auto">Auto</option>
            </select>
          </label>
          <label>
            <span>质量</span>
            <select value={settings.quality} onChange={(event) => onSettingsChange({ ...settings, quality: event.target.value })}>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="auto">Auto</option>
            </select>
          </label>
          {settings.actionType === "inpaint" ? (
            <label>
              <span>Mask 图片</span>
              <select value={settings.maskAssetId || ""} onChange={(event) => onSettingsChange({ ...settings, maskAssetId: event.target.value })}>
                <option value="">选择本次图谱里的 mask 图片</option>
                {(sources.length ? sources.map((source) => source.asset).filter(Boolean) : maskAssets.filter((item) => item.id === asset?.id)).map((item) => <option key={item.id} value={item.id}>{assetLabel(item, assetKindLabel(item))}</option>)}
              </select>
            </label>
          ) : null}
        </div>
        <label className="canvas-dialog-prompt">
          <span>编辑提示词</span>
          <textarea value={prompt} onChange={(event) => onPromptChange(event.target.value)} placeholder="描述要保留和要改变的内容，例如：用 @产品图 保持主体，用 @风格图 迁移光影材质，把背景改成高级棚拍暖光…" />
        </label>
        <div className="canvas-dialog-actions">
          <button className="secondary-image-action" type="button" onClick={onClose} disabled={creating}>取消</button>
          <button className="primary-image-action compact" type="button" onClick={onSubmit} disabled={creating || !prompt.trim() || (settings.actionType === "inpaint" && !settings.maskAssetId)}>
            {creating ? <Loader2 className="spinning" size={16} /> : <Sparkles size={16} />}
            <span>生成编辑版本</span>
          </button>
        </div>
      </section>
    </Modal>
  );
}

export function VideoFromCandidateDialog({ candidate, prompt, promptArtifactId, optimizing, creating, onOptimizePrompt, onPromptChange, onClose, onSubmit }) {
  return (
    <Modal open title="从候选图生成视频" onCancel={onClose} footer={null} closable={!creating} keyboard={!creating} maskClosable={!creating} destroyOnClose>
      <section className="canvas-dialog">
        <div className="canvas-dialog-heading">
          <span>Image to Video</span>
          <strong id="canvas-video-title">从精选图生成视频</strong>
          <p>视频只从已精选图片启动，确保主体和风格先在图片阶段稳定下来。</p>
        </div>
        <div className="canvas-video-source">
          <span>Source candidate</span>
          <strong>#{candidate.index + 1} · {candidate.id.slice(0, 8)}</strong>
        </div>
        <label className="canvas-dialog-prompt">
          <span>运动与镜头提示词</span>
          {promptArtifactId ? <small>当前将使用已保存的视频 Prompt 版本生成视频。</small> : <small>编辑提示词后会作为手写版本提交，不再绑定已保存版本。</small>}
          <textarea value={prompt} onChange={(event) => onPromptChange(event.target.value)} placeholder="描述镜头运动、节奏、主体动作、转场和需要保持不变的视觉锚点…" />
        </label>
        <div className="canvas-dialog-actions">
          <button className="secondary-image-action" type="button" onClick={onClose} disabled={creating}>取消</button>
          <button className="secondary-image-action" type="button" onClick={onOptimizePrompt} disabled={creating || optimizing}>
            {optimizing ? <Loader2 className="spinning" size={16} /> : <Sparkles size={16} />}
            <span>{promptArtifactId ? "重新优化 Prompt" : "优化视频 Prompt"}</span>
          </button>
          <button className="primary-image-action compact" type="button" onClick={onSubmit} disabled={creating || !prompt.trim()}>
            {creating ? <Loader2 className="spinning" size={16} /> : <Video size={16} />}
            <span>生成视频</span>
          </button>
        </div>
      </section>
    </Modal>
  );
}

export function VideoRemixDialog({ node, asset, prompt, creating, onPromptChange, onClose, onSubmit }) {
  return (
    <Modal open title="调整视频 / 重新生成" onCancel={onClose} footer={null} closable={!creating} keyboard={!creating} maskClosable={!creating} destroyOnClose>
      <section className="canvas-dialog">
        <div className="canvas-dialog-heading">
          <span>Video Remix</span>
          <strong id="canvas-video-remix-title">调整视频 / 重新生成</strong>
          <p>当前版本会基于原始首帧重新生成一个新视频，不直接修改已有视频文件。</p>
        </div>
        <div className="canvas-video-source">
          <MediaPreview asset={asset} alt={node.title} compact />
          <span>Source video</span>
          <strong>{node.title}</strong>
        </div>
        <label className="canvas-dialog-prompt">
          <span>新的运动与镜头提示词</span>
          <textarea value={prompt} onChange={(event) => onPromptChange(event.target.value)} placeholder="描述要调整的镜头运动、主体动作、节奏、转场和保持不变的视觉锚点…" />
        </label>
        <small>会读取该视频记录的源图片资产作为首帧，生成一个新的画布视频节点。</small>
        <div className="canvas-dialog-actions">
          <button className="secondary-image-action" type="button" onClick={onClose} disabled={creating}>取消</button>
          <button className="primary-image-action compact" type="button" onClick={onSubmit} disabled={creating || !prompt.trim()}>
            {creating ? <Loader2 className="spinning" size={16} /> : <Video size={16} />}
            <span>重新生成视频</span>
          </button>
        </div>
      </section>
    </Modal>
  );
}

export function SeriesPlanPreview({ plan }) {
  return (
    <div className="canvas-series-preview">
      <div className="canvas-series-locks">
        <span>角色锁定</span>
        <strong>{plan.character_lock?.join(" / ") || "未检测到角色锁定"}</strong>
        <span>风格锁定</span>
        <strong>{styleLockText(plan.style_lock) || "沿用画布风格系统"}</strong>
      </div>
      <div className="canvas-series-frame-list">
        {plan.frames?.map((frame) => (
          <article key={frame.index}>
            <span>{String(frame.index).padStart(2, "0")}</span>
            <div>
              <strong>{frame.title}</strong>
              <p>{frame.beat}</p>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

export function CanvasEdgeLayer({ edges, nodes, selectedNodeId, selectedSourceIds }) {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const selectedSourceSet = new Set(selectedSourceIds);
  return (
    <svg className="canvas-edge-layer" aria-hidden="true">
      <defs>
        <marker id="canvas-edge-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" />
        </marker>
        <marker id="canvas-edge-arrow-image-edit" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" />
        </marker>
        <marker id="canvas-edge-arrow-video" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" />
        </marker>
      </defs>
      {edges.map((edge) => {
        const source = nodesById.get(edge.source_node_id);
        const target = nodesById.get(edge.target_node_id);
        if (!source || !target) {
          return null;
        }
        const path = edgePath(source, target);
        const active = edge.source_node_id === selectedNodeId || edge.target_node_id === selectedNodeId || (selectedSourceSet.has(edge.source_node_id) && selectedSourceSet.has(edge.target_node_id));
        const className = ["canvas-edge", `type-${edge.type.replace(/_/g, "-")}`, active ? "active" : ""].filter(Boolean).join(" ");
        return <path key={edge.id} className={className} d={path} markerEnd={`url(#${edgeMarkerId(edge.type)})`} />;
      })}
    </svg>
  );
}

export function MediaPreview({ asset, alt, compact = false }) {
  const url = safeDisplayUrl(asset?.url);
  const className = compact ? "canvas-media-preview compact" : "canvas-media-preview";
  if (isImageAsset(asset) && url) {
    return <img className={className} src={url} alt={alt} loading="lazy" decoding="async" referrerPolicy="no-referrer" draggable={false} />;
  }
  if (isVideoAsset(asset) && url) {
    return <video className={className} src={url} muted playsInline preload="metadata" draggable={false} />;
  }
  return <span className={className}>{isVideoAsset(asset) ? <Film size={compact ? 16 : 22} /> : <ImagePlus size={compact ? 16 : 22} />}</span>;
}

export function CanvasNodeCard({ node, asset, selected, inScope, onSelect, onPointerDown }) {
  const className = ["canvas-node-card", `type-${node.type.replace(/_/g, "-")}`, selected ? "selected" : "", inScope && !selected ? "in-scope" : ""].filter(Boolean).join(" ");
  return (
    <article
      className={className}
      style={{ transform: `translate(${node.position.x}px, ${node.position.y}px)`, width: node.size.width, height: node.size.height }}
      role="button"
      tabIndex={0}
      aria-selected={selected}
      onKeyDown={(event) => selectNodeWithKeyboard(event, onSelect)}
      onPointerDown={onPointerDown}
    >
      <span>{nodeTypeLabel(node.type)}</span>
      <strong>{node.title}</strong>
      {asset ? <MediaPreview asset={asset} alt={node.title} /> : <p>{nodeSummary(node)}</p>}
      <NodeMediaBadges node={node} />
    </article>
  );
}

function NodeMediaBadges({ node }) {
  const badges = nodeMediaBadges(node);
  if (!badges.length) {
    return null;
  }
  return <div className="canvas-node-media-badges">{badges.map((badge) => <small key={badge}>{badge}</small>)}</div>;
}

export function NodeInspector({ node, edges = [], assetById = new Map(), updatingPromptProgram, onSavePromptProgram }) {
  if (node.type === "prompt_program") {
    return <PromptProgramInspector node={node} updating={updatingPromptProgram} onSave={onSavePromptProgram} />;
  }
  return (
    <div className="canvas-inspector-card">
      <strong>{node.title}</strong>
      <dl>
        <div><dt>类型</dt><dd>{nodeTypeLabel(node.type)}</dd></div>
        <div><dt>坐标</dt><dd>{Math.round(node.position.x)}, {Math.round(node.position.y)}</dd></div>
        <div><dt>角色</dt><dd>{node.payload?.role || "未设置"}</dd></div>
      </dl>
      <div className="canvas-safe-fields">
        {safePayloadFields(node).map((field) => (
          <div key={field.label}>
            <span>{field.label}</span>
            <strong>{field.value}</strong>
          </div>
        ))}
      </div>
      <MediaBranchComparison node={node} assetById={assetById} />
      <MediaLineageInspector node={node} edges={edges} />
    </div>
  );
}

function MediaBranchComparison({ node, assetById }) {
  const comparison = mediaBranchComparison(node, assetById);
  if (!comparison) {
    return null;
  }
  return (
    <section className="canvas-media-branch-compare" aria-label="媒体分支对比">
      <div className="canvas-media-branch-heading">
        <span>Branch Compare</span>
        <strong>{comparison.title}</strong>
      </div>
      <div className="canvas-media-compare-grid">
        {comparison.items.map((item) => (
          <div key={item.label} className={item.role ? `role-${item.role}` : ""}>
            <MediaPreview asset={item.asset} alt={item.label} compact />
            <span>{item.label}</span>
            <strong>{item.caption}</strong>
          </div>
        ))}
      </div>
      {comparison.note ? <p>{comparison.note}</p> : null}
    </section>
  );
}

function MediaLineageInspector({ node, edges }) {
  const fields = mediaLineageFields(node, edges);
  if (!fields.length) {
    return null;
  }
  return (
    <section className="canvas-media-lineage-inspector" aria-label="媒体生产链路">
      <div>
        <span>Media Lineage</span>
        <strong>{mediaLineageTitle(node)}</strong>
      </div>
      <div className="canvas-media-lineage-grid">
        {fields.map((field) => (
          <div key={field.label}>
            <span>{field.label}</span>
            <strong>{field.value}</strong>
          </div>
        ))}
      </div>
      {node.payload?.final_prompt || node.payload?.motion_prompt ? <p>{trimInspectorText(node.payload.final_prompt || node.payload.motion_prompt, 180)}</p> : null}
    </section>
  );
}

export function PromptProgramInspector({ node, updating, onSave }) {
  const [draft, setDraft] = useState(() => promptProgramDraft(node));
  useEffect(() => {
    setDraft(promptProgramDraft(node));
  }, [node.id, node.payload]);
  return (
    <div className="canvas-inspector-card prompt-program-inspector">
      <strong>{node.title}</strong>
      <small>把 Prompt 拆成可控生产块，后续图片批次、精修和视频首帧都应该从这里出发。</small>
      {PROMPT_PROGRAM_FIELDS.map((field) => (
        <label key={field.key}>
          <span>{field.label}</span>
          <textarea value={draft[field.key]} onChange={(event) => setDraft({ ...draft, [field.key]: event.target.value })} />
        </label>
      ))}
      <div className="canvas-safe-fields">
        {node.payload?.referenced_asset_mentions?.length ? <div><span>@资产引用</span><strong>{node.payload.referenced_asset_mentions.map((label) => `@${label}`).join(" / ")}</strong></div> : null}
        {node.payload?.reference_instruction ? <div><span>引用策略</span><strong>{trimInspectorText(node.payload.reference_instruction)}</strong></div> : null}
      </div>
      <button className="primary-image-action compact" type="button" onClick={() => onSave?.(node, draft)} disabled={updating}>
        {updating ? <Loader2 className="spinning" size={16} /> : <Check size={16} />}
        <span>保存 Prompt Program</span>
      </button>
    </div>
  );
}

export function repairBatchContext(batch) {
  const context = batch.repair_context || {};
  if (!context.is_repair_version) {
    return null;
  }
  return {
    repairPromptId: context.repair_prompt_node_id || "",
    repairPromptTitle: context.repair_prompt_title || "Repair Prompt",
    evaluationId: context.evaluation_node_id || "",
    sourceImageId: context.source_image_node_id || "",
    sourceImageAssetId: context.source_image_asset_id || "",
    sourceImageUrl: context.source_image_url || "",
    sourceImageMediaType: context.source_image_media_type || "image/png",
    sourceImageTitle: context.source_image_title || "精选图",
    repairFocus: context.repair_focus || {},
    baselineScore: numericScore(context.baseline_score),
    candidateDeltas: context.candidate_deltas || {},
  };
}

function repairComparisonPayload(candidate, candidateAsset, repairContext, assetById, onCreateTargetedRepair) {
  return {
    candidate,
    candidateAsset,
    sourceAsset: sourceRepairAsset(repairContext, assetById),
    repairContext,
    delta: repairContext?.candidateDeltas?.[candidate.id] || {},
    onCreateTargetedRepair,
  };
}

function sourceRepairAsset(repairContext, assetById) {
  const asset = assetById.get(repairContext?.sourceImageAssetId);
  if (asset) {
    return asset;
  }
  if (!repairContext?.sourceImageAssetId || !repairContext?.sourceImageUrl) {
    return null;
  }
  return {
    id: repairContext.sourceImageAssetId,
    kind: "image",
    media_type: repairContext.sourceImageMediaType || "image/png",
    url: repairContext.sourceImageUrl,
    metadata: { filename: repairContext.sourceImageTitle || "原始精选图" },
  };
}

export function isEditableImageNode(node, asset) {
  if (!node?.payload?.asset_id) {
    return false;
  }
  if (asset) {
    return isImageAsset(asset);
  }
  return String(node.payload?.media_type || "").startsWith("image/") || ["selected_image", "generated_image", "edited_image"].includes(node.type);
}

export function isRepairPromptNode(node) {
  return node?.type === "prompt_program" && node.payload?.workflow === "evaluation_repair_phase_4";
}

export function isRemixableVideoNode(node) {
  return node?.type === "generated_video" && Boolean(node.payload?.source_asset_id);
}

export function isApprovableProductionMediaNode(node) {
  return node?.type === "edited_image" || node?.type === "generated_video";
}

export function nodeDisplayAsset(node, assetById) {
  const asset = assetById.get(node.payload?.asset_id);
  if (asset) {
    return asset;
  }
  if (!node.payload?.asset_id || (!node.payload?.image_url && !node.payload?.media_type)) {
    return null;
  }
  const isVideoNode = node.type === "generated_video" || String(node.payload.media_type || "").startsWith("video/");
  return {
    id: node.payload.asset_id,
    kind: isVideoNode ? "video" : "image",
    media_type: node.payload.media_type || (isVideoNode ? "video/mp4" : "image/png"),
    url: node.payload.image_url || node.payload.video_url || "",
    metadata: { filename: node.title },
  };
}

export function restoreDialogFocus(focusRef) {
  const target = focusRef.current;
  focusRef.current = null;
  if (target && typeof target.focus === "function") {
    window.requestAnimationFrame(() => target.focus());
  }
}

function nodeTypeLabel(type) {
  return NODE_TYPE_LABELS[type] || type;
}

function promptProgramDraft(node) {
  return Object.fromEntries(PROMPT_PROGRAM_FIELDS.map((field) => [field.key, node.payload?.[field.key] || ""]));
}

function nodeMediaBadges(node) {
  const badges = [];
  if (node.payload?.approval_status === "approved") {
    badges.push("approved");
  }
  if (node.payload?.source === "canvas_image_edit") {
    badges.push(node.payload?.mask_asset_id ? "masked edit" : "edit branch");
  }
  if (node.type === "generated_video") {
    badges.push(node.payload?.source_asset_id ? "source-frame regen" : "video output");
  }
  if (node.payload?.task_id) {
    badges.push(`task ${String(node.payload.task_id).slice(0, 8)}`);
  }
  return badges;
}

function nodeSummary(node) {
  if (node.type === "repair_version") {
    const status = node.payload?.status === "archived" ? "已归档" : "活跃";
    const focus = node.payload?.repair_focus_label || "整体修复";
    return `${status} · ${focus} · ${node.payload?.source_image_title || "精选图"}`;
  }
  return node.payload?.prompt || node.payload?.instruction || node.payload?.goal || node.payload?.scene || node.payload?.motion_prompt || node.payload?.role || "等待编译为创作图谱节点";
}

function candidateEvaluation(candidate) {
  const evaluation = candidate.metadata?.evaluation || {};
  return {
    dimensions: Array.isArray(evaluation.dimensions) ? evaluation.dimensions : [],
    repairTargets: Array.isArray(evaluation.repair_targets) ? evaluation.repair_targets : [],
    suggestion: evaluation.suggestion || "",
  };
}

function formatScore(score) {
  return Number.isFinite(Number(score)) ? Number(score).toFixed(1) : "—";
}

function governanceOperationCounts(operations) {
  return operations.reduce((counts, operation) => ({ ...counts, [operation.operation]: (counts[operation.operation] || 0) + 1 }), {});
}

function operationTargetLabel(operation, labelsByNodeId) {
  if (!operation) {
    return "—";
  }
  const payload = operation.payload || {};
  return labelsByNodeId.get(operation.target_node_id) || operation.target_node_id?.slice(0, 8) || (payload.candidate_id ? `candidate ${String(payload.candidate_id).slice(0, 8)}` : "") || (payload.asset_id ? `asset ${String(payload.asset_id).slice(0, 8)}` : "") || "canvas";
}

function branchOperationLabel(operation) {
  return ({ materialize: "物化", pin: "主线", unpin: "取消主线", archive: "归档", restore: "恢复", approve: "批准", revoke: "撤销批准", select: "精选图片", reject: "拒绝图片", candidate: "候选状态" })[operation] || operation || "操作";
}

function branchScopeLabel(scope) {
  return ({ single: "单节点", subtree: "子树", path: "路径" })[scope] || scope || "范围";
}

function formatBranchOperationDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "刚刚";
  }
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function operationTimestamp(value) {
  const timestamp = new Date(value).getTime();
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function formatScoreDelta(delta) {
  if (!Number.isFinite(delta)) {
    return "—";
  }
  return `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}`;
}

function numericScore(score) {
  if (score == null || score === "") {
    return null;
  }
  const value = Number(score);
  return Number.isFinite(value) ? value : null;
}

function scorePercent(score) {
  const value = Number(score);
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, value * 10));
}

function trimCandidateText(value, limit) {
  const text = String(value || "");
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function candidateAsset(candidate, assetById) {
  return assetById.get(candidate.asset_id) || {
    id: candidate.asset_id,
    kind: "image",
    media_type: candidate.metadata?.media_type || "image/png",
    url: candidate.metadata?.image_url || "",
    metadata: { filename: `Candidate ${candidate.index + 1}` },
  };
}

function focusFirstDialogControl(dialog) {
  dialog?.querySelector("button, select, textarea, input")?.focus();
}

function handleDialogKeyDown(event, dialog, onClose) {
  if (event.key === "Escape") {
    event.preventDefault();
    onClose();
    return;
  }
  if (event.key !== "Tab" || !dialog) {
    return;
  }
  const controls = [...dialog.querySelectorAll("button:not(:disabled), select:not(:disabled), textarea:not(:disabled), input:not(:disabled), [tabindex]:not([tabindex='-1'])")];
  if (!controls.length) {
    return;
  }
  const first = controls[0];
  const last = controls[controls.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function mediaBranchComparison(node, assetById) {
  const resultAsset = nodeDisplayAsset(node, assetById);
  const sourceAsset = firstExistingAsset(assetById, node.payload?.source_asset_ids || [node.payload?.source_asset_id]);
  const maskAsset = node.payload?.mask_asset_id ? assetById.get(node.payload.mask_asset_id) : null;
  if (node.payload?.source === "canvas_image_edit" && resultAsset) {
    const items = [];
    if (sourceAsset) {
      items.push({ label: "Before", caption: assetLabel(sourceAsset, "源图"), asset: sourceAsset, role: "source" });
    }
    if (maskAsset) {
      items.push({ label: "Mask", caption: assetLabel(maskAsset, "局部约束"), asset: maskAsset, role: "mask" });
    }
    items.push({ label: "After", caption: node.payload?.action_type || "edited image", asset: resultAsset, role: "result" });
    return { title: maskAsset ? "Masked image repair" : "Image edit version", items, note: trimInspectorText(node.payload?.edit_prompt || node.payload?.final_prompt || "") };
  }
  if (node.type === "generated_video" && resultAsset) {
    const items = [];
    if (sourceAsset) {
      items.push({ label: "Source frame", caption: assetLabel(sourceAsset, "首帧"), asset: sourceAsset, role: "source" });
    }
    items.push({ label: "Video", caption: "regenerated output", asset: resultAsset, role: "result" });
    return { title: "Source frame to video", items, note: trimInspectorText(node.payload?.motion_prompt || "") };
  }
  return null;
}

function firstExistingAsset(assetById, assetIds) {
  return assetIds.map((id) => id && assetById.get(id)).find(Boolean) || null;
}

function mediaLineageTitle(node) {
  if (node.payload?.source === "canvas_image_edit") {
    return node.payload?.mask_asset_id ? "Mask-based image edit" : "Non-destructive image edit";
  }
  if (node.type === "generated_video") {
    return "Image-to-video regeneration";
  }
  if (node.type === "selected_image") {
    return "Selected production image";
  }
  return "Media branch";
}

function mediaLineageFields(node, edges = []) {
  const fields = [];
  const incomingEdges = edges.filter((edge) => edge.target_node_id === node.id);
  const outgoingEdges = edges.filter((edge) => edge.source_node_id === node.id);
  if (!["selected_image", "edited_image", "generated_image", "generated_video"].includes(node.type) && node.payload?.source !== "canvas_image_edit") {
    return fields;
  }
  const sourceNodeIds = node.payload?.source_node_ids?.length ? node.payload.source_node_ids : incomingEdges.map((edge) => edge.source_node_id);
  if (sourceNodeIds.length) {
    fields.push({ label: "源节点", value: sourceNodeIds.map((id) => String(id).slice(0, 8)).join(" / ") });
  }
  if (node.payload?.source_asset_ids?.length) {
    fields.push({ label: "源图片", value: node.payload.source_asset_ids.map((id) => String(id).slice(0, 8)).join(" / ") });
  }
  if (node.payload?.source_asset_id) {
    fields.push({ label: "源首帧", value: String(node.payload.source_asset_id).slice(0, 8) });
  }
  if (node.payload?.mask_asset_id) {
    fields.push({ label: "Mask", value: String(node.payload.mask_asset_id).slice(0, 8) });
  }
  if (node.payload?.action_type) {
    fields.push({ label: "编辑动作", value: node.payload.action_type });
  }
  if (node.payload?.approval_status) {
    fields.push({ label: "生产批准", value: node.payload.approval_status === "approved" ? "approved" : "draft" });
  }
  if (node.payload?.approved_at) {
    fields.push({ label: "批准时间", value: String(node.payload.approved_at).slice(0, 16).replace("T", " ") });
  }
  if (node.payload?.task_id) {
    fields.push({ label: "任务", value: String(node.payload.task_id).slice(0, 8) });
  }
  if (incomingEdges.length) {
    fields.push({ label: "入边", value: incomingEdges.map((edge) => edge.type).join(" / ") });
  }
  if (outgoingEdges.length) {
    fields.push({ label: "输出", value: outgoingEdges.map((edge) => edge.type).join(" / ") });
  }
  return fields;
}

function edgeMarkerId(type) {
  if (type === "image_edit") {
    return "canvas-edge-arrow-image-edit";
  }
  if (type === "video_remix" || type === "video_from_image") {
    return "canvas-edge-arrow-video";
  }
  return "canvas-edge-arrow";
}

function safePayloadFields(node) {
  const fields = [];
  const role = node.payload?.role;
  if (role) {
    fields.push({ label: "角色", value: role });
  }
  if (node.payload?.mention_label) {
    fields.push({ label: "@ 引用", value: `@${node.payload.mention_label}` });
  }
  if (node.payload?.reference_role) {
    fields.push({ label: "参考类型", value: referenceRoleLabel(node.payload.reference_role) });
  }
  if (node.payload?.reference_instruction) {
    fields.push({ label: "参考约束", value: trimInspectorText(node.payload.reference_instruction) });
  }
  if (node.payload?.goal) {
    fields.push({ label: "生产目标", value: trimInspectorText(node.payload.goal) });
  }
  if (node.payload?.subject) {
    fields.push({ label: "主体语义", value: trimInspectorText(node.payload.subject) });
  }
  if (node.payload?.visual_style) {
    fields.push({ label: "视觉风格", value: trimInspectorText(node.payload.visual_style) });
  }
  if (node.payload?.prompt || node.payload?.subject_block || node.payload?.composition_block) {
    fields.push({ label: "Prompt 结构", value: trimInspectorText([node.payload.prompt, node.payload.subject_block, node.payload.composition_block].filter(Boolean).join(" / ")) });
  }
  if (node.payload?.dimensions) {
    fields.push({ label: "评分维度", value: trimInspectorText([node.payload.dimensions].flat().join(" / ")) });
  }
  if (node.payload?.manifest_sections) {
    fields.push({ label: "JSON 章节", value: trimInspectorText([node.payload.manifest_sections].flat().join(" / ")) });
  }
  if ((node.type === "brief" || node.type === "series_frame") && node.payload?.prompt) {
    fields.push({ label: node.type === "series_frame" ? "分镜 Prompt" : "简报", value: trimInspectorText(node.payload.prompt) });
  }
  if (node.payload?.scene) {
    fields.push({ label: "分镜目标", value: trimInspectorText(node.payload.scene) });
  }
  if (node.payload?.camera) {
    fields.push({ label: "镜头", value: trimInspectorText(node.payload.camera) });
  }
  if (node.type === "asset" && node.payload?.asset_kind) {
    fields.push({ label: "资产类型", value: node.payload.asset_kind === "video" ? "视频" : "图片" });
  }
  if (node.type === "asset" && node.payload?.media_type) {
    fields.push({ label: "媒体类型", value: node.payload.media_type });
  }
  if (node.payload?.source === "canvas_image_edit") {
    fields.push({ label: "编辑类型", value: node.payload.action_type || "edit" });
  }
  if (node.payload?.edit_prompt) {
    fields.push({ label: "编辑提示", value: trimInspectorText(node.payload.edit_prompt) });
  }
  if (node.payload?.approval_status) {
    fields.push({ label: "生产审批", value: node.payload.approval_status === "approved" ? "已批准" : "草稿" });
  }
  if (node.payload?.approval_reason) {
    fields.push({ label: "审批原因", value: trimInspectorText(node.payload.approval_reason) });
  }
  if (node.type === "generated_video" && node.payload?.source_asset_id) {
    fields.push({ label: "源首帧", value: String(node.payload.source_asset_id).slice(0, 8) });
  }
  if (!fields.length) {
    fields.push({ label: "状态", value: "等待编译" });
  }
  return fields;
}

function referenceRoleLabel(value) {
  return REFERENCE_ROLE_LABELS[value] || value;
}

function selectNodeWithKeyboard(event, onSelect) {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  event.preventDefault();
  onSelect?.();
}
