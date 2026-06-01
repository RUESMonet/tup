import { getJson, postJson, setSessionToken } from "./client";

export async function registerAccount(payload) {
  return postJson("/api/auth/register", payload);
}

export async function loginAccount(payload) {
  return postJson("/api/auth/login", payload);
}

export async function logoutAccount() {
  await postJson("/api/auth/logout", {});
  setSessionToken("");
}

export async function fetchCurrentUser() {
  return getJson("/api/auth/me");
}
