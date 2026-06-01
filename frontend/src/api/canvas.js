import { deleteJson, getJson, patchJson, postJson } from "./client";

export function fetchCanvases(projectId) {
  return getJson(`/api/projects/${projectId}/canvases`);
}

export function createCanvas(projectId, payload) {
  return postJson(`/api/projects/${projectId}/canvases`, payload);
}

export function fetchCanvas(canvasId) {
  return getJson(`/api/canvases/${canvasId}`);
}

export function fetchCanvasBranchOperations(canvasId, filters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== "" && value !== "all") {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return getJson(`/api/canvases/${canvasId}/branch-operations${query ? `?${query}` : ""}`);
}

export function createCanvasNode(canvasId, payload) {
  return postJson(`/api/canvases/${canvasId}/nodes`, payload);
}

export function createCanvasEdge(canvasId, payload) {
  return postJson(`/api/canvases/${canvasId}/edges`, payload);
}

export function updateCanvasNode(canvasId, nodeId, payload) {
  return patchJson(`/api/canvases/${canvasId}/nodes/${nodeId}`, payload);
}

export function setCanvasMediaApproval(canvasId, nodeId, payload) {
  return postJson(`/api/canvases/${canvasId}/media/${nodeId}/approval`, payload);
}

export function setCanvasRepairVersionStatus(canvasId, nodeId, status, options = {}) {
  return postJson(`/api/canvases/${canvasId}/repair-versions/${nodeId}/status`, { status, ...options });
}

export function materializeCanvasRepairVersion(canvasId, payload) {
  return postJson(`/api/canvases/${canvasId}/repair-versions/materialize`, payload);
}

export function pinCanvasRepairVersion(canvasId, nodeId, payload = {}) {
  return postJson(`/api/canvases/${canvasId}/repair-versions/${nodeId}/pin`, payload);
}

export function unpinCanvasRepairVersion(canvasId, nodeId, payload = {}) {
  return postJson(`/api/canvases/${canvasId}/repair-versions/${nodeId}/unpin`, payload);
}

export function deleteCanvasNode(canvasId, nodeId) {
  return deleteJson(`/api/canvases/${canvasId}/nodes/${nodeId}`);
}

export function planCanvasSeries(canvasId, payload) {
  return postJson(`/api/canvases/${canvasId}/series/plan`, payload);
}

export function submitCanvasFinal(canvasId, payload) {
  return postJson(`/api/canvases/${canvasId}/final-submit`, payload);
}

export function updateCanvasNodePositions(canvasId, positions) {
  return patchJson(`/api/canvases/${canvasId}/nodes/positions`, { positions });
}

export function createCanvasImageEditTask(canvasId, payload) {
  return postJson(`/api/canvases/${canvasId}/generate/image-edit`, payload);
}

export function createCanvasImageBatch(canvasId, payload) {
  return postJson(`/api/canvases/${canvasId}/image-batches`, payload);
}

export function fetchCanvasImageBatches(canvasId) {
  return getJson(`/api/canvases/${canvasId}/image-batches`);
}

export function updateCanvasImageCandidate(canvasId, batchId, candidateId, payload) {
  return patchJson(`/api/canvases/${canvasId}/image-batches/${batchId}/candidates/${candidateId}`, payload);
}

export function createCanvasVideoTask(canvasId, payload) {
  return postJson(`/api/canvases/${canvasId}/generate/video`, payload);
}

export function fetchCanvasPromptArtifacts(canvasId, filters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return getJson(`/api/canvases/${canvasId}/prompt-artifacts${query ? `?${query}` : ""}`);
}

export function optimizeCanvasImagePrompt(canvasId, payload) {
  return postJson(`/api/canvases/${canvasId}/storyboard/image-prompt`, payload);
}

export function optimizeCanvasVideoPrompt(canvasId, payload) {
  return postJson(`/api/canvases/${canvasId}/storyboard/video-prompt`, payload);
}
