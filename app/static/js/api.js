export class ApiError extends Error {
  constructor(status, detail) {
    super(describe(detail));
    this.status = status;
    this.detail = detail;
  }
}

function describe(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg ?? JSON.stringify(d)).join("; ");
  if (detail && typeof detail === "object" && detail.message) return detail.message;
  return "Request failed";
}

// The API key lives in this module's memory. It is only written to sessionStorage (cleared when the
// tab closes) if the user explicitly ticks "keep me signed in for this tab". It is never put in
// localStorage, a cookie, or the URL.
const STORAGE_KEY = "aijp.key";
let apiKey = null;

export const auth = {
  /** Called when a request made WITH a key is rejected (revoked, expired, or mistyped). */
  onUnauthorized: null,
  set(key, remember = false) {
    apiKey = key;
    try {
      if (remember) sessionStorage.setItem(STORAGE_KEY, key);
      else sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* storage unavailable: the key simply stays in memory */
    }
  },
  restore() {
    try {
      apiKey = sessionStorage.getItem(STORAGE_KEY);
    } catch {
      apiKey = null;
    }
    return apiKey;
  },
  clear() {
    apiKey = null;
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* nothing to clear */
    }
  },
  get signedIn() {
    return apiKey !== null;
  },
};

// The project the user is working in. It is a slug (not a secret), so remembering it in
// localStorage is a per-viewer convenience; the server decides what the key may actually reach.
const PROJECT_KEY = "aijp.project";
let currentProject = null;

export const project = {
  get() {
    return currentProject;
  },
  set(slug) {
    currentProject = slug;
    try {
      if (slug) localStorage.setItem(PROJECT_KEY, slug);
    } catch {
      /* storage unavailable: the choice just lasts until reload */
    }
  },
  remembered() {
    try {
      return localStorage.getItem(PROJECT_KEY);
    } catch {
      return null;
    }
  },
};

// Endpoints that are about the caller or the service, not about one project's data.
const UNSCOPED = ["/auth/", "/projects", "/health", "/eval/"];

function scoped(path) {
  if (!currentProject || UNSCOPED.some((prefix) => path.startsWith(prefix))) return path;
  return `${path}${path.includes("?") ? "&" : "?"}project=${encodeURIComponent(currentProject)}`;
}

async function request(path, options = {}) {
  path = scoped(path);
  const headers = new Headers(options.headers);
  if (apiKey) headers.set("Authorization", `Bearer ${apiKey}`);
  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(0, "Cannot reach the server");
  }
  if (response.status === 204) return null;
  let body = null;
  try {
    body = await response.json();
  } catch {
    /* non-JSON error body */
  }
  if (!response.ok) {
    if (response.status === 401 && apiKey && !path.startsWith("/auth/me")) auth.onUnauthorized?.();
    throw new ApiError(response.status, body?.detail ?? response.statusText);
  }
  return body;
}

const json = (payload, signal) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
  signal,
});

export const api = {
  authConfig: () => request("/auth/config"),
  me: () => request("/auth/me"),
  projects: () => request("/projects"),
  status: () => request("/status"),
  ask: (question, signal) => request("/ask", json({ question }, signal)),
  search: (query, mode, topK) => request("/search", json({ query, mode, top_k: topK })),

  /** All documents, following pagination (the API caps a page at 200). */
  async documents() {
    const items = [];
    for (let offset = 0; ; offset += 200) {
      const page = await request(`/documents?limit=200&offset=${offset}`);
      items.push(...page.items);
      if (items.length >= page.total || page.items.length === 0) return items;
    }
  },
  document: (id) => request(`/documents/${encodeURIComponent(id)}`),
  remove: (id) => request(`/documents/${encodeURIComponent(id)}`, { method: "DELETE" }),
  upload(file, sourcePath) {
    const form = new FormData();
    form.append("file", file, file.name);
    if (sourcePath) form.append("source_path", sourcePath);
    return request("/documents", { method: "POST", body: form });
  },
  embed: () => request("/embeddings", { method: "POST" }),

  verify: (claim, signal) => request("/agent/consistency-checks", json({ claim }, signal)),
  runs: () => request("/agent/runs?limit=20"),
  run: (id) => request(`/agent/runs/${encodeURIComponent(id)}`),
  approve: (id) => request(`/agent/actions/${encodeURIComponent(id)}/approve`, { method: "POST" }),
  reject: (id) => request(`/agent/actions/${encodeURIComponent(id)}/reject`, { method: "POST" }),
  tasks: () => request("/agent/tasks"),

  reports: () => request("/eval/reports"),
  report: (name) => request(`/eval/reports/${encodeURIComponent(name)}`),
};
