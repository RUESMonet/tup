export const terminalStatuses = new Set(["succeeded", "failed"]);
export const POLL_INTERVAL_MS = 1200;
export const REQUEST_TIMEOUT_MS = 15000;
export const fallbackModels = [{ id: "openai", provider_model: "gpt-image-2", configured: false }];
export const defaultPrompt =
  "一张现代香水产品海报，透明玻璃瓶置于浅灰色石材台面，柔和棚拍灯光，细腻反射，高级商业摄影，避免文字水印和标签变形";
