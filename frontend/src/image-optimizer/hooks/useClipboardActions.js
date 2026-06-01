import { formatGuide, readablePromptText } from "../promptFormatting";

export function useClipboardActions({ prompt, task, guide, onStatus }) {
  async function copyFinalPrompt() {
    const text = task?.final_prompt ? readablePromptText(task.final_prompt) : prompt;
    try {
      await navigator.clipboard.writeText(text);
      onStatus({ kind: "ready", message: "提示词已复制" });
    } catch {
      onStatus({ kind: "failed", message: "浏览器拒绝复制，请手动选择文本" });
    }
  }

  async function copyGuide() {
    if (!guide) {
      return;
    }
    try {
      await navigator.clipboard.writeText(formatGuide(guide));
      onStatus({ kind: "ready", message: "优化指南已复制" });
    } catch {
      onStatus({ kind: "failed", message: "浏览器拒绝复制，请手动选择文本" });
    }
  }

  return { copyFinalPrompt, copyGuide };
}
