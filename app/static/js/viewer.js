// The source drawer: a whole document as its stored chunks, with the cited one highlighted and
// scrolled into view. This is what makes a citation verifiable rather than decorative.

import { api } from "./api.js";
import { $, clear, h } from "./dom.js";
import { bytes, locator } from "./format.js";

let opener = null;

function codeBlock(chunk) {
  const start = chunk.start_line ?? 1;
  return h(
    "div",
    { class: "code", role: "region", "aria-label": "Passage text" },
    chunk.content.split("\n").map((line, i) =>
      h(
        "div",
        { class: "row" },
        h("span", { class: "ln", "aria-hidden": "true" }, String(start + i)),
        h("span", { class: "lt" }, line === "" ? " " : line),
      ),
    ),
  );
}

function chunkView(chunk, targetId) {
  const isTarget = chunk.id === targetId;
  const where = locator(chunk);
  return h(
    "section",
    { class: `chunk ${isTarget ? "is-target" : ""}`, id: `chunk-${chunk.id}` },
    h(
      "div",
      { class: "chunk-head" },
      h("span", {}, `#${chunk.chunk_index}`),
      chunk.section ? h("span", {}, chunk.section) : null,
      where ? h("span", {}, where) : null,
      isTarget ? h("strong", {}, "cited passage") : null,
    ),
    codeBlock(chunk),
  );
}

function close() {
  const viewer = $("#viewer");
  viewer.hidden = true;
  document.body.removeEventListener("keydown", onKey);
  if (opener && document.contains(opener)) opener.focus();
  opener = null;
}

function onKey(event) {
  if (event.key === "Escape") close();
  if (event.key !== "Tab") return;
  // Keep focus inside the dialog while it is open.
  const focusable = [...$("#viewer").querySelectorAll("button, [href], [tabindex]")].filter(
    (el) => !el.disabled && el.tabIndex >= 0,
  );
  if (focusable.length === 0) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

export function initViewer() {
  $("#viewer-close").addEventListener("click", close);
  $("#viewer [data-close]").addEventListener("click", close);
}

export async function openSource(documentId, chunkId = null) {
  const viewer = $("#viewer");
  const body = clear($("#viewer-body"));
  opener = document.activeElement;
  $("#viewer-title").textContent = "Loading…";
  $("#viewer-sub").textContent = "";
  viewer.hidden = false;
  document.body.addEventListener("keydown", onKey);
  $("#viewer-close").focus();

  try {
    const doc = await api.document(documentId);
    $("#viewer-title").textContent = doc.source_path;
    $("#viewer-sub").textContent =
      `${doc.file_type.toUpperCase()} · ${doc.chunk_count} passages · ${bytes(doc.size_bytes)} · sha256 ${doc.sha256.slice(0, 12)}`;
    body.append(...doc.chunks.map((c) => chunkView(c, chunkId)));
    const target = chunkId ? document.getElementById(`chunk-${chunkId}`) : null;
    if (target) target.scrollIntoView({ block: "center" });
  } catch (error) {
    $("#viewer-title").textContent = "Could not load source";
    body.append(
      h(
        "div",
        { class: "error-panel" },
        h("strong", {}, error.status === 404 ? "Document no longer exists" : "Error"),
        h("p", {}, error.message),
      ),
    );
  }
}
