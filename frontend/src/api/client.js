import { REQUEST_TIMEOUT_MS } from "../image-optimizer/constants";

export function getSessionToken() {
  return "";
}

export function setSessionToken() {}

export async function getJson(url, options = {}) {
  const response = await fetchWithTimeout(url, withAuth(options));
  return parseResponse(response);
}

export async function postJson(url, payload, options = {}) {
  const response = await fetchWithTimeout(
    url,
    withAuth({
      ...options,
      method: "POST",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      body: JSON.stringify(payload),
    }),
  );
  return parseResponse(response);
}

export async function patchJson(url, payload, options = {}) {
  const response = await fetchWithTimeout(
    url,
    withAuth({
      ...options,
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      body: JSON.stringify(payload),
    }),
  );
  return parseResponse(response);
}

export async function deleteJson(url, options = {}) {
  const response = await fetchWithTimeout(
    url,
    withAuth({
      ...options,
      method: "DELETE",
    }),
  );
  return response.status === 204 ? null : parseResponse(response);
}

export async function postForm(url, formData, options = {}) {
  const response = await fetchWithTimeout(
    url,
    withAuth({
      ...options,
      method: "POST",
      body: formData,
    }),
  );
  return parseResponse(response);
}

export async function postNdjson(url, payload, options = {}) {
  return fetchNdjsonWithTimeout(
    url,
    withAuth({
      ...options,
      method: "POST",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      body: JSON.stringify(payload),
    }),
    options.onEvent,
    REQUEST_TIMEOUT_MS * 4,
  );
}

function withAuth(options = {}) {
  const token = getSessionToken();
  if (!token) {
    return options;
  }
  return { ...options, headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` } };
}

async function fetchWithTimeout(url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const externalSignal = options.signal;
  let timedOut = false;
  const abortFromExternal = () => controller.abort();
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  if (externalSignal?.aborted) {
    controller.abort();
  } else {
    externalSignal?.addEventListener("abort", abortFromExternal, { once: true });
  }

  const { signal, ...fetchOptions } = options;
  try {
    return await fetch(url, { ...fetchOptions, credentials: "same-origin", signal: controller.signal });
  } catch (error) {
    if (error?.name === "AbortError" && timedOut) {
      throw new Error("请求超时，请确认后端 http://127.0.0.1:8000 已启动");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
    externalSignal?.removeEventListener("abort", abortFromExternal);
  }
}

async function fetchNdjsonWithTimeout(url, options, onEvent, timeoutMs) {
  const controller = new AbortController();
  const externalSignal = options.signal;
  let timedOut = false;
  const abortFromExternal = () => controller.abort();
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  if (externalSignal?.aborted) {
    controller.abort();
  } else {
    externalSignal?.addEventListener("abort", abortFromExternal, { once: true });
  }

  const { signal, ...fetchOptions } = options;
  try {
    const response = await fetch(url, { ...fetchOptions, credentials: "same-origin", signal: controller.signal });
    if (!response.ok) {
      return parseResponse(response);
    }
    if (!response.body) {
      throw new Error("浏览器不支持流式响应");
    }
    return await readNdjson(response.body, onEvent);
  } catch (error) {
    if (error?.name === "AbortError" && timedOut) {
      throw new Error("请求超时，请确认后端 http://127.0.0.1:8000 已启动");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
    externalSignal?.removeEventListener("abort", abortFromExternal);
  }
}

async function parseResponse(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(safeHttpErrorMessage(response.status));
  }
  return payload;
}

function safeHttpErrorMessage(status) {
  const messages = {
    400: "请求参数无效，请检查输入后重试",
    401: "登录已失效，请重新登录",
    403: "当前账号没有权限执行此操作",
    404: "请求的资源不存在或无权访问",
    409: "资源状态冲突，请刷新后重试",
    413: "请求内容过大，请减少画布内容后重试",
    422: "提交内容不符合要求，请检查输入",
    429: "请求过于频繁，请稍后重试",
  };
  return messages[status] || `请求失败，请稍后重试（HTTP ${status}）`;
}

async function readNdjson(body, onEvent) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let lastEvent = null;

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = done ? "" : lines.pop() || "";

    for (const line of lines) {
      const event = parseNdjsonLine(line);
      if (event) {
        lastEvent = event;
        onEvent?.(event);
      }
    }

    if (done) {
      break;
    }
  }

  const event = parseNdjsonLine(buffer);
  if (event) {
    lastEvent = event;
    onEvent?.(event);
  }
  return lastEvent;
}

function parseNdjsonLine(line) {
  const cleanLine = line.trim();
  if (!cleanLine) {
    return null;
  }
  try {
    return JSON.parse(cleanLine);
  } catch {
    throw new Error("流式响应格式无效");
  }
}

export function isAbortError(error) {
  return error?.name === "AbortError";
}

export function requestErrorMessage(error, fallback) {
  if (error?.message?.includes("Failed to fetch")) {
    return `${fallback}：无法连接后端，请用 npm run dev 同时启动前后端`;
  }
  return error?.message || fallback;
}
