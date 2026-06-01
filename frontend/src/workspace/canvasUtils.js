import { assetLabel } from "./mediaUrls";

export const DEFAULT_VIEW = { x: 0, y: 0, scale: 1 };
export const NODE_SIZE = { width: 320, height: 180 };
export const SERIES_FRAME_SIZE = { width: 360, height: 210 };
export const SEMANTIC_NODE_SIZE = { width: 340, height: 190 };
export const FINAL_JSON_NODE_SIZE = { width: 380, height: 220 };
export const SERIES_FRAME_VERTICAL_GAP = 230;
export const SERIES_FRAME_X_OFFSET = 440;
export const SERIES_FRAME_FALLBACK_POINT = { x: 620, y: 140 };
export const MIN_ZOOM = 0.45;
export const MAX_ZOOM = 1.8;
export const FIT_MAX_ZOOM = 1.35;
export const ZOOM_STEP = 0.1;
export const FIT_PADDING_X = 280;
export const FIT_PADDING_Y = 240;

export function canvasPoint(x, y, view) {
  return { x: (x - view.x) / view.scale, y: (y - view.y) / view.scale };
}

export function canvasBounds(nodes) {
  const boxes = nodes.map((node) => ({
    minX: node.position?.x || 0,
    minY: node.position?.y || 0,
    maxX: (node.position?.x || 0) + (node.size?.width || NODE_SIZE.width),
    maxY: (node.position?.y || 0) + (node.size?.height || NODE_SIZE.height),
  }));
  const minX = Math.min(...boxes.map((box) => box.minX));
  const minY = Math.min(...boxes.map((box) => box.minY));
  const maxX = Math.max(...boxes.map((box) => box.maxX));
  const maxY = Math.max(...boxes.map((box) => box.maxY));
  return { minX, minY, width: maxX - minX, height: maxY - minY };
}

export function edgePath(source, target) {
  const start = nodeCenter(source);
  const end = nodeCenter(target);
  const controlOffset = Math.max(90, Math.abs(end.x - start.x) * 0.36);
  return `M ${start.x} ${start.y} C ${start.x + controlOffset} ${start.y}, ${end.x - controlOffset} ${end.y}, ${end.x} ${end.y}`;
}

export function nodeCenter(node) {
  return {
    x: (node.position?.x || 0) + (node.size?.width || NODE_SIZE.width) / 2,
    y: (node.position?.y || 0) + (node.size?.height || NODE_SIZE.height) / 2,
  };
}

export function videoPromptRootNodeId(canvas, node, selectedNodeIds) {
  if (!node) {
    return selectedNodeIds[0];
  }
  if (node.type === "selected_image") {
    const selectedIdSet = new Set(selectedNodeIds);
    const sourceEdge = (canvas?.edges || []).find((edge) => edge.target_node_id === node.id && selectedIdSet.has(edge.source_node_id));
    return sourceEdge?.source_node_id || selectedNodeIds.find((nodeId) => nodeId !== node.id) || node.id;
  }
  return selectedNodeIds.includes(node.id) ? node.id : selectedNodeIds[0];
}

export function selectedSourceNodeIds(canvas, selectedNodeId) {
  const nodesById = new Map((canvas?.nodes || []).map((node) => [node.id, node]));
  const selected = nodesById.get(selectedNodeId);
  if (!selected) {
    return [];
  }
  const allowedSelectedImageIds = repairBranchSourceImageIds(canvas, selected, nodesById);
  if (selected.type === "selected_image") {
    allowedSelectedImageIds.add(selected.id);
  }
  if (selected.type === "repair_version" && selected.payload?.source_image_node_id) {
    allowedSelectedImageIds.add(selected.payload.source_image_node_id);
  }
  if (isBlockedSourceNode(selected, allowedSelectedImageIds)) {
    return [];
  }
  const adjacency = new Map();
  for (const node of canvas?.nodes || []) {
    if (!isBlockedSourceNode(node, allowedSelectedImageIds)) {
      adjacency.set(node.id, new Set());
    }
  }
  for (const edge of canvas?.edges || []) {
    if (adjacency.has(edge.source_node_id) && adjacency.has(edge.target_node_id)) {
      adjacency.get(edge.source_node_id).add(edge.target_node_id);
      adjacency.get(edge.target_node_id).add(edge.source_node_id);
    }
  }
  const nodeIds = [];
  const queue = [selectedNodeId];
  const seen = new Set();
  while (queue.length) {
    const nodeId = queue.shift();
    if (seen.has(nodeId) || !adjacency.has(nodeId)) {
      continue;
    }
    seen.add(nodeId);
    nodeIds.push(nodeId);
    for (const nextId of adjacency.get(nodeId) || []) {
      if (!seen.has(nextId)) {
        queue.push(nextId);
      }
    }
  }
  return includeMentionedAssetNodeIds(nodeIds, canvas?.nodes || []);
}

function repairBranchSourceImageIds(canvas, selected, nodesById) {
  const sourceImageIds = new Set();
  if (selected.type === "prompt_program" && selected.payload?.workflow === "evaluation_repair_phase_4") {
    for (const sourceNodeId of selected.payload?.source_node_ids || []) {
      const source = nodesById.get(sourceNodeId);
      if (source?.type === "selected_image") {
        sourceImageIds.add(source.id);
      }
    }
  }
  if (selected.type === "evaluation" && selected.payload?.workflow === "evaluation_repair_phase_4") {
    for (const sourceNodeId of selected.payload?.source_node_ids || []) {
      const source = nodesById.get(sourceNodeId);
      if (source?.type === "selected_image") {
        sourceImageIds.add(source.id);
      }
    }
  }
  for (const edge of canvas?.edges || []) {
    const source = nodesById.get(edge.source_node_id);
    if (selected.type === "repair_version" && edge.type === "repair_version_source" && edge.target_node_id === selected.id && source?.type === "selected_image") {
      sourceImageIds.add(edge.source_node_id);
    }
  }
  return sourceImageIds;
}

function isBlockedSourceNode(node, allowedSelectedImageIds) {
  if (node.type === "series_frame" || node.type === "generated_video") {
    return true;
  }
  if (node.type === "selected_image") {
    return !allowedSelectedImageIds.has(node.id);
  }
  return false;
}

export function selectedConnectedNodeIds(canvas, selectedNodeId) {
  if (!canvas || !selectedNodeId) {
    return [];
  }
  const nodesById = new Map(canvas.nodes.map((node) => [node.id, node]));
  if (!nodesById.has(selectedNodeId)) {
    return [];
  }
  const adjacency = new Map(canvas.nodes.map((node) => [node.id, new Set()]));
  for (const edge of canvas.edges || []) {
    if (adjacency.has(edge.source_node_id) && adjacency.has(edge.target_node_id)) {
      adjacency.get(edge.source_node_id).add(edge.target_node_id);
      adjacency.get(edge.target_node_id).add(edge.source_node_id);
    }
  }
  const nodeIds = [];
  const queue = [selectedNodeId];
  const seen = new Set();
  while (queue.length) {
    const nodeId = queue.shift();
    if (seen.has(nodeId)) {
      continue;
    }
    seen.add(nodeId);
    nodeIds.push(nodeId);
    for (const nextId of adjacency.get(nodeId) || []) {
      if (!seen.has(nextId)) {
        queue.push(nextId);
      }
    }
  }
  return nodeIds;
}

export function seriesFramePayload(frame, plan) {
  return {
    prompt: frame.prompt,
    role: "series_frame",
    scene: frame.beat,
    camera: frame.camera,
    character_anchors: plan.character_lock || [],
    preserve: frame.continuity || [],
    text_literals: plan.text_literals || [],
    source_node_ids: frame.source_node_ids || [],
    provenance: "series_director",
    source_canvas_id: plan.canvas_id,
    source_project_id: plan.project_id,
    plan_profile: "campaign_series",
    frame_index: frame.index,
    style: plan.style_lock?.style || "",
    lighting: plan.style_lock?.lighting || "",
    color_palette: plan.style_lock?.color_palette || "",
  };
}

export function seriesFrameOrigin(nodes, view) {
  if (!nodes.length) {
    return canvasPoint(SERIES_FRAME_FALLBACK_POINT.x, SERIES_FRAME_FALLBACK_POINT.y, view);
  }
  const maxX = Math.max(...nodes.map((node) => node.position?.x || 0));
  const minY = Math.min(...nodes.map((node) => node.position?.y || 0));
  return { x: maxX + SERIES_FRAME_X_OFFSET, y: minY };
}

export function assetMentionLabel(asset) {
  const label = assetLabel(asset, "asset").replace(/\.[a-z0-9]+$/i, "").toLowerCase();
  const slug = label.replace(/[^a-z0-9一-龥]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 24);
  return slug || asset?.id?.slice?.(0, 8) || "asset";
}

export function uniqueAssetMentionLabel(asset, nodes) {
  const base = assetMentionLabel(asset);
  const used = new Set(nodes.map((node) => node.payload?.mention_label).filter(Boolean));
  return uniqueMentionLabel(base, used, asset);
}

export function assetMentionOptions(assets, nodes) {
  const used = new Set(nodes.map((node) => node.payload?.mention_label).filter(Boolean));
  return assets.map((asset) => {
    const existingNode = nodes.find((node) => node.type === "asset" && node.payload?.asset_id === asset.id && node.payload?.mention_label);
    const mentionLabel = existingNode?.payload?.mention_label || uniqueMentionLabel(assetMentionLabel(asset), used, asset);
    used.add(mentionLabel);
    return { asset, mentionLabel, existingNodeId: existingNode?.id || "" };
  });
}

export function extractMentionQuery(value, cursorIndex) {
  const beforeCursor = value.slice(0, cursorIndex);
  const match = beforeCursor.match(/(^|\s)@([a-z0-9一-龥-]{0,32})$/i);
  if (!match) {
    return null;
  }
  const token = match[2].toLowerCase();
  return { start: cursorIndex - token.length - 1, end: cursorIndex, query: token };
}

export function replaceMentionToken(value, range, mentionLabel) {
  const before = value.slice(0, range.start);
  const after = value.slice(range.end);
  const nextMention = `@${mentionLabel}`;
  const spacer = after && !/^\s/.test(after) ? " " : "";
  return { value: `${before}${nextMention}${spacer}${after}`, cursorIndex: before.length + nextMention.length + spacer.length };
}

export function findCanvasAssetNodeByMention(nodes, mentionLabel) {
  return nodes.find((node) => node.type === "asset" && node.payload?.mention_label === mentionLabel) || null;
}

export function promptMentionLabels(value) {
  return [...String(value || "").matchAll(/(^|\s)@([a-z0-9一-龥-]{1,32})(?=\s|$|[，。,.!?！？])/gi)].map((match) => match[2].toLowerCase());
}

function includeMentionedAssetNodeIds(sourceNodeIds, nodes) {
  const sourceSet = new Set(sourceNodeIds);
  const mentionedLabels = new Set();
  for (const node of nodes) {
    if (!sourceSet.has(node.id)) {
      continue;
    }
    for (const field of MENTION_SOURCE_FIELDS) {
      if (typeof node.payload?.[field] === "string") {
        for (const label of promptMentionLabels(node.payload[field])) {
          mentionedLabels.add(label);
        }
      }
    }
  }
  if (!mentionedLabels.size) {
    return sourceNodeIds;
  }
  const mentionedAssetNodeIds = nodes
    .filter((node) => node.type === "asset" && node.payload?.mention_label && mentionedLabels.has(String(node.payload.mention_label).toLowerCase()))
    .map((node) => node.id);
  return [...sourceNodeIds, ...mentionedAssetNodeIds.filter((nodeId) => !sourceSet.has(nodeId))];
}

const MENTION_SOURCE_FIELDS = ["prompt", "brief", "instruction", "scene", "final_prompt", "edit_prompt", "optimization_prompt"];

function uniqueMentionLabel(base, used, asset) {
  if (!used.has(base)) {
    return base;
  }
  for (let index = 2; index <= 99; index += 1) {
    const candidate = `${base}-${index}`;
    if (!used.has(candidate)) {
      return candidate;
    }
  }
  return `${base}-${asset?.id?.slice?.(0, 8) || Date.now()}`;
}

export function appendAssetMention(value, mentionLabel) {
  const mention = `@${mentionLabel}`;
  const text = value.trim();
  return text.includes(mention) ? value : `${text}${text ? " " : ""}${mention}`;
}

export function styleLockText(styleLock = {}) {
  return Object.entries(styleLock).map(([key, value]) => `${key}: ${value}`).join(" / ");
}

export function trimInspectorText(value) {
  const text = String(value || "");
  return text.length > 220 ? `${text.slice(0, 220)}…` : text;
}
