import { api, auth } from "./api.js";
import { $, h } from "./dom.js";
import { initViewer, openSource } from "./viewer.js";
import { mountAsk } from "./views/ask.js";
import { mountDocuments } from "./views/documents.js";
import { mountEvaluation } from "./views/evaluation.js";
import { mountLogin } from "./views/login.js";
import { mountSearch } from "./views/search.js";
import { mountSystem } from "./views/system.js";
import { mountVerify } from "./views/verify.js";

const ROUTES = {
  ask: { title: "Ask", mount: mountAsk },
  search: { title: "Search", mount: mountSearch },
  verify: { title: "Verify", mount: mountVerify },
  documents: { title: "Documents", mount: mountDocuments },
  evaluation: { title: "Evaluation", mount: mountEvaluation },
  system: { title: "System", mount: mountSystem },
};

const RANK = { reader: 1, editor: 2, approver: 3 };

const ctx = {
  status: null, // last /status payload (null until the first success)
  state: { askHistory: [] }, // survives navigation, lost on reload (nothing is persisted)
  authEnabled: true, // from /auth/config; the server enforces, this only shapes the UI
  me: null, // { name, role, key_prefix } once signed in
  loginNotice: null,
  openSource,

  /** Can the signed-in key do things that need `role`? (The server checks again on every call.) */
  can(role) {
    if (!this.authEnabled) return true;
    return (RANK[this.me?.role] ?? 0) >= RANK[role];
  },

  async refreshStatus() {
    try {
      this.status = await api.status();
    } catch (error) {
      this.status = null; // do not keep showing a stale "all good"
      renderSpineStatus();
      throw error;
    }
    renderSpineStatus();
    return this.status;
  },

  toast(message, kind = "ok") {
    const el = h("div", { class: `toast ${kind === "bad" ? "bad" : ""}` }, message);
    $("#toasts").append(el);
    setTimeout(() => el.remove(), 4500);
  },

  /** Verify a key with the server; on success it becomes the session's identity. */
  async signIn(key, remember) {
    auth.set(key, remember);
    try {
      this.me = await api.me();
    } catch (error) {
      auth.clear();
      this.me = null;
      throw error;
    }
    this.loginNotice = null;
    await afterSignIn();
  },

  signOut() {
    auth.clear();
    this.me = null;
    this.status = null;
    this.state.askHistory = [];
    renderSpineStatus();
    route();
  },
};

function renderBanner() {
  const banner = $("#auth-banner");
  banner.hidden = ctx.authEnabled;
  banner.textContent = ctx.authEnabled
    ? ""
    : "Authentication is OFF. Anyone who can reach this server can upload, delete and approve. Use this only on a machine nobody else can reach.";
}

function renderSpineStatus() {
  const foot = $("#spine-foot");
  foot.replaceChildren();
  const line = (ok, text) =>
    h("div", { class: "line" }, h("span", { class: `dot ${ok === null ? "" : ok ? "ok" : "bad"}` }), text);

  if (ctx.authEnabled && ctx.me) {
    foot.append(
      h(
        "div",
        { class: "who" },
        h("strong", {}, ctx.me.name),
        h("span", { class: "role-tag" }, ctx.me.role),
        h("button", { class: "link-btn", type: "button", onClick: () => ctx.signOut() }, "Sign out"),
      ),
    );
  }
  if (ctx.authEnabled && !ctx.me) return; // nothing to report until signed in
  const s = ctx.status;
  if (!s) {
    foot.append(line(false, "API unreachable"));
    return;
  }
  const modelsOk = s.ollama.reachable && s.ollama.models.every((m) => m.installed);
  foot.append(
    line(s.database.reachable && s.database.pgvector, `database · ${s.database.documents} docs`),
    line(modelsOk, `ollama · ${s.ollama.reachable ? (modelsOk ? "ready" : "model missing") : "down"}`),
    line(s.database.pending_chunks === 0, s.database.pending_chunks ? `${s.database.pending_chunks} to embed` : "all embedded"),
  );
}

function parseHash() {
  const [path, query = ""] = location.hash.replace(/^#\/?/, "").split("?");
  return { name: ROUTES[path] ? path : "ask", params: new URLSearchParams(query) };
}

async function route() {
  const main = $("#main");
  const locked = ctx.authEnabled && !ctx.me;
  document.body.classList.toggle("is-locked", locked);
  if (locked) {
    document.title = "Sign in · Project Intelligence";
    for (const link of document.querySelectorAll("#nav a")) {
      link.classList.remove("is-active");
      link.setAttribute("tabindex", "-1");
    }
    await mountLogin(main, ctx);
    return;
  }
  const { name, params } = parseHash();
  const view = ROUTES[name];
  for (const link of document.querySelectorAll("#nav a")) {
    const active = link.dataset.route === name;
    link.classList.toggle("is-active", active);
    link.removeAttribute("tabindex");
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  document.title = `${view.title} · Project Intelligence`;
  await view.mount(main, ctx, params);
  window.scrollTo(0, 0);
}

async function afterSignIn() {
  renderSpineStatus();
  // Mount first, refresh status in the background. Waiting for /status (which probes Ollama and
  // can take a couple of seconds) before mounting made sign-in feel stuck, and let a delayed
  // mount replace a page the user had already started working in, wiping its state.
  await route();
  ctx.refreshStatus().catch(() => {
    /* the spine shows "API unreachable"; views report their own errors */
  });
}

async function boot() {
  initViewer();
  try {
    ctx.authEnabled = (await api.authConfig()).auth_enabled;
  } catch {
    ctx.authEnabled = true; // if we cannot tell, behave as if authentication is required
  }
  renderBanner();

  // A key rejected mid-session (revoked, expired) sends the user back to sign in.
  auth.onUnauthorized = () => {
    auth.clear();
    ctx.me = null;
    ctx.loginNotice = "Your key was rejected. It may have been revoked or expired. Sign in again.";
    renderSpineStatus();
    route();
  };

  if (ctx.authEnabled && auth.restore()) {
    try {
      ctx.me = await api.me();
    } catch {
      auth.clear();
      ctx.me = null;
    }
  } else if (!ctx.authEnabled) {
    ctx.me = await api.me().catch(() => null);
  }

  window.addEventListener("hashchange", route);
  await afterSignIn();
  // Keep the sidebar indicators honest without hammering the API (and never while signed out).
  setInterval(() => {
    if (!document.hidden && (!ctx.authEnabled || ctx.me)) ctx.refreshStatus().catch(renderSpineStatus);
  }, 30000);
}

boot();
