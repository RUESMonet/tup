import { getJson, postForm, postJson } from "./client";

export function fetchProjects() {
  return getJson("/api/projects");
}

export function createProject(payload) {
  return postJson("/api/projects", payload);
}

export function fetchProject(projectId) {
  return getJson(`/api/projects/${projectId}`);
}

export function fetchProjectAssets(projectId) {
  return getJson(`/api/projects/${projectId}/assets`);
}

export function fetchProjectTasks(projectId) {
  return getJson(`/api/projects/${projectId}/tasks`);
}

export function uploadProjectAsset(projectId, file, options = {}) {
  const formData = new FormData();
  formData.append("file", file);
  return postForm(`/api/projects/${projectId}/assets/upload`, formData, options);
}
