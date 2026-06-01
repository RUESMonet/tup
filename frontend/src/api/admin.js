import { getJson, postJson } from "./client";

export async function fetchModelSettings() {
  return getJson("/api/admin/model-settings");
}

export async function updateModelSettings(payload) {
  return postJson("/api/admin/model-settings", payload);
}
