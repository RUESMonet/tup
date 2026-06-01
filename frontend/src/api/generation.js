import { getJson, postJson } from "./client";

export function createProjectImageTask(projectId, payload, options = {}) {
  return postJson(`/api/projects/${projectId}/generate/image`, payload, options);
}

export function createProjectImageEditTask(projectId, payload, options = {}) {
  return postJson(`/api/projects/${projectId}/generate/image-edit`, payload, options);
}

export function createProjectVideoTask(projectId, payload, options = {}) {
  return postJson(`/api/projects/${projectId}/generate/video`, payload, options);
}

export function fetchProjectTask(taskId, options = {}) {
  return getJson(`/api/tasks/${taskId}`, options);
}

export function fetchProjectTaskHistory(taskId, options = {}) {
  return getJson(`/api/tasks/${taskId}/history`, options);
}
