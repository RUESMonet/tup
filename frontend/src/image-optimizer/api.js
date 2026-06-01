import { getJson, isAbortError, postJson, postNdjson, requestErrorMessage } from "../api/client";

export async function fetchModels({ signal } = {}) {
  return getJson("/api/models", { signal });
}

export async function analyzeReferencePrompt(payload, { signal } = {}) {
  return postJson("/api/reference/analyze", payload, { signal });
}

export async function streamReferencePromptDraft(payload, { signal, onEvent } = {}) {
  return postNdjson("/api/reference/draft/stream", payload, { signal, onEvent });
}

export async function createGenerationTask(payload, { signal } = {}) {
  return postJson("/api/generate", payload, { signal });
}

export async function optimizePromptSkill(payload, { signal } = {}) {
  return postJson("/api/prompt/optimize", payload, { signal });
}

export async function fetchTask(taskId, { signal } = {}) {
  return getJson(`/api/task/${taskId}`, { signal });
}

export async function fetchTaskHistory(taskId, { signal } = {}) {
  return getJson(`/api/task/${taskId}/history`, { signal });
}

export { isAbortError, requestErrorMessage };
