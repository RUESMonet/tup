export function readablePromptText(value) {
  if (typeof value !== "string") {
    return "";
  }
  try {
    const payload = JSON.parse(value);
    return candidatePromptText(payload);
  } catch {
    return value;
  }
}

export function promptForRequest(prompt, activePromptPayload) {
  return activePromptPayload ? JSON.stringify(activePromptPayload) : prompt.trim();
}

export function promptJsonText(payload) {
  if (typeof payload === "string") {
    try {
      return JSON.stringify(JSON.parse(payload), null, 2);
    } catch {
      return JSON.stringify({ prompt: { raw_text: payload } }, null, 2);
    }
  }
  return JSON.stringify(payload || {}, null, 2);
}

export function candidatePromptText(payload) {
  if (typeof payload === "string") {
    return payload;
  }
  const promptPayload = payload?.prompt;
  if (!promptPayload || typeof promptPayload !== "object") {
    return JSON.stringify(payload, null, 2);
  }
  if (typeof promptPayload.raw_text === "string" && promptPayload.raw_text.trim()) {
    return promptPayload.raw_text;
  }

  return [
    promptTextLine("subject", promptPayload.subject),
    promptTextLine("environment", promptPayload.environment),
    promptTextLine("style", promptPayload.style),
    promptTextLine("lighting", promptPayload.lighting),
    promptTextLine("camera and composition", promptPayload.camera_and_composition),
    promptTextLine("atmosphere", promptPayload.atmosphere),
    promptTextLine("color palette", promptPayload.color_palette),
    promptTextLine("text and logo constraints", promptPayload.text_and_logo_constraints),
    promptTextLine("scene constraints", promptPayload.scene_constraints || promptPayload.constraints),
    promptTextLine("negative prompt", negativePromptValue(promptPayload.negative_prompt)),
  ]
    .filter(Boolean)
    .join("\n");
}

function promptTextLine(label, value) {
  const items = (Array.isArray(value) ? value : [value]).filter((item) => typeof item === "string" && item.trim());
  return items.length ? `${label}: ${items.join("; ")}` : "";
}

function negativePromptValue(value) {
  if (typeof value === "string") {
    return stripNegativePromptPrefix(value);
  }
  return Array.isArray(value) ? value.map((item) => (typeof item === "string" ? stripNegativePromptPrefix(item) : item)) : value;
}

function stripNegativePromptPrefix(value) {
  return value.replace(/^negative prompt:\s*/i, "");
}

export function summarizeCandidate(candidate) {
  if (candidate.summary && typeof candidate.summary === "object") {
    return Object.entries(candidate.summary)
      .slice(0, 3)
      .map(([key, value]) => `${key}: ${value}`)
      .join(" / ");
  }
  return "候选提示词";
}

export function formatGuide(guide) {
  const issues = (guide.issues || []).map((issue, index) => `${index + 1}. ${issue.title}：${issue.detail}`);
  const actions = (guide.actions || []).map((action, index) => {
    const example = action.example ? `\n   示例：${action.example}` : "";
    return `${index + 1}. ${action.title}：${action.instruction}${example}`;
  });
  const nextSteps = (guide.next_steps || []).map((step, index) => `${index + 1}. ${step}`);

  return [
    "优化指南",
    guide.summary || "",
    issues.length ? `\n主要问题\n${issues.join("\n")}` : "",
    actions.length ? `\n建议动作\n${actions.join("\n")}` : "",
    nextSteps.length ? `\n下一步\n${nextSteps.join("\n")}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}
