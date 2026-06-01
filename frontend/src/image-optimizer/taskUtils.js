export function imageSource(task) {
  if (!task) {
    return "";
  }
  if (task.image_b64_json) {
    return `data:${task.image_media_type || "image/png"};base64,${task.image_b64_json}`;
  }
  if (task.image_url && !task.image_url.startsWith("mock://")) {
    return task.image_url;
  }
  return "";
}

export function normalizeNumber(value, fallback) {
  if (value === "") {
    return fallback;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}
