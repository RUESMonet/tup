import { useEffect, useMemo, useRef, useState } from "react";

import { createCanvas, createCanvasEdge, createCanvasImageBatch, createCanvasImageEditTask, createCanvasNode, createCanvasVideoTask, deleteCanvasNode, fetchCanvas, fetchCanvasBranchOperations, fetchCanvasImageBatches, fetchCanvasPromptArtifacts, fetchCanvases, materializeCanvasRepairVersion, optimizeCanvasImagePrompt, optimizeCanvasVideoPrompt, pinCanvasRepairVersion, planCanvasSeries, setCanvasMediaApproval, setCanvasRepairVersionStatus, submitCanvasFinal, unpinCanvasRepairVersion, updateCanvasImageCandidate, updateCanvasNode, updateCanvasNodePositions } from "../api/canvas";
import { assetMentionOptions, canvasBounds, canvasPoint, DEFAULT_VIEW, extractMentionQuery, FINAL_JSON_NODE_SIZE, findCanvasAssetNodeByMention, FIT_MAX_ZOOM, FIT_PADDING_X, FIT_PADDING_Y, MAX_ZOOM, MIN_ZOOM, NODE_SIZE, promptMentionLabels, replaceMentionToken, selectedConnectedNodeIds, selectedSourceNodeIds, SEMANTIC_NODE_SIZE, SERIES_FRAME_SIZE, SERIES_FRAME_VERTICAL_GAP, seriesFrameOrigin, seriesFramePayload, videoPromptRootNodeId, ZOOM_STEP } from "./canvasUtils";
import { CanvasWorkspaceView, repairBatchContext, restoreDialogFocus } from "./CanvasWorkspaceComponents";
import { useCanvasAssetUpload } from "./useCanvasAssetUpload";
import { assetKindLabel, assetLabel, isImageAsset, isVideoAsset } from "./mediaUrls";
import { useImageEditTaskPolling } from "./useImageEditTaskPolling";
import { useVideoTaskPolling } from "./useVideoTaskPolling";

const REFERENCE_ROLES = [
  { value: "product", label: "产品", help: "锁定主体、材质、Logo 和比例" },
  { value: "style", label: "风格", help: "迁移色彩、光线、质感和情绪" },
  { value: "character", label: "角色", help: "保持人物身份、脸型、发型和服装锚点" },
  { value: "composition", label: "构图", help: "参考布局、镜头、前中后景关系" },
  { value: "motion", label: "运动", help: "参考动作轨迹、镜头运动、剪辑节奏和时间感" },
];

const IMAGE_BATCH_DEFAULTS = {
  count: 4,
  size: "1024x1024",
  quality: "high",
};

const VIDEO_DEFAULTS = {
  duration: 5,
  aspectRatio: "16:9",
};

const IMAGE_EDIT_DEFAULTS = {
  actionType: "edit",
  maskAssetId: "",
  size: "1024x1024",
  quality: "high",
};
const SERVER_MANAGED_MEDIA_NODE_TYPES = new Set(["selected_image", "edited_image", "generated_image", "generated_video"]);

const SEMANTIC_SKELETON_NODES = [
  {
    type: "semantic_spec",
    title: "LMM 语义规格",
    offset: { x: 420, y: -80 },
    size: SEMANTIC_NODE_SIZE,
    payload: {
      role: "semantic_spec",
      goal: "把简报、参考资产和设计约束拆成可执行的主体、场景、构图、光线、材质与负面约束。",
      subject: "待从 brief 和 @参考资产提取主体身份、产品锚点或角色锚点。",
      scene: "待定义环境、时段、空间层次和情绪。",
      composition: "待定义画幅、主体比例、前中后景和视觉动线。",
      lighting: "待定义主光、辅光、反差、材质高光和氛围光。",
      visual_style: "待定义美术方向、质感、色彩和参考案例。",
      must_keep: ["主体身份", "关键材质", "品牌或角色锚点"],
      can_change: ["背景", "镜头距离", "光线氛围"],
      negative_constraints: ["低清晰度", "主体漂移", "文字错误", "廉价滤镜感"],
    },
  },
  {
    type: "prompt_program",
    title: "Prompt Program",
    offset: { x: 820, y: -80 },
    size: { width: 360, height: 230 },
    payload: {
      role: "prompt_program",
      profile: "professional_design",
      prompt: "基于语义规格编译专业图片生成 Prompt，先大量生成候选图，再进入精修和视频。",
      subject_block: "主体：锁定身份、比例、材质和关键识别点。",
      scene_block: "场景：描述环境、时段、空间关系和叙事目标。",
      composition_block: "构图：明确景别、机位、主体占比、前中后景和留白。",
      lighting_block: "光线：明确主光方向、反差、色温、反射和高光。",
      camera_block: "镜头：焦段、视角、景深、动态感。",
      negative_prompt: "避免低质感、主体变形、过度锐化、文字乱码、风格不一致。",
    },
  },
  {
    type: "evaluation",
    title: "LMM 评分规则",
    offset: { x: 1240, y: -80 },
    size: SEMANTIC_NODE_SIZE,
    payload: {
      role: "evaluation_policy",
      instruction: "对图片候选和精修结果进行可解释评分，而不是只给一个数字。",
      dimensions: ["prompt_alignment", "aesthetic", "composition", "detail_quality", "text_rendering", "character_consistency"],
      target_score: "8.5",
      repair_targets: ["构图不稳定", "材质不高级", "文字不准确", "主体身份漂移"],
    },
  },
  {
    type: "scene",
    title: "Scene 01",
    offset: { x: 420, y: 220 },
    size: SEMANTIC_NODE_SIZE,
    payload: {
      role: "scene",
      scene: "从精选图片资产组织成第一个可生成视频的场景。",
      atmosphere: "待由精选图和语义规格决定。",
      style: "继承 Prompt Program 和精选图片的视觉系统。",
    },
  },
  {
    type: "shot",
    title: "Shot 01",
    offset: { x: 820, y: 220 },
    size: SEMANTIC_NODE_SIZE,
    payload: {
      role: "shot",
      instruction: "把高质量精选图作为首帧，定义镜头运动、节奏和持续时间。",
      camera: "slow dolly in, controlled commercial pacing",
      motion_prompt: "保持主体和风格稳定，加入克制的镜头推进与细节动效。",
      duration: "5",
      aspect_ratio: "16:9",
    },
  },
  {
    type: "final_json",
    title: "Production JSON",
    offset: { x: 1240, y: 220 },
    size: FINAL_JSON_NODE_SIZE,
    payload: {
      role: "final_manifest",
      instruction: "最终 JSON 从画布图谱编译，包含 brief、semantic spec、prompt program、图片优化、精修、shot、video 和 lineage。",
      manifest_sections: ["brief", "semantic_spec", "prompt_programs", "references", "image_iterations", "edited_images", "scenes", "shots", "videos", "evaluations", "lineage"],
      status: "draft",
    },
  },
];

const SEMANTIC_SKELETON_EDGES = [
  ["semantic_spec", "prompt_program", "compiled_to_prompt"],
  ["prompt_program", "evaluation", "evaluated_by"],
  ["semantic_spec", "scene", "plans_scene"],
  ["scene", "shot", "contains_shot"],
  ["shot", "final_json", "included_in_final"],
  ["evaluation", "final_json", "included_in_final"],
];

const ACTIVE_BATCH_STATUSES = new Set(["pending", "queued", "running"]);
const REPAIR_VERSION_NODE_SIZE = { width: 320, height: 170 };
const REPAIR_VERSION_VERTICAL_GAP = 220;
const REPAIR_VERSION_HORIZONTAL_GAP = 380;

export function CanvasWorkspaceController({ projectId, assets = [], onStatus, onComplete }) {
  const [canvas, setCanvas] = useState(null);
  const [view, setView] = useState(DEFAULT_VIEW);
  const [brief, setBrief] = useState("");
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [creatingSemanticSkeleton, setCreatingSemanticSkeleton] = useState(false);
  const [creatingPromptProgram, setCreatingPromptProgram] = useState(false);
  const [updatingPromptProgram, setUpdatingPromptProgram] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [referenceRole, setReferenceRole] = useState("product");
  const [referenceInstruction, setReferenceInstruction] = useState("");
  const [seriesPlan, setSeriesPlan] = useState(null);
  const [planningSeries, setPlanningSeries] = useState(false);
  const [materializingSeries, setMaterializingSeries] = useState(false);
  const [materializingRepairGraph, setMaterializingRepairGraph] = useState(false);
  const [layingOutRepairGraph, setLayingOutRepairGraph] = useState(false);
  const [mentionMenu, setMentionMenu] = useState(null);
  const [activeMentionIndex, setActiveMentionIndex] = useState(0);
  const [finalSubmission, setFinalSubmission] = useState(null);
  const [finalSubmitting, setFinalSubmitting] = useState(false);
  const [finalError, setFinalError] = useState("");
  const [interaction, setInteraction] = useState(null);
  const [imageBatches, setImageBatches] = useState([]);
  const [promptArtifacts, setPromptArtifacts] = useState([]);
  const [optimizingPromptNodeId, setOptimizingPromptNodeId] = useState("");
  const [batchDialogOpen, setBatchDialogOpen] = useState(false);
  const [batchSettings, setBatchSettings] = useState(IMAGE_BATCH_DEFAULTS);
  const [creatingBatch, setCreatingBatch] = useState(false);
  const [creatingRepairBatch, setCreatingRepairBatch] = useState(false);
  const [updatingCandidateId, setUpdatingCandidateId] = useState("");
  const [repairingCandidateId, setRepairingCandidateId] = useState("");
  const [videoDialogCandidate, setVideoDialogCandidate] = useState(null);
  const [videoPrompt, setVideoPrompt] = useState("");
  const [optimizingVideoPromptNodeId, setOptimizingVideoPromptNodeId] = useState("");
  const [videoPromptArtifactId, setVideoPromptArtifactId] = useState("");
  const [creatingVideo, setCreatingVideo] = useState(false);
  const [pendingVideoTasks, setPendingVideoTasks] = useState({});
  const [imageEditDialogNode, setImageEditDialogNode] = useState(null);
  const [imageEditPrompt, setImageEditPrompt] = useState("");
  const [imageEditSettings, setImageEditSettings] = useState(IMAGE_EDIT_DEFAULTS);
  const [creatingImageEdit, setCreatingImageEdit] = useState(false);
  const [pendingImageEditTasks, setPendingImageEditTasks] = useState({});
  const [videoRemixDialogNode, setVideoRemixDialogNode] = useState(null);
  const [videoRemixPrompt, setVideoRemixPrompt] = useState("");
  const [mediaApprovalDialog, setMediaApprovalDialog] = useState(null);
  const [mediaApprovalSubmitting, setMediaApprovalSubmitting] = useState(false);
  const [approvingMediaNodeId, setApprovingMediaNodeId] = useState("");
  const [branchOperationDialog, setBranchOperationDialog] = useState(null);
  const [branchOperationSubmitting, setBranchOperationSubmitting] = useState(false);
  const [branchOperationFilters, setBranchOperationFilters] = useState({ limit: 40, offset: 0 });
  const [branchOperationPage, setBranchOperationPage] = useState({ operations: [], total: 0, limit: 40, offset: 0, loading: false, summary: null });
  const briefTextareaRef = useRef(null);
  const dialogReturnFocusRef = useRef(null);
  const branchOperationRequestRef = useRef(0);
  const latestCanvasIdRef = useRef("");
  const stageRef = useRef(null);
  const pointerCaptureTargetRef = useRef(null);
  const latestDragPositionRef = useRef(null);
  const mediaAssets = useMemo(() => assets.filter((asset) => isImageAsset(asset) || isVideoAsset(asset)), [assets]);
  const assetById = useMemo(() => new Map(mediaAssets.map((asset) => [asset.id, asset])), [mediaAssets]);
  const mentionOptions = useMemo(() => assetMentionOptions(mediaAssets, canvas?.nodes || []), [mediaAssets, canvas?.nodes]);
  const canvasMentionLabels = useMemo(() => new Set((canvas?.nodes || []).map((node) => node.payload?.mention_label).filter(Boolean)), [canvas?.nodes]);
  const unresolvedBriefMentions = useMemo(() => promptMentionLabels(brief).filter((label) => !canvasMentionLabels.has(label)), [brief, canvasMentionLabels]);
  const activeBatchCount = useMemo(() => imageBatches.filter((batch) => ACTIVE_BATCH_STATUSES.has(batch.status)).length, [imageBatches]);
  const selectedCandidateCount = useMemo(() => imageBatches.reduce((count, batch) => count + (batch.candidates || []).filter((candidate) => candidate.status === "selected").length, 0), [imageBatches]);
  const { addAssetNode, assetUploadInputRef, createAssetReferenceNode, openCanvasAssetUpload, uploadCanvasAssets, uploadingAssets } = useCanvasAssetUpload({
    canvas,
    creating,
    loadCanvas,
    onComplete,
    onStatus,
    projectId,
    referenceInstruction,
    referenceRole,
    referenceRoles: REFERENCE_ROLES,
    setBrief,
    setCanvas,
    setCreating,
    setFinalSubmission,
    setSelectedNodeId,
    setSeriesPlan,
    view,
  });
  latestCanvasIdRef.current = canvas?.id || "";

  useEffect(() => {
    let cancelled = false;
    loadCanvas(() => cancelled);
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    if (!canvas?.id || !activeBatchCount) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      refreshCanvasArtifacts().catch((error) => onStatus?.({ kind: "failed", message: error?.message || "图片批次刷新失败" }));
      onComplete?.();
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [canvas?.id, activeBatchCount, imageBatches]);

  useVideoTaskPolling({ canvas, pendingVideoTasks, setPendingVideoTasks, projectId, refreshCanvasArtifacts, onComplete, onStatus });
  useImageEditTaskPolling({ canvas, pendingImageEditTasks, setPendingImageEditTasks, projectId, refreshCanvasArtifacts, onComplete, onStatus });

  async function loadCanvas(isCancelled = () => false) {
    branchOperationRequestRef.current += 1;
    setLoading(true);
    onStatus?.({ kind: "loading", message: "正在打开无限画布" });
    try {
      const list = await fetchCanvases(projectId);
      const firstCanvas = list.canvases?.[0] || (await createCanvas(projectId, { name: "Creative Canvas" }));
      const [detail, batchList, artifactList] = await Promise.all([
        fetchCanvas(firstCanvas.id),
        fetchCanvasImageBatches(firstCanvas.id),
        fetchCanvasPromptArtifacts(firstCanvas.id, { limit: 100 }),
      ]);
      if (!isCancelled()) {
        setCanvas(detail);
        setBranchOperationFilters({ limit: 40, offset: 0 });
        setBranchOperationPage({ operations: [], total: 0, limit: 40, offset: 0, loading: false, summary: null });
        setImageBatches(batchList.batches || []);
        setPromptArtifacts(artifactList.artifacts || []);
        setSeriesPlan(null);
        onStatus?.({ kind: "ready", message: "无限画布已就绪" });
      }
    } catch (error) {
      if (!isCancelled()) {
        onStatus?.({ kind: "failed", message: error?.message || "无限画布加载失败" });
      }
    } finally {
      if (!isCancelled()) {
        setLoading(false);
      }
    }
  }

  async function refreshCanvasArtifacts() {
    if (!canvas?.id) {
      return;
    }
    const [detail, batchList, artifactList] = await Promise.all([
      fetchCanvas(canvas.id),
      fetchCanvasImageBatches(canvas.id),
      fetchCanvasPromptArtifacts(canvas.id, { limit: 100 }),
    ]);
    setCanvas(detail);
    setImageBatches(batchList.batches || []);
    setPromptArtifacts(artifactList.artifacts || []);
  }

  async function loadBranchOperations(filters = {}) {
    if (!canvas?.id) {
      return null;
    }
    const requestCanvasId = canvas.id;
    const nextFilters = { ...branchOperationFilters, ...filters, limit: filters.limit || branchOperationFilters.limit || 40 };
    const requestId = branchOperationRequestRef.current + 1;
    branchOperationRequestRef.current = requestId;
    setBranchOperationFilters(nextFilters);
    setBranchOperationPage((current) => ({ ...current, loading: true }));
    try {
      const page = await fetchCanvasBranchOperations(requestCanvasId, nextFilters);
      if (branchOperationRequestRef.current !== requestId || latestCanvasIdRef.current !== requestCanvasId) {
        return page;
      }
      setBranchOperationPage({ operations: page.operations || [], total: page.total || 0, limit: page.limit || nextFilters.limit || 40, offset: page.offset || 0, loading: false, summary: page.summary || null });
      return page;
    } catch (error) {
      if (branchOperationRequestRef.current === requestId && latestCanvasIdRef.current === requestCanvasId) {
        setBranchOperationPage((current) => ({ ...current, loading: false }));
        onStatus?.({ kind: "failed", message: error?.message || "治理记录加载失败" });
      }
      return null;
    }
  }

  async function addBriefNode() {
    const text = brief.trim();
    if (!text || !canvas || creating) {
      return;
    }
    setCreating(true);
    try {
      const node = await createCanvasNode(canvas.id, {
        type: "brief",
        title: text.slice(0, 36),
        position: canvasPoint(140, 120, view),
        size: NODE_SIZE,
        payload: { prompt: text, role: "creative_brief" },
      });
      setCanvas((current) => (current ? { ...current, nodes: [...current.nodes, node] } : current));
      setSelectedNodeId(node.id);
      setSeriesPlan(null);
      setBrief("");
      onStatus?.({ kind: "ready", message: "创意简报已放入画布" });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "创建画布节点失败" });
    } finally {
      setCreating(false);
    }
  }

  async function addStoryboardNode() {
    const text = brief.trim();
    if (!text || !canvas || creating) {
      return;
    }
    setCreating(true);
    try {
      const node = await createCanvasNode(canvas.id, {
        type: "storyboard",
        title: text.slice(0, 36),
        position: canvasPoint(220, 220, view),
        size: SEMANTIC_NODE_SIZE,
        payload: {
          role: "storyboard",
          prompt: text,
          scene: text,
          camera: "slow controlled camera move",
          camera_motion: "slow dolly in",
          subject_action: "subject remains stable with subtle premium motion",
          shot_size: "medium close-up",
          temporal_rhythm: "calm commercial pacing",
          ending_state: "clean hero frame",
          duration: "5",
          aspect_ratio: "16:9",
        },
      });
      setCanvas((current) => (current ? { ...current, nodes: [...current.nodes, node] } : current));
      setBrief("");
      setSelectedNodeId(node.id);
      onStatus?.({ kind: "ready", message: "分镜节点已加入画布" });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "分镜节点创建失败" });
    } finally {
      setCreating(false);
    }
  }

  function promptProgramPayload(prompt, referenceNodes, sourceNodeIds) {
    const mentions = referenceNodes.map((node) => node.payload?.mention_label).filter(Boolean);
    const referencePolicy = mentions.length ? `引用 ${mentions.map((label) => `@${label}`).join("、")}，按各自 reference_role 控制身份、风格、构图或运动。` : "没有显式 @资产引用时，以 brief 和语义规格为准。";
    return {
      role: "prompt_program",
      profile: "professional_design",
      prompt,
      subject_block: `主体：${prompt}`,
      scene_block: "场景：明确环境、时段、空间层次、叙事目标和设计用途。",
      composition_block: "构图：明确景别、机位、主体占比、前中后景、留白和视觉动线。",
      lighting_block: "光线：明确主光方向、反差、色温、材质高光、反射与氛围光。",
      camera_block: "镜头：明确焦段、视角、景深、动态感和商业影像质感。",
      negative_prompt: "避免低清晰度、主体漂移、廉价滤镜、过度锐化、文字乱码、风格不一致。",
      reference_instruction: referencePolicy,
      referenced_asset_ids: referenceNodes.map((node) => node.payload.asset_id).filter(Boolean),
      referenced_asset_mentions: mentions,
      source_node_ids: sourceNodeIds,
      workflow: "prompt_program_phase_2",
    };
  }

  async function materializeSemanticSkeleton() {
    if (!canvas || creatingSemanticSkeleton) {
      return;
    }
    const anchorNode = selectedNode?.type === "brief" ? selectedNode : canvas.nodes.find((node) => node.type === "brief");
    if (!anchorNode) {
      onStatus?.({ kind: "failed", message: "请先把创意简报放入画布，再初始化语义生产骨架" });
      return;
    }
    setCreatingSemanticSkeleton(true);
    onStatus?.({ kind: "loading", message: "正在创建 LMM 语义生产骨架" });
    const createdNodes = [];
    const createdEdges = [];
    const nodesByType = {};
    try {
      for (const template of SEMANTIC_SKELETON_NODES) {
        const node = await createCanvasNode(canvas.id, {
          type: template.type,
          title: template.title,
          position: { x: anchorNode.position.x + template.offset.x, y: anchorNode.position.y + template.offset.y },
          size: template.size,
          payload: {
            ...template.payload,
            source_node_ids: [anchorNode.id],
            source_canvas_id: canvas.id,
            workflow: "semantic_canvas_phase_1",
          },
        });
        createdNodes.push(node);
        nodesByType[template.type] = node;
      }
      for (const node of createdNodes.filter((item) => item.type === "semantic_spec")) {
        const edge = await createCanvasEdge(canvas.id, {
          source_node_id: anchorNode.id,
          target_node_id: node.id,
          type: "semantic_analysis",
          payload: { workflow: "semantic_canvas_phase_1" },
        });
        createdEdges.push(edge);
      }
      for (const [sourceType, targetType, edgeType] of SEMANTIC_SKELETON_EDGES) {
        const source = nodesByType[sourceType];
        const target = nodesByType[targetType];
        if (!source || !target) {
          continue;
        }
        const edge = await createCanvasEdge(canvas.id, {
          source_node_id: source.id,
          target_node_id: target.id,
          type: edgeType,
          payload: { workflow: "semantic_canvas_phase_1" },
        });
        createdEdges.push(edge);
      }
      setCanvas((current) => (current ? { ...current, nodes: [...current.nodes, ...createdNodes], edges: [...current.edges, ...createdEdges] } : current));
      setSelectedNodeId(nodesByType.semantic_spec?.id || createdNodes[0]?.id || anchorNode.id);
      setFinalSubmission(null);
      onStatus?.({ kind: "ready", message: "LMM 语义生产骨架已写入画布" });
    } catch (error) {
      if (createdNodes.length) {
        await Promise.allSettled(createdNodes.map((node) => deleteCanvasNode(canvas.id, node.id)));
        await loadCanvas();
      }
      onStatus?.({ kind: "failed", message: error?.message || "创建语义生产骨架失败" });
    } finally {
      setCreatingSemanticSkeleton(false);
    }
  }

  async function createPromptProgramFromSelection() {
    if (!canvas || creatingPromptProgram || !selectedSourceIds.length) {
      return;
    }
    setCreatingPromptProgram(true);
    onStatus?.({ kind: "loading", message: "正在从当前图谱生成 Prompt Program" });
    const sourceNodes = canvas.nodes.filter((node) => selectedSourceIds.includes(node.id));
    const anchorNode = selectedNode || sourceNodes[0];
    const prompt = sourceNodes.find((node) => node.payload?.prompt)?.payload?.prompt || sourceNodes.find((node) => node.payload?.goal)?.payload?.goal || "专业图片生成 Prompt Program";
    const referenceNodes = sourceNodes.filter((node) => node.payload?.asset_id);
    let createdNode = null;
    try {
      const node = await createCanvasNode(canvas.id, {
        type: "prompt_program",
        title: "Prompt Program",
        position: { x: (anchorNode?.position?.x || 0) + 420, y: anchorNode?.position?.y || 0 },
        size: { width: 360, height: 230 },
        payload: promptProgramPayload(prompt, referenceNodes, selectedSourceIds),
      });
      createdNode = node;
      const edges = [];
      for (const sourceNodeId of selectedSourceIds) {
        const edge = await createCanvasEdge(canvas.id, {
          source_node_id: sourceNodeId,
          target_node_id: node.id,
          type: "compiled_to_prompt",
          payload: { workflow: "prompt_program_phase_2" },
        });
        edges.push(edge);
      }
      setCanvas((current) => (current ? { ...current, nodes: [...current.nodes, node], edges: [...current.edges, ...edges] } : current));
      setSelectedNodeId(node.id);
      setFinalSubmission(null);
      onStatus?.({ kind: "ready", message: "Prompt Program 已写入画布，可在 Inspector 中编辑" });
    } catch (error) {
      if (createdNode) {
        await Promise.allSettled([deleteCanvasNode(canvas.id, createdNode.id)]);
        await loadCanvas();
      }
      onStatus?.({ kind: "failed", message: error?.message || "创建 Prompt Program 失败" });
    } finally {
      setCreatingPromptProgram(false);
    }
  }

  async function optimizeStoryboardImagePrompt(node = selectedNode) {
    if (!canvas || !node || optimizingPromptNodeId) {
      return;
    }
    const sourceIds = selectedSourceNodeIds(canvas, node.id);
    setOptimizingPromptNodeId(node.id);
    try {
      const response = await optimizeCanvasImagePrompt(canvas.id, {
        node_id: node.id,
        selected_node_ids: sourceIds.length ? sourceIds : [node.id],
        root_node_id: node.id,
        params: { size: "1024x1024", quality: "high" },
        skip_prompt_evaluation: false,
      });
      setPromptArtifacts((current) => [response.artifact, ...current.filter((artifact) => artifact.id !== response.artifact.id)]);
      // Production media payloads are immutable on the backend; prompt artifacts remain available through artifact history.
      if (!isServerManagedMediaNode(node)) {
        const nextPayload = { ...node.payload, prompt_artifact_id: response.artifact.id, final_prompt: response.final_prompt };
        const updated = await updateCanvasNode(canvas.id, node.id, { payload: nextPayload });
        setCanvas((current) => (current ? { ...current, nodes: current.nodes.map((item) => (item.id === updated.id ? updated : item)) } : current));
      }
      onStatus?.({ kind: "ready", message: "图像 Prompt 已优化并保存版本" });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "图像 Prompt 优化失败" });
    } finally {
      setOptimizingPromptNodeId("");
    }
  }

  async function optimizeStoryboardVideoPrompt(node = selectedNode, sourceCandidate = videoDialogCandidate) {
    if (!canvas || !node || optimizingVideoPromptNodeId) {
      return;
    }
    const sourceIds = selectedSourceNodeIds(canvas, node.id);
    const selectedNodeIds = sourceIds.length ? sourceIds : [node.id];
    setOptimizingVideoPromptNodeId(node.id);
    try {
      const response = await optimizeCanvasVideoPrompt(canvas.id, {
        node_id: node.id,
        selected_node_ids: selectedNodeIds,
        root_node_id: videoPromptRootNodeId(canvas, node, selectedNodeIds),
        source_candidate_id: sourceCandidate?.id || undefined,
        duration: VIDEO_DEFAULTS.duration,
        aspect_ratio: VIDEO_DEFAULTS.aspectRatio,
        params: {},
      });
      setPromptArtifacts((current) => [response.artifact, ...current.filter((artifact) => artifact.id !== response.artifact.id)]);
      // Production media payloads are immutable on the backend; prompt artifacts remain available through artifact history.
      if (!isServerManagedMediaNode(node)) {
        const nextPayload = { ...node.payload, video_prompt_artifact_id: response.artifact.id, motion_prompt: response.final_prompt };
        const updated = await updateCanvasNode(canvas.id, node.id, { payload: nextPayload });
        setCanvas((current) => (current ? { ...current, nodes: current.nodes.map((item) => (item.id === updated.id ? updated : item)) } : current));
      }
      setVideoPrompt(response.final_prompt);
      setVideoPromptArtifactId(response.artifact.id);
      onStatus?.({ kind: "ready", message: "视频 Prompt 已优化并保存版本" });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "视频 Prompt 优化失败" });
    } finally {
      setOptimizingVideoPromptNodeId("");
    }
  }

  function latestNodePromptArtifact(artifacts, nodeId, kind) {
    return (Array.isArray(artifacts) ? artifacts : []).find((artifact) => artifact.node_id === nodeId && artifact.kind === kind) || null;
  }

  function isServerManagedMediaNode(node) {
    return SERVER_MANAGED_MEDIA_NODE_TYPES.has(node?.type);
  }

  function artifactPrompt(artifact) {
    return artifact?.payload?.final_prompt || artifact?.payload?.compiled_prompt || "";
  }

  async function updatePromptProgramNode(node, draft) {
    if (!canvas || !node || updatingPromptProgram) {
      return;
    }
    setUpdatingPromptProgram(true);
    try {
      const updated = await updateCanvasNode(canvas.id, node.id, {
        payload: {
          ...node.payload,
          ...draft,
          workflow: node.payload?.workflow || "prompt_program_phase_2",
        },
      });
      setCanvas((current) => (current ? { ...current, nodes: current.nodes.map((item) => (item.id === updated.id ? updated : item)) } : current));
      setFinalSubmission(null);
      onStatus?.({ kind: "ready", message: "Prompt Program 已保存" });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "保存 Prompt Program 失败" });
    } finally {
      setUpdatingPromptProgram(false);
    }
  }

  function mentionMenuFor(value, cursorIndex) {
    const query = extractMentionQuery(value, cursorIndex);
    if (!query) {
      return null;
    }
    const options = mentionOptions
      .filter((option) => {
        const label = option.mentionLabel.toLowerCase();
        const name = assetLabel(option.asset, assetKindLabel(option.asset)).toLowerCase();
        return label.includes(query.query) || name.includes(query.query);
      })
      .slice(0, 6);
    return options.length ? { ...query, options } : null;
  }

  function updateMentionMenu(value, cursorIndex) {
    setMentionMenu(mentionMenuFor(value, cursorIndex));
    setActiveMentionIndex(0);
  }

  function handleBriefChange(event) {
    const value = event.target.value;
    setBrief(value);
    setFinalSubmission(null);
    updateMentionMenu(value, event.target.selectionStart || value.length);
  }

  function handleBriefCursor(event) {
    updateMentionMenu(event.target.value, event.target.selectionStart || event.target.value.length);
  }

  function handleBriefKeyDown(event) {
    const menu = mentionMenu || mentionMenuFor(event.currentTarget.value, event.currentTarget.selectionStart || event.currentTarget.value.length);
    if (!menu?.options?.length) {
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setMentionMenu(menu);
      setActiveMentionIndex((current) => Math.min(current + 1, menu.options.length - 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setMentionMenu(menu);
      setActiveMentionIndex((current) => Math.max(current - 1, 0));
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setMentionMenu(null);
      setActiveMentionIndex(0);
      return;
    }
    if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      const index = Math.min(activeMentionIndex, menu.options.length - 1);
      selectMentionOption(menu.options[index], menu, event.currentTarget.value);
    }
  }

  async function selectMentionOption(option, menu = mentionMenu, value = brief) {
    if (!canvas || creating || !menu) {
      return;
    }
    const next = replaceMentionToken(value, menu, option.mentionLabel);
    setBrief(next.value);
    setMentionMenu(null);
    window.requestAnimationFrame(() => {
      const textarea = briefTextareaRef.current?.resizableTextArea?.textArea || briefTextareaRef.current;
      textarea?.focus?.();
      textarea?.setSelectionRange?.(next.cursorIndex, next.cursorIndex);
    });
    const existing = findCanvasAssetNodeByMention(canvas.nodes, option.mentionLabel);
    if (existing) {
      setSelectedNodeId(existing.id);
      onStatus?.({ kind: "ready", message: `已复用 @${option.mentionLabel} 文件引用` });
      return;
    }
    setCreating(true);
    try {
      const { roleMeta } = await createAssetReferenceNode(option.asset, option.mentionLabel);
      onStatus?.({ kind: "ready", message: `@${option.mentionLabel} 已作为${roleMeta.label}参考放入画布` });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "创建 @文件引用失败" });
    } finally {
      setCreating(false);
    }
  }

  async function planSeries() {
    if (!canvas || planningSeries || materializingSeries || !selectedSourceIds.length) {
      return;
    }
    setPlanningSeries(true);
    onStatus?.({ kind: "loading", message: "系列导演正在规划角色、风格和分镜" });
    try {
      const plan = await planCanvasSeries(canvas.id, { selected_node_ids: selectedSourceIds, frame_count: 4, profile: "campaign_series" });
      setSeriesPlan(plan);
      onStatus?.({ kind: "ready", message: `系列方案已生成：${plan.frames?.length || 0} 个分镜` });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "系列方案生成失败" });
    } finally {
      setPlanningSeries(false);
    }
  }

  function repairVersionOrigin(nodes) {
    const bounds = canvasBounds(nodes);
    return { x: bounds.maxX + 140, y: bounds.minY + 40 };
  }

  function repairVersionIteration(context) {
    const iteration = Number(context?.repairFocus?.iteration);
    return Number.isFinite(iteration) ? iteration : 1;
  }

  function existingRepairVersionNodes() {
    return new Map((canvas?.nodes || []).filter((node) => node.type === "repair_version" && node.payload?.batch_id).map((node) => [node.payload.batch_id, node]));
  }

  async function materializeRepairVersionGraph() {
    if (!canvas || materializingRepairGraph) {
      return;
    }
    const repairVersions = imageBatches.map((batch) => ({ batch, context: repairBatchContext(batch) })).filter((item) => item.context);
    if (!repairVersions.length) {
      onStatus?.({ kind: "failed", message: "还没有可物化的修复版本" });
      return;
    }
    const existingByBatchId = existingRepairVersionNodes();
    const pendingVersions = repairVersions.filter(({ batch }) => !existingByBatchId.has(batch.id)).sort((left, right) => repairVersionIteration(left.context) - repairVersionIteration(right.context));
    if (!pendingVersions.length) {
      onStatus?.({ kind: "ready", message: "修复版本图谱已是最新" });
      return;
    }
    setMaterializingRepairGraph(true);
    const origin = repairVersionOrigin(canvas.nodes);
    const createdNodes = [];
    const versionNodesByBatchId = new Map(existingByBatchId);
    try {
      let latestCanvas = canvas;
      for (const { batch } of pendingVersions) {
        latestCanvas = await materializeCanvasRepairVersion(canvas.id, {
          batch_id: batch.id,
          position: { x: origin.x, y: origin.y + versionNodesByBatchId.size * REPAIR_VERSION_VERTICAL_GAP },
          size: REPAIR_VERSION_NODE_SIZE,
        });
        const node = latestCanvas.nodes.find((item) => item.type === "repair_version" && item.payload?.batch_id === batch.id);
        if (node) {
          createdNodes.push(node);
          versionNodesByBatchId.set(batch.id, node);
        }
      }
      setCanvas(latestCanvas);
      setSelectedNodeId(createdNodes[0]?.id || selectedNodeId);
      setFinalSubmission(null);
      onStatus?.({ kind: "ready", message: `修复版本图谱已写入画布：${createdNodes.length} 个版本节点` });
    } catch (error) {
      await loadCanvas();
      onStatus?.({ kind: "failed", message: error?.message || "创建修复版本图谱失败" });
    } finally {
      setMaterializingRepairGraph(false);
    }
  }

  function repairVersionLayoutPositions() {
    const repairNodes = (canvas?.nodes || []).filter((node) => node.type === "repair_version" && node.payload?.batch_id);
    if (!repairNodes.length) {
      return [];
    }
    const contextByBatchId = new Map(imageBatches.map((batch) => [batch.id, repairBatchContext(batch)]).filter(([, context]) => context));
    const nodeByBatchId = new Map(repairNodes.map((node) => [node.payload.batch_id, node]));
    const childrenByBatchId = new Map();
    const roots = [];
    for (const node of repairNodes) {
      const batchId = node.payload.batch_id;
      const context = contextByBatchId.get(batchId);
      const parentBatchId = context?.repairFocus?.parent_batch_id || node.payload.repair_parent_batch_id || "";
      if (parentBatchId && nodeByBatchId.has(parentBatchId)) {
        childrenByBatchId.set(parentBatchId, [...(childrenByBatchId.get(parentBatchId) || []), batchId]);
      } else {
        roots.push(batchId);
      }
    }
    const byIteration = (left, right) => repairVersionIteration(contextByBatchId.get(left)) - repairVersionIteration(contextByBatchId.get(right));
    roots.sort(byIteration);
    for (const children of childrenByBatchId.values()) {
      children.sort(byIteration);
    }
    const minX = Math.min(...repairNodes.map((node) => node.position.x));
    const minY = Math.min(...repairNodes.map((node) => node.position.y));
    const positionsById = new Map();
    let leafIndex = 0;
    function place(batchId, depth, path = new Set()) {
      const node = nodeByBatchId.get(batchId);
      if (!node) {
        return minY;
      }
      const existing = positionsById.get(node.id);
      if (existing) {
        return existing.position.y;
      }
      if (path.has(batchId)) {
        const y = minY + leafIndex++ * REPAIR_VERSION_VERTICAL_GAP;
        positionsById.set(node.id, { id: node.id, position: { x: minX + depth * REPAIR_VERSION_HORIZONTAL_GAP, y } });
        return y;
      }
      const nextPath = new Set(path);
      nextPath.add(batchId);
      const children = childrenByBatchId.get(batchId) || [];
      const childYs = children.map((childBatchId) => place(childBatchId, depth + 1, nextPath));
      const y = childYs.length ? childYs.reduce((sum, value) => sum + value, 0) / childYs.length : minY + leafIndex++ * REPAIR_VERSION_VERTICAL_GAP;
      positionsById.set(node.id, { id: node.id, position: { x: minX + depth * REPAIR_VERSION_HORIZONTAL_GAP, y } });
      return y;
    }
    roots.forEach((batchId) => place(batchId, 0));
    for (const batchId of nodeByBatchId.keys()) {
      const node = nodeByBatchId.get(batchId);
      if (node && !positionsById.has(node.id)) {
        place(batchId, 0);
      }
    }
    return [...positionsById.values()];
  }

  async function layoutRepairVersionGraph() {
    if (!canvas || layingOutRepairGraph) {
      return;
    }
    const positions = repairVersionLayoutPositions();
    if (!positions.length) {
      onStatus?.({ kind: "failed", message: "还没有可布局的修复版本节点" });
      return;
    }
    setLayingOutRepairGraph(true);
    try {
      const nodes = await updateCanvasNodePositions(canvas.id, positions);
      const updatedById = new Map(nodes.nodes?.map((node) => [node.id, node]) || []);
      setCanvas((current) => (current ? { ...current, nodes: current.nodes.map((node) => updatedById.get(node.id) || node) } : current));
      setFinalSubmission(null);
      onStatus?.({ kind: "ready", message: `修复版本分支已重新布局：${positions.length} 个节点` });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "修复版本分支布局失败" });
    } finally {
      setLayingOutRepairGraph(false);
    }
  }

  function repairVersionDescendants(node) {
    const nodesByBatchId = new Map((canvas?.nodes || []).filter((item) => item.type === "repair_version" && item.payload?.batch_id).map((item) => [item.payload.batch_id, item]));
    const childrenByBatchId = new Map();
    for (const item of nodesByBatchId.values()) {
      const parentBatchId = item.payload?.repair_parent_batch_id;
      if (parentBatchId) {
        childrenByBatchId.set(parentBatchId, [...(childrenByBatchId.get(parentBatchId) || []), item]);
      }
    }
    const descendants = [];
    const queue = [...(childrenByBatchId.get(node.payload?.batch_id) || [])];
    const seen = new Set([node.id]);
    while (queue.length) {
      const child = queue.shift();
      if (!child || seen.has(child.id)) {
        continue;
      }
      seen.add(child.id);
      descendants.push(child);
      queue.push(...(childrenByBatchId.get(child.payload?.batch_id) || []));
    }
    return descendants;
  }

  function repairVersionAncestors(node) {
    const nodesByBatchId = new Map((canvas?.nodes || []).filter((item) => item.type === "repair_version" && item.payload?.batch_id).map((item) => [item.payload.batch_id, item]));
    const ancestors = [];
    const seen = new Set([node.id]);
    let parentBatchId = node.payload?.repair_parent_batch_id || "";
    while (parentBatchId) {
      const parent = nodesByBatchId.get(parentBatchId);
      if (!parent || seen.has(parent.id)) {
        break;
      }
      seen.add(parent.id);
      ancestors.unshift(parent);
      parentBatchId = parent.payload?.repair_parent_batch_id || "";
    }
    return ancestors;
  }

  function branchOperationPreview(node, operation, includeDescendants = false) {
    if (operation === "pin") {
      return [repairVersionAncestors(node), [node]].flat();
    }
    if (operation === "unpin") {
      return [node];
    }
    return includeDescendants ? [node, ...repairVersionDescendants(node)] : [node];
  }

  function defaultBranchOperationReason(operation, includeDescendants = false) {
    if (operation === "pin") {
      return "Designer pinned primary production path after reviewing branch quality and delivery intent";
    }
    if (operation === "unpin") {
      return "Designer unpinned primary production path after governance review";
    }
    if (operation === "restore") {
      return includeDescendants ? "Designer restored repair subtree after governance review" : "Designer restored repair branch after governance review";
    }
    return includeDescendants ? "Designer archived repair subtree after governance review" : "Designer archived repair branch after governance review";
  }

  function openBranchOperationDialog(node, operation, options = {}) {
    if (!node || node.type !== "repair_version") {
      return;
    }
    const includeDescendants = Boolean(options.includeDescendants);
    const affectedNodes = branchOperationPreview(node, operation, includeDescendants);
    dialogReturnFocusRef.current = document.activeElement;
    setBranchOperationDialog({
      node,
      operation,
      nextStatus: operation === "restore" ? "active" : operation === "archive" ? "archived" : "active",
      includeDescendants,
      affectedNodes,
      reason: options.reason || defaultBranchOperationReason(operation, includeDescendants),
    });
  }

  function closeBranchOperationDialog() {
    setBranchOperationDialog(null);
    restoreDialogFocus(dialogReturnFocusRef);
  }

  function setBranchOperationReason(reason) {
    setBranchOperationDialog((current) => (current ? { ...current, reason } : current));
  }

  async function submitBranchOperationDialog() {
    if (!branchOperationDialog || branchOperationSubmitting) {
      return;
    }
    setBranchOperationSubmitting(true);
    try {
      const { node, operation, nextStatus, includeDescendants, reason } = branchOperationDialog;
      const ok = operation === "pin"
        ? await pinRepairVersionPath(node, { reason })
        : operation === "unpin"
          ? await unpinRepairVersionPath(node, { reason })
          : await setRepairVersionArchiveStatus(node, nextStatus, { includeDescendants, reason });
      if (ok) {
        closeBranchOperationDialog();
      }
    } finally {
      setBranchOperationSubmitting(false);
    }
  }

  async function setRepairVersionArchiveStatus(node, nextStatus, options = {}) {
    if (!canvas || !node || node.type !== "repair_version" || !["active", "archived"].includes(nextStatus)) {
      return false;
    }
    const requestCanvasId = canvas.id;
    const includeDescendants = Boolean(options.includeDescendants);
    if (!includeDescendants && node.payload?.status === nextStatus) {
      return false;
    }
    try {
      const response = await setCanvasRepairVersionStatus(requestCanvasId, node.id, nextStatus, {
        include_descendants: includeDescendants,
        reason: options.reason || (nextStatus === "archived" ? "Designer archived repair branch from canvas" : "Designer restored repair branch from canvas"),
      });
      const updatedNodes = response.nodes || [response];
      const updatedById = new Map(updatedNodes.map((item) => [item.id, item]));
      const latestCanvas = await fetchCanvas(requestCanvasId);
      if (latestCanvasIdRef.current !== requestCanvasId) {
        return false;
      }
      setCanvas((current) => (latestCanvas || (current ? { ...current, nodes: current.nodes.map((item) => updatedById.get(item.id) || item) } : current)));
      await loadBranchOperations({ ...branchOperationFilters, offset: 0 });
      setFinalSubmission(null);
      const scope = includeDescendants ? "子树" : "分支";
      onStatus?.({ kind: "ready", message: nextStatus === "archived" ? `修复${scope}已归档，原始节点和 lineage 未被删除` : `修复${scope}已恢复为 active` });
      return true;
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "更新修复分支状态失败" });
      return false;
    }
  }

  async function pinRepairVersionPath(node, options = {}) {
    if (!canvas || !node || node.type !== "repair_version") {
      return false;
    }
    const requestCanvasId = canvas.id;
    try {
      const response = await pinCanvasRepairVersion(requestCanvasId, node.id, { reason: options.reason || defaultBranchOperationReason("pin") });
      const updatedNodes = response.nodes || [response];
      const updatedById = new Map(updatedNodes.map((item) => [item.id, item]));
      const latestCanvas = await fetchCanvas(requestCanvasId);
      if (latestCanvasIdRef.current !== requestCanvasId) {
        return false;
      }
      setCanvas((current) => (latestCanvas || (current ? { ...current, nodes: current.nodes.map((item) => updatedById.get(item.id) || item) } : current)));
      await loadBranchOperations({ ...branchOperationFilters, offset: 0 });
      setFinalSubmission(null);
      onStatus?.({ kind: "ready", message: "主生产路径已固定，Final JSON 会优先使用该 active 链路" });
      return true;
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "固定主生产路径失败" });
      return false;
    }
  }

  async function unpinRepairVersionPath(node, options = {}) {
    if (!canvas || !node || node.type !== "repair_version") {
      return false;
    }
    const requestCanvasId = canvas.id;
    try {
      const response = await unpinCanvasRepairVersion(requestCanvasId, node.id, { reason: options.reason || defaultBranchOperationReason("unpin") });
      const updatedNodes = response.nodes || [response];
      const updatedById = new Map(updatedNodes.map((item) => [item.id, item]));
      const latestCanvas = await fetchCanvas(requestCanvasId);
      if (latestCanvasIdRef.current !== requestCanvasId) {
        return false;
      }
      setCanvas((current) => (latestCanvas || (current ? { ...current, nodes: current.nodes.map((item) => updatedById.get(item.id) || item) } : current)));
      await loadBranchOperations({ ...branchOperationFilters, offset: 0 });
      setFinalSubmission(null);
      onStatus?.({ kind: "ready", message: "主生产路径已取消固定，Final JSON 会回到 active 链路评估" });
      return true;
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "取消主生产路径失败" });
      return false;
    }
  }

  function focusRepairVersionNode(node) {
    if (!node) {
      return;
    }
    setSelectedNodeId(node.id);
    if (!stageRef.current) {
      return;
    }
    const viewport = stageRef.current.getBoundingClientRect();
    setView((current) => ({
      ...current,
      x: viewport.width / 2 - (node.position.x + node.size.width / 2) * current.scale,
      y: viewport.height / 2 - (node.position.y + node.size.height / 2) * current.scale,
    }));
  }

  async function materializeSeriesFrames() {
    if (!canvas || !seriesPlan?.frames?.length || materializingSeries || planningSeries) {
      return;
    }
    setMaterializingSeries(true);
    const origin = seriesFrameOrigin(canvas.nodes, view);
    const createdNodes = [];
    const createdEdges = [];
    try {
      for (const frame of seriesPlan.frames) {
        const node = await createCanvasNode(canvas.id, {
          type: "series_frame",
          title: frame.title,
          position: { x: origin.x, y: origin.y + (frame.index - 1) * SERIES_FRAME_VERTICAL_GAP },
          size: SERIES_FRAME_SIZE,
          payload: seriesFramePayload(frame, seriesPlan),
        });
        createdNodes.push(node);
        for (const sourceNodeId of frame.source_node_ids || []) {
          const edge = await createCanvasEdge(canvas.id, {
            source_node_id: sourceNodeId,
            target_node_id: node.id,
            type: "series_lineage",
            payload: { role: "series_source", frame_index: frame.index },
          });
          createdEdges.push(edge);
        }
      }
      setCanvas((current) => (current ? { ...current, nodes: [...current.nodes, ...createdNodes], edges: [...current.edges, ...createdEdges] } : current));
      setSelectedNodeId(createdNodes[0]?.id || selectedNodeId);
      setSeriesPlan(null);
      setFinalSubmission(null);
      onStatus?.({ kind: "ready", message: "系列分镜已放回无限画布" });
    } catch (error) {
      if (createdNodes.length) {
        await Promise.allSettled(createdNodes.map((node) => deleteCanvasNode(canvas.id, node.id)));
        await loadCanvas();
      }
      onStatus?.({ kind: "failed", message: error?.message || "创建系列分镜节点失败" });
    } finally {
      setMaterializingSeries(false);
    }
  }

  function openImageBatchDialog() {
    if (!selectedSourceNodeCount) {
      onStatus?.({ kind: "failed", message: "请先选择一个简报、参考资产或已选图像节点" });
      return;
    }
    dialogReturnFocusRef.current = document.activeElement;
    setBatchDialogOpen(true);
  }

  function closeImageBatchDialog() {
    setBatchDialogOpen(false);
    restoreDialogFocus(dialogReturnFocusRef);
  }

  async function createImageBatchFromSelection() {
    if (!canvas || creatingBatch || !selectedSourceIds.length) {
      return;
    }
    setCreatingBatch(true);
    onStatus?.({ kind: "loading", message: "正在从当前画布图谱生成多张候选图" });
    const promptArtifactId = selectedNode?.payload?.prompt_artifact_id;
    try {
      const batch = await createCanvasImageBatch(canvas.id, {
        selected_node_ids: selectedSourceIds,
        root_node_id: selectedNode?.id || selectedSourceIds[0],
        prompt_artifact_id: promptArtifactId || undefined,
        model: "openai",
        threshold: 0,
        max_iter: 1,
        skip_prompt_evaluation: true,
        params: { n: batchSettings.count, size: batchSettings.size, quality: batchSettings.quality },
      });
      setImageBatches((current) => [batch, ...current.filter((item) => item.id !== batch.id)]);
      closeImageBatchDialog();
      setFinalSubmission(null);
      onStatus?.({ kind: "ready", message: `图片批次已创建，正在生成 ${batchSettings.count} 张候选图` });
      await onComplete?.();
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "图片批次创建失败" });
    } finally {
      setCreatingBatch(false);
    }
  }

  async function createRepairImageBatchFromNode(node = selectedNode) {
    if (!canvas || creatingRepairBatch || !node || node.type !== "prompt_program" || node.payload?.workflow !== "evaluation_repair_phase_4") {
      return;
    }
    const sourceNodeIds = selectedSourceNodeIds(canvas, node.id);
    if (!sourceNodeIds.length) {
      onStatus?.({ kind: "failed", message: "修复 Prompt Program 没有可用的源图谱" });
      return;
    }
    setCreatingRepairBatch(true);
    onStatus?.({ kind: "loading", message: "正在从修复 Prompt Program 生成新候选图" });
    try {
      const batch = await createCanvasImageBatch(canvas.id, {
        selected_node_ids: sourceNodeIds,
        root_node_id: node.id,
        prompt_artifact_id: node.payload?.prompt_artifact_id || undefined,
        model: "openai",
        threshold: 0,
        max_iter: 1,
        skip_prompt_evaluation: true,
        params: { n: 2, size: IMAGE_BATCH_DEFAULTS.size, quality: IMAGE_BATCH_DEFAULTS.quality },
      });
      setImageBatches((current) => [batch, ...current.filter((item) => item.id !== batch.id)]);
      setFinalSubmission(null);
      await onComplete?.();
      onStatus?.({ kind: "ready", message: "修复候选图批次已创建" });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "修复候选图批次创建失败" });
    } finally {
      setCreatingRepairBatch(false);
    }
  }

  async function refreshBatchesFromButton() {
    if (!canvas?.id) {
      return;
    }
    try {
      await refreshCanvasArtifacts();
      await onComplete?.();
      onStatus?.({ kind: "ready", message: "画布生产结果已刷新" });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "画布生产结果刷新失败" });
    }
  }

  function candidateEvaluationPayload(candidate, repairFocus = null) {
    const evaluation = candidate.metadata?.evaluation || {};
    const dimensions = Array.isArray(evaluation.dimensions)
      ? evaluation.dimensions.map((item) => `${item.label || item.key}: ${formatCandidateScore(item.score)}`).slice(0, 8)
      : [];
    const baseRepairTargets = Array.isArray(evaluation.repair_targets) ? evaluation.repair_targets.map(String).slice(0, 8) : [];
    const focusInstruction = repairFocusInstruction(repairFocus);
    return {
      dimensions,
      repairTargets: focusInstruction ? [focusInstruction, ...baseRepairTargets].slice(0, 8) : baseRepairTargets,
      suggestion: focusInstruction || evaluation.suggestion || "",
      optimizationPrompt: focusInstruction ? `${focusInstruction}。${evaluation.optimization_prompt || candidate.prompt || "保持其他已经改善的维度稳定。"}` : evaluation.optimization_prompt || candidate.prompt || "",
      totalScore: Number.isFinite(Number(evaluation.total_score)) ? Number(evaluation.total_score) : candidate.score,
    };
  }

  function repairFocusInstruction(repairFocus) {
    if (!repairFocus) {
      return "";
    }
    const label = repairFocus.label || repairFocus.key || "目标维度";
    const baseline = formatCandidateScore(repairFocus.baseline_score);
    const current = formatCandidateScore(repairFocus.score);
    const delta = Number.isFinite(Number(repairFocus.delta)) ? Number(repairFocus.delta).toFixed(1) : "未变化";
    return `定向修复「${label}」维度：从 ${baseline} 到 ${current}，变化 ${delta}，下一轮只强化这个维度并保持其他维度稳定`;
  }

  function formatCandidateScore(score) {
    return Number.isFinite(Number(score)) ? Number(score).toFixed(1) : "未评分";
  }

  function repairPromptProgramPayload(candidate, evaluationNodeId, batch, repairFocus = null) {
    const evaluation = candidateEvaluationPayload(candidate, repairFocus);
    const repairInstruction = evaluation.optimizationPrompt || evaluation.repairTargets.join("；") || candidate.prompt;
    const parentIteration = Number(batch?.repair_context?.repair_focus?.iteration || 0);
    return {
      role: "prompt_program",
      profile: "professional_design_repair",
      prompt: repairInstruction,
      subject_block: `基于候选图 #${candidate.index + 1} 的主体继续优化，保持已成立的主体身份、材质和画面意图。`,
      scene_block: "只调整评分中暴露的问题，不重写已经成立的场景与视觉方向。",
      composition_block: repairInstruction,
      lighting_block: "根据评价结果修复光影、材质高光、反差和高级感。",
      camera_block: "保持镜头语言稳定，只针对构图和视觉层次做必要修复。",
      negative_prompt: evaluation.repairTargets.join("；"),
      optimization_prompt: repairInstruction,
      referenced_asset_ids: [candidate.asset_id],
      source_node_ids: [candidate.node_id, evaluationNodeId].filter(Boolean),
      repair_focus_key: repairFocus?.key || "",
      repair_focus_label: repairFocus?.label || repairFocus?.key || "",
      repair_parent_batch_id: batch?.id || "",
      repair_iteration: Number.isFinite(parentIteration) ? parentIteration + 1 : 1,
      workflow: "evaluation_repair_phase_4",
    };
  }

  async function createRepairBranchFromCandidate(batch, candidate, options = {}) {
    if (!canvas || repairingCandidateId) {
      return;
    }
    const repairFocus = options.dimension || null;
    const sourceNode = canvas.nodes.find((node) => node.id === candidate.node_id);
    if (!sourceNode) {
      onStatus?.({ kind: "failed", message: "请先精选候选图，把图片回写到画布后再生成修复分支" });
      return;
    }
    const evaluation = candidateEvaluationPayload(candidate, repairFocus);
    setRepairingCandidateId(candidate.id);
    onStatus?.({ kind: "loading", message: repairFocus ? "正在生成定向维度修复分支" : "正在从候选图评分生成修复分支" });
    const createdNodes = [];
    try {
      const evaluationNode = await createCanvasNode(canvas.id, {
        type: "evaluation",
        title: repairFocus ? `${repairFocus.label || repairFocus.key} 定向评价` : `候选图 #${candidate.index + 1} 评价`,
        position: { x: sourceNode.position.x + 420, y: sourceNode.position.y },
        size: SEMANTIC_NODE_SIZE,
        payload: {
          role: "image_evaluation",
          source: "candidate_evaluation",
          batch_id: batch.id,
          candidate_id: candidate.id,
          asset_id: candidate.asset_id,
          score: candidate.score,
          total_score: evaluation.totalScore,
          dimensions: evaluation.dimensions,
          repair_targets: evaluation.repairTargets,
          instruction: evaluation.suggestion,
          optimization_prompt: evaluation.optimizationPrompt,
          repair_focus_key: repairFocus?.key || "",
          repair_focus_label: repairFocus?.label || repairFocus?.key || "",
          repair_parent_batch_id: batch.id,
          source_node_ids: [sourceNode.id],
          workflow: "evaluation_repair_phase_4",
        },
      });
      createdNodes.push(evaluationNode);
      const promptNode = await createCanvasNode(canvas.id, {
        type: "prompt_program",
        title: repairFocus ? `Repair ${repairFocus.label || repairFocus.key}` : `Repair Prompt #${candidate.index + 1}`,
        position: { x: sourceNode.position.x + 840, y: sourceNode.position.y },
        size: { width: 360, height: 230 },
        payload: repairPromptProgramPayload(candidate, evaluationNode.id, batch, repairFocus),
      });
      createdNodes.push(promptNode);
      const edges = [];
      edges.push(await createCanvasEdge(canvas.id, { source_node_id: sourceNode.id, target_node_id: evaluationNode.id, type: "evaluated_by", payload: { workflow: "evaluation_repair_phase_4", candidate_id: candidate.id, repair_focus_key: repairFocus?.key || "" } }));
      edges.push(await createCanvasEdge(canvas.id, { source_node_id: evaluationNode.id, target_node_id: promptNode.id, type: "repair_prompt", payload: { workflow: "evaluation_repair_phase_4", candidate_id: candidate.id, repair_focus_key: repairFocus?.key || "" } }));
      setCanvas((current) => (current ? { ...current, nodes: [...current.nodes, ...createdNodes], edges: [...current.edges, ...edges] } : current));
      setSelectedNodeId(promptNode.id);
      setFinalSubmission(null);
      await refreshCanvasArtifacts();
      onStatus?.({ kind: "ready", message: repairFocus ? "定向修复 Prompt Program 已写入画布" : "修复 Prompt Program 已写入画布" });
    } catch (error) {
      if (createdNodes.length) {
        await Promise.allSettled(createdNodes.map((node) => deleteCanvasNode(canvas.id, node.id)));
        await loadCanvas();
      }
      onStatus?.({ kind: "failed", message: error?.message || "生成修复分支失败" });
    } finally {
      setRepairingCandidateId("");
    }
  }

  async function updateCandidateStatus(batch, candidate, status) {
    if (!canvas || updatingCandidateId) {
      return;
    }
    setUpdatingCandidateId(candidate.id);
    try {
      const selectedPosition = status === "selected" ? canvasPoint(760, 220 + selectedCandidateCount * 36, view) : null;
      await updateCanvasImageCandidate(canvas.id, batch.id, candidate.id, {
        status,
        reason: status === "selected" ? "Selected for video exploration" : "Rejected during candidate review",
        position: selectedPosition,
      });
      await refreshCanvasArtifacts();
      await onComplete?.();
      setFinalSubmission(null);
      onStatus?.({ kind: "ready", message: status === "selected" ? "候选图已精选并回写画布节点" : "候选图已标记为淘汰" });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "候选图状态更新失败" });
    } finally {
      setUpdatingCandidateId("");
    }
  }

  function openVideoDialog(candidate) {
    dialogReturnFocusRef.current = document.activeElement;
    const nodeId = candidate?.node_id || "";
    const latestVideoArtifact = nodeId ? latestNodePromptArtifact(promptArtifacts, nodeId, "storyboard_video_prompt_version") : null;
    const prompt = artifactPrompt(latestVideoArtifact) || `基于这张精选图生成专业短片：保持主体身份、材质、构图和光影，加入克制的镜头推进与高级商业广告节奏。`;
    setVideoDialogCandidate(candidate);
    setVideoPrompt(prompt);
    setVideoPromptArtifactId(latestVideoArtifact?.id || "");
  }

  function closeVideoDialog() {
    setVideoDialogCandidate(null);
    setVideoPromptArtifactId("");
    restoreDialogFocus(dialogReturnFocusRef);
  }

  function imageEditSourceNodes(node = selectedNode) {
    if (!canvas || !node) {
      return [];
    }
    const nodesById = new Map(canvas.nodes.map((item) => [item.id, item]));
    const candidateNodeIds = [node.id, ...selectedSourceIds];
    const mentionLabels = new Set(promptMentionLabels([brief, node.payload?.prompt, node.payload?.final_prompt, node.payload?.edit_prompt, node.payload?.instruction].filter(Boolean).join(" ")));
    for (const item of canvas.nodes) {
      if (item.type === "asset" && item.payload?.mention_label && mentionLabels.has(item.payload.mention_label)) {
        candidateNodeIds.push(item.id);
      }
    }
    const seenAssetIds = new Set();
    const sources = [];
    for (const nodeId of candidateNodeIds) {
      const sourceNode = nodesById.get(nodeId);
      const assetId = sourceNode?.payload?.asset_id;
      const asset = assetId ? assetById.get(assetId) : null;
      if (!sourceNode || !asset || !isImageAsset(asset) || seenAssetIds.has(assetId)) {
        continue;
      }
      seenAssetIds.add(assetId);
      sources.push({ node: sourceNode, asset, assetId });
      if (sources.length >= 8) {
        break;
      }
    }
    return sources;
  }

  function videoRemixSourceAssetId(node) {
    const assetId = node?.payload?.source_asset_id;
    const asset = assetId ? assetById.get(assetId) : null;
    return asset && isImageAsset(asset) ? assetId : "";
  }

  function openImageEditDialog(node = selectedNode) {
    const sources = imageEditSourceNodes(node);
    if (!node || !sources.length) {
      onStatus?.({ kind: "failed", message: "请选择图片节点，或选择包含 @图片引用的图谱后再编辑" });
      return;
    }
    dialogReturnFocusRef.current = document.activeElement;
    setImageEditDialogNode({ node, sources });
    setImageEditPrompt(node.payload?.final_prompt || node.payload?.edit_prompt || node.payload?.prompt || "基于当前多张参考图进行专业图片编辑：保留关键主体身份、构图、材质和光影，只按以下要求调整：");
    setImageEditSettings(IMAGE_EDIT_DEFAULTS);
  }

  function closeImageEditDialog() {
    setImageEditDialogNode(null);
    restoreDialogFocus(dialogReturnFocusRef);
  }

  function updateVideoPrompt(value) {
    setVideoPrompt(value);
    setVideoPromptArtifactId("");
  }

  async function createImageEditFromNode() {
    if (!canvas || !imageEditDialogNode || creatingImageEdit) {
      return;
    }
    const prompt = imageEditPrompt.trim();
    const sourceEntries = imageEditDialogNode.sources || imageEditSourceNodes(imageEditDialogNode.node || imageEditDialogNode);
    const sourceNodeIds = sourceEntries.map((entry) => entry.node.id);
    const sourceAssetIds = imageEditSettings.actionType === "inpaint" ? sourceEntries.map((entry) => entry.assetId).filter((assetId) => assetId !== imageEditSettings.maskAssetId) : sourceEntries.map((entry) => entry.assetId);
    if (!prompt || !sourceNodeIds.length || !sourceAssetIds.length) {
      onStatus?.({ kind: "failed", message: "请确认当前图谱里有可编辑的图片源和编辑提示词" });
      return;
    }
    if (imageEditSettings.actionType === "inpaint") {
      const maskEntry = sourceEntries.find((entry) => entry.assetId === imageEditSettings.maskAssetId);
      if (!maskEntry) {
        onStatus?.({ kind: "failed", message: "请选择已在当前编辑图谱中的 mask 图片" });
        return;
      }
    }
    setCreatingImageEdit(true);
    onStatus?.({ kind: "loading", message: "正在创建画布图片编辑任务" });
    try {
      const task = await createCanvasImageEditTask(canvas.id, {
        prompt,
        source_node_ids: sourceNodeIds,
        source_image_asset_ids: sourceAssetIds,
        ...(imageEditSettings.actionType === "inpaint" ? { mask_asset_id: imageEditSettings.maskAssetId } : {}),
        action_type: imageEditSettings.actionType,
        model: "openai",
        threshold: 0,
        max_iter: 1,
        skip_prompt_evaluation: true,
        params: { size: imageEditSettings.size, quality: imageEditSettings.quality },
      });
      closeImageEditDialog();
      setImageEditPrompt("");
      setFinalSubmission(null);
      setPendingImageEditTasks((current) => ({ ...current, [task.task_id]: { attempts: 0 } }));
      await onComplete?.();
      onStatus?.({ kind: "ready", message: `多图编辑任务已创建：${task.task_id.slice(0, 8)} · ${sourceAssetIds.length} 张源图` });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "图片编辑任务创建失败" });
    } finally {
      setCreatingImageEdit(false);
    }
  }

  function openVideoRemixDialog(node = selectedNode) {
    const sourceAssetId = videoRemixSourceAssetId(node);
    if (!node || node.type !== "generated_video" || !sourceAssetId) {
      onStatus?.({ kind: "failed", message: "请选择源首帧仍在当前项目资产库中的视频节点" });
      return;
    }
    dialogReturnFocusRef.current = document.activeElement;
    setVideoRemixDialogNode(node);
    setVideoRemixPrompt(node.payload?.motion_prompt || "基于原始首帧重新生成视频：保持主体和风格，调整镜头运动、节奏和动作表现。");
  }

  function closeVideoRemixDialog() {
    setVideoRemixDialogNode(null);
    restoreDialogFocus(dialogReturnFocusRef);
  }

  async function createVideoRemixFromNode() {
    if (!canvas || !videoRemixDialogNode || creatingVideo) {
      return;
    }
    const prompt = videoRemixPrompt.trim();
    const sourceAssetId = videoRemixSourceAssetId(videoRemixDialogNode);
    if (!prompt || !sourceAssetId) {
      onStatus?.({ kind: "failed", message: "请确认源首帧仍在当前项目资产库中，并填写视频调整提示词" });
      return;
    }
    setCreatingVideo(true);
    onStatus?.({ kind: "loading", message: "正在基于原始首帧重新生成视频" });
    try {
      const task = await createCanvasVideoTask(canvas.id, {
        prompt,
        source_image_asset_id: sourceAssetId,
        selected_node_ids: [videoRemixDialogNode.id],
        duration: VIDEO_DEFAULTS.duration,
        aspect_ratio: VIDEO_DEFAULTS.aspectRatio,
        params: {},
      });
      closeVideoRemixDialog();
      setVideoRemixPrompt("");
      setFinalSubmission(null);
      setPendingVideoTasks((current) => ({ ...current, [task.task_id]: { attempts: 0 } }));
      await onComplete?.();
      onStatus?.({ kind: "ready", message: `视频重生成任务已创建：${task.task_id.slice(0, 8)}` });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "视频重生成任务创建失败" });
    } finally {
      setCreatingVideo(false);
    }
  }

  async function createVideoFromCandidate() {
    if (!canvas || !videoDialogCandidate || creatingVideo) {
      return;
    }
    const prompt = videoPrompt.trim();
    if (!prompt) {
      onStatus?.({ kind: "failed", message: "请填写图生视频运动提示词" });
      return;
    }
    setCreatingVideo(true);
    onStatus?.({ kind: "loading", message: "正在从精选图生成视频任务" });
    try {
      const sourceNodeIds = videoDialogCandidate.node_id ? [videoDialogCandidate.node_id] : selectedSourceIds;
      const task = await createCanvasVideoTask(canvas.id, {
        prompt,
        prompt_artifact_id: videoPromptArtifactId || undefined,
        source_candidate_id: videoDialogCandidate.id,
        selected_node_ids: sourceNodeIds,
        duration: VIDEO_DEFAULTS.duration,
        aspect_ratio: VIDEO_DEFAULTS.aspectRatio,
        params: {},
      });
      closeVideoDialog();
      setVideoPrompt("");
      setVideoPromptArtifactId("");
      setFinalSubmission(null);
      setPendingVideoTasks((current) => ({ ...current, [task.task_id]: { attempts: 0 } }));
      await onComplete?.();
      onStatus?.({ kind: "ready", message: `图生视频任务已创建：${task.task_id.slice(0, 8)}` });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "图生视频任务创建失败" });
    } finally {
      setCreatingVideo(false);
    }
  }

  function openMediaApprovalDialog(node = selectedNode, approved = true) {
    if (!node || !["edited_image", "generated_video"].includes(node.type)) {
      onStatus?.({ kind: "failed", message: "请选择可审批的编辑图片或生成视频节点" });
      return;
    }
    dialogReturnFocusRef.current = document.activeElement;
    setMediaApprovalDialog({
      node,
      approved,
      reason: approved
        ? "确认该媒体符合生产交付标准，画面质量、主体一致性和使用意图已通过设计审查。"
        : "撤销该媒体的生产批准，需要继续优化后再进入交付链路。",
    });
  }

  function closeMediaApprovalDialog() {
    setMediaApprovalDialog(null);
    restoreDialogFocus(dialogReturnFocusRef);
  }

  function setMediaApprovalReason(reason) {
    setMediaApprovalDialog((current) => (current ? { ...current, reason } : current));
  }

  async function submitMediaApprovalDialog() {
    if (!canvas || !mediaApprovalDialog || mediaApprovalSubmitting) {
      return;
    }
    const reason = mediaApprovalDialog.reason.trim();
    if (!reason) {
      onStatus?.({ kind: "failed", message: "请填写审批原因" });
      return;
    }
    const { node, approved } = mediaApprovalDialog;
    setMediaApprovalSubmitting(true);
    setApprovingMediaNodeId(node.id);
    onStatus?.({ kind: "loading", message: approved ? "正在批准生产媒体" : "正在撤销生产媒体批准" });
    try {
      const updated = await setCanvasMediaApproval(canvas.id, node.id, { approved, reason });
      setCanvas((current) => (current ? { ...current, nodes: current.nodes.map((item) => (item.id === updated.id ? updated : item)) } : current));
      setSelectedNodeId(updated.id);
      await loadBranchOperations({ ...branchOperationFilters, offset: 0 });
      setFinalSubmission(null);
      closeMediaApprovalDialog();
      await onComplete?.();
      onStatus?.({ kind: "ready", message: approved ? "已批准为生产媒体，并写入治理日志" : "已撤销生产媒体批准，并写入治理日志" });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "媒体审批状态更新失败" });
    } finally {
      setApprovingMediaNodeId("");
      setMediaApprovalSubmitting(false);
    }
  }

  async function submitFinalJson(enableGeneration = false) {
    if (!canvas || finalSubmitting || !selectedSourceIds.length) {
      return;
    }
    setFinalSubmitting(true);
    setFinalError("");
    onStatus?.({ kind: "loading", message: enableGeneration ? "正在提交最终 JSON 并创建生成任务" : "正在编译最终 JSON" });
    try {
      const payload = await submitCanvasFinal(canvas.id, {
        selected_node_ids: selectedSourceIds,
        artifact_node_id: selectedNode?.type === "brief" ? selectedNode.id : null,
        root_node_id: selectedNode?.id || selectedSourceIds[0],
        profile: "professional_design",
        generation: enableGeneration ? { enabled: true, model: "openai", threshold: 0, skip_prompt_evaluation: true, params: {} } : { enabled: false, params: {} },
      });
      setFinalSubmission(payload);
      if (payload.task) {
        await onComplete?.();
      }
      onStatus?.({ kind: "ready", message: payload.task ? `最终 JSON 已提交，任务 ${payload.task.task_id.slice(0, 8)} 已创建` : "最终 JSON 已生成并保存" });
    } catch (error) {
      const message = error?.message || "最终 JSON 提交失败";
      setFinalError(message);
      onStatus?.({ kind: "failed", message });
    } finally {
      setFinalSubmitting(false);
    }
  }

  function startPan(event) {
    if (event.button !== 0 || event.target.closest(".canvas-node-card") || event.target.closest("button") || event.target.closest("textarea")) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    pointerCaptureTargetRef.current = event.currentTarget;
    setInteraction({ type: "pan", pointerId: event.pointerId, start: { x: event.clientX, y: event.clientY }, origin: view });
  }

  function startNodeDrag(event, node) {
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    pointerCaptureTargetRef.current = event.currentTarget;
    setSelectedNodeId(node.id);
    latestDragPositionRef.current = node.position;
    setInteraction({ type: "node", pointerId: event.pointerId, nodeId: node.id, start: { x: event.clientX, y: event.clientY }, origin: node.position });
  }

  function movePointer(event) {
    if (!interaction || interaction.pointerId !== event.pointerId) {
      return;
    }
    const delta = { x: event.clientX - interaction.start.x, y: event.clientY - interaction.start.y };
    if (interaction.type === "pan") {
      setView({ ...interaction.origin, x: interaction.origin.x + delta.x, y: interaction.origin.y + delta.y });
      return;
    }
    const position = { x: interaction.origin.x + delta.x / view.scale, y: interaction.origin.y + delta.y / view.scale };
    latestDragPositionRef.current = position;
    setCanvas((current) => (current ? { ...current, nodes: current.nodes.map((node) => (node.id === interaction.nodeId ? { ...node, position } : node)) } : current));
  }

  async function endPointer(event) {
    if (!interaction || interaction.pointerId !== event.pointerId) {
      return;
    }
    const ended = interaction;
    const finalPosition = latestDragPositionRef.current;
    const captureTarget = pointerCaptureTargetRef.current;
    if (captureTarget?.hasPointerCapture?.(event.pointerId)) {
      captureTarget.releasePointerCapture(event.pointerId);
    }
    pointerCaptureTargetRef.current = null;
    setInteraction(null);
    latestDragPositionRef.current = null;
    if (ended.type !== "node" || !canvas || !finalPosition) {
      return;
    }
    if (Math.abs(finalPosition.x - ended.origin.x) < 0.01 && Math.abs(finalPosition.y - ended.origin.y) < 0.01) {
      return;
    }
    const node = canvas.nodes.find((item) => item.id === ended.nodeId);
    if (!node) {
      return;
    }
    try {
      await updateCanvasNodePositions(canvas.id, [{ id: node.id, position: finalPosition }]);
      onStatus?.({ kind: "ready", message: "画布位置已保存" });
    } catch (error) {
      onStatus?.({ kind: "failed", message: error?.message || "画布位置保存失败" });
      loadCanvas();
    }
  }

  function zoomBy(nextScale) {
    setView((current) => ({ ...current, scale: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number((current.scale + nextScale).toFixed(2)))) }));
  }

  function resetView() {
    setView(DEFAULT_VIEW);
  }

  function fitCanvas() {
    if (!canvas?.nodes?.length || !stageRef.current) {
      resetView();
      return;
    }
    const bounds = canvasBounds(canvas.nodes);
    const viewport = stageRef.current.getBoundingClientRect();
    const scale = Math.min(FIT_MAX_ZOOM, Math.max(MIN_ZOOM, Math.min(viewport.width / (bounds.width + FIT_PADDING_X), viewport.height / (bounds.height + FIT_PADDING_Y))));
    setView({
      x: (viewport.width - bounds.width * scale) / 2 - bounds.minX * scale,
      y: (viewport.height - bounds.height * scale) / 2 - bounds.minY * scale,
      scale: Number(scale.toFixed(2)),
    });
  }

  const selectedNode = useMemo(() => canvas?.nodes.find((node) => node.id === selectedNodeId) || null, [canvas?.nodes, selectedNodeId]);
  const selectedSourceIds = useMemo(() => selectedSourceNodeIds(canvas, selectedNodeId), [canvas, selectedNodeId]);
  const selectedHighlightIds = useMemo(() => Array.from(new Set([...selectedConnectedNodeIds(canvas, selectedNodeId), ...selectedSourceIds])), [canvas, selectedNodeId, selectedSourceIds]);
  const selectedHighlightSet = useMemo(() => new Set(selectedHighlightIds), [selectedHighlightIds]);
  const selectedSourceKey = useMemo(() => selectedSourceIds.join("|"), [selectedSourceIds]);
  const selectedSourceNodeCount = selectedSourceIds.length;
  const selectedHighlightNodeCount = selectedHighlightIds.length;
  const activeMentionOption = mentionMenu?.options?.[activeMentionIndex] || null;
  const selectedImageEditSourceCount = imageEditSourceNodes(selectedNode).length;

  useEffect(() => {
    setSeriesPlan(null);
    setFinalSubmission(null);
    setFinalError("");
  }, [selectedSourceKey]);

  return (
    <CanvasWorkspaceView
      referenceRoles={REFERENCE_ROLES}
      refs={{ assetUploadInputRef, briefTextareaRef, stageRef }}
      state={{
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
        uploadingAssets,
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
        optimizingPromptNodeId,
        optimizingVideoPromptNodeId,
        promptArtifacts,
        imageEditDialogNode,
        imageEditPrompt,
        imageEditSettings,
        loading,
        layingOutRepairGraph,
        mediaApprovalDialog,
        mediaApprovalSubmitting,
        mediaAssets,
        mentionMenu,
        planningSeries,
        materializingSeries,
        materializingRepairGraph,
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
        unresolvedBriefMentions,
        updatingCandidateId,
        updatingPromptProgram,
        videoDialogCandidate,
        videoPrompt,
        videoPromptArtifactId,
        videoRemixDialogNode,
        videoRemixPrompt,
        view,
      }}
      actions={{
        addAssetNode,
        addBriefNode,
        addStoryboardNode,
        closeBranchOperationDialog,
        closeImageBatchDialog,
        closeMediaApprovalDialog,
        closeImageEditDialog,
        closeMentionMenu: () => setMentionMenu(null),
        closeVideoDialog,
        closeVideoRemixDialog,
        createImageBatchFromSelection,
        createImageEditFromNode,
        createPromptProgramFromSelection,
        createRepairBranchFromCandidate,
        createRepairImageBatchFromNode,
        createVideoFromCandidate,
        createVideoRemixFromNode,
        endPointer,
        fitCanvas,
        handleBriefChange,
        handleBriefCursor,
        handleBriefKeyDown,
        layoutRepairVersionGraph,
        loadBranchOperations,
        materializeRepairVersionGraph,
        materializeSemanticSkeleton,
        materializeSeriesFrames,
        movePointer,
        openBranchOperationDialog,
        openCanvasAssetUpload,
        openImageBatchDialog,
        openImageEditDialog,
        openMediaApprovalDialog,
        openVideoDialog,
        openVideoRemixDialog,
        optimizeStoryboardImagePrompt,
        optimizeStoryboardVideoPrompt,
        planSeries,
        refreshBatchesFromButton,
        resetView,
        selectMentionOption,
        setBatchSettings,
        setImageEditPrompt,
        setImageEditSettings,
        setMediaApprovalReason,
        setBranchOperationReason,
        setReferenceInstruction,
        setReferenceRole,
        setRepairVersionArchiveStatus,
        pinRepairVersionPath,
        submitBranchOperationDialog,
        submitMediaApprovalDialog,
        setSelectedNodeId,
        focusRepairVersionNode,
        setVideoPrompt: updateVideoPrompt,
        setVideoRemixPrompt,
        startNodeDrag,
        startPan,
        submitFinalJson,
        updateCandidateStatus,
        uploadCanvasAssets,
        updatePromptProgramNode,
        zoomBy,
      }}
    />
  );
}
