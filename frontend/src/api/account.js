import { getJson } from "./client";

export function fetchAccountCredits() {
  return getJson("/api/account/credits");
}

export function fetchAccountTransactions(params = {}) {
  const search = new URLSearchParams();
  if (params.projectId) {
    search.set("project_id", params.projectId);
  }
  if (params.limit) {
    search.set("limit", String(params.limit));
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return getJson(`/api/account/transactions${suffix}`);
}
