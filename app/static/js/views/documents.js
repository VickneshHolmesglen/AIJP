import { api } from "../api.js";
import { clear, h, rise } from "../dom.js";
import { basename, bytes, dirname, shortDate } from "../format.js";

const ALLOWED = new Set(["pdf", "txt", "md", "py", "gd", "json", "yaml", "yml"]);
const ACCEPT = [...ALLOWED].map((e) => `.${e}`).join(",");
// Directories that are never worth indexing when a whole project folder is chosen.
const JUNK = /(^|\/)(\.[^/]+|node_modules|__pycache__|venv|dist|build|target)\//;

const extOf = (name) => name.slice(name.lastIndexOf(".") + 1).toLowerCase();

export async function mountDocuments(root, ctx) {
  let docs = [];
  let filter = "";
  const tableHost = h("section", { "aria-live": "polite" });
  const banner = h("div");
  const queue = h("ul", { class: "queue", hidden: true, "aria-label": "Upload progress" });

  const fileInput = h("input", { type: "file", multiple: true, accept: ACCEPT, hidden: true });
  const folderInput = h("input", { type: "file", webkitdirectory: true, hidden: true });

  // ---- upload -----------------------------------------------------------------------------
  async function uploadAll(files) {
    const maxBytes = ctx.status?.config.max_upload_bytes ?? Infinity;
    const skipped = { type: 0, junk: 0, size: 0 };
    const usable = [];
    for (const file of files) {
      const path = file.webkitRelativePath || file.name;
      if (JUNK.test(path)) skipped.junk += 1;
      else if (!ALLOWED.has(extOf(file.name))) skipped.type += 1;
      else if (file.size > maxBytes) skipped.size += 1;
      else usable.push(file);
    }
    clear(queue).hidden = false;
    const counts = { added: 0, duplicate: 0, failed: 0 };
    for (const file of usable) {
      const path = file.webkitRelativePath || "";
      const glyph = h("span", {}, "…");
      const state = h("span", {}, "uploading");
      const row = h("li", {}, glyph, h("span", { class: "path" }, path || file.name), state);
      queue.append(row);
      queue.scrollTop = queue.scrollHeight;
      try {
        await api.upload(file, path || null);
        counts.added += 1;
        row.className = "ok";
        glyph.textContent = "✓";
        state.textContent = "added";
      } catch (error) {
        if (error.status === 409) {
          counts.duplicate += 1;
          row.className = "warn";
          glyph.textContent = "=";
          state.textContent = "already indexed";
        } else {
          counts.failed += 1;
          row.className = "bad";
          glyph.textContent = "✕";
          state.textContent = error.message;
        }
      }
    }
    const notes = [];
    if (skipped.type) notes.push(`${skipped.type} unsupported type`);
    if (skipped.junk) notes.push(`${skipped.junk} in hidden/build folders`);
    if (skipped.size) notes.push(`${skipped.size} over the size limit`);
    if (notes.length) {
      queue.append(h("li", {}, h("span", {}, "–"), h("span", { class: "path" }, `Skipped: ${notes.join(", ")}`), h("span", {})));
    }
    ctx.toast(
      `${counts.added} added, ${counts.duplicate} already indexed, ${counts.failed} failed`,
      counts.failed ? "bad" : "ok",
    );
    await refresh();
  }

  // The server enforces roles on every call; the UI just avoids offering what would be refused.
  const canEdit = ctx.can("editor");
  const dropzone = !canEdit
    ? h(
        "div",
        { class: "role-note" },
        `Your key (${ctx.me?.role ?? "reader"}) can read the corpus but not change it. Ask for an editor key to upload, delete or embed documents.`,
      )
    : h(
    "div",
    { class: "dropzone" },
    h(
      "p",
      {},
      "Drop files here, or add a whole project folder. Supported: PDF, TXT, Markdown, Python, GDScript, JSON, YAML. ",
      "Each file is validated before parsing, and folder paths become the citation paths.",
    ),
    h(
      "div",
      { class: "btns" },
      h("button", { class: "btn", type: "button", onClick: () => fileInput.click() }, "Add files"),
      h("button", { class: "btn", type: "button", onClick: () => folderInput.click() }, "Add folder"),
    ),
  );
  if (canEdit) {
    for (const type of ["dragenter", "dragover"]) {
      dropzone.addEventListener(type, (e) => {
        e.preventDefault();
        dropzone.classList.add("is-over");
      });
    }
    for (const type of ["dragleave", "drop"]) {
      dropzone.addEventListener(type, () => dropzone.classList.remove("is-over"));
    }
    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      uploadAll([...e.dataTransfer.files]);
    });
    for (const input of [fileInput, folderInput]) {
      input.addEventListener("change", () => {
        const files = [...input.files];
        input.value = "";
        if (files.length) uploadAll(files);
      });
    }
  }

  // ---- embedding banner ------------------------------------------------------------------
  function renderBanner() {
    clear(banner);
    const pending = ctx.status?.database.pending_chunks ?? 0;
    if (!pending || !canEdit) return;
    const button = h("button", { class: "btn btn-primary", type: "button" }, `Embed ${pending} passages`);
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "Embedding…";
      try {
        const { embedded } = await api.embed();
        ctx.toast(`Embedded ${embedded} passages`, "ok");
      } catch (error) {
        ctx.toast(error.message, "bad");
      }
      await refresh();
    });
    banner.append(
      h(
        "div",
        { class: "banner" },
        h("p", {}, `${pending} passages are stored but not yet embedded, so vector search and Ask cannot see them.`),
        button,
      ),
    );
  }

  // ---- table -----------------------------------------------------------------------------
  function armedDelete(doc) {
    const button = h("button", { class: "btn btn-small btn-danger", type: "button" }, "Delete");
    let timer = null;
    button.addEventListener("click", async () => {
      if (!button.classList.contains("is-armed")) {
        button.classList.add("is-armed");
        button.textContent = "Confirm?";
        timer = setTimeout(() => {
          button.classList.remove("is-armed");
          button.textContent = "Delete";
        }, 3000);
        return;
      }
      clearTimeout(timer);
      try {
        await api.remove(doc.id);
        ctx.toast(`Deleted ${doc.source_path}`, "ok");
      } catch (error) {
        ctx.toast(error.message, "bad");
      }
      await refresh();
    });
    return button;
  }

  function renderTable() {
    clear(tableHost);
    const needle = filter.trim().toLowerCase();
    const shown = docs
      .filter((d) => !needle || d.source_path.toLowerCase().includes(needle))
      .sort((a, b) => a.source_path.localeCompare(b.source_path));
    if (docs.length === 0) {
      tableHost.append(
        h(
          "div",
          { class: "empty" },
          h("p", {}, "Nothing is indexed yet."),
          h("p", {}, "Add files or a project folder above. Then embed them, and ask a question."),
        ),
      );
      return;
    }
    if (shown.length === 0) {
      tableHost.append(h("div", { class: "empty" }, `No documents match “${filter}”.`));
      return;
    }
    const rows = [];
    let lastDir = null;
    for (const doc of shown) {
      const dir = dirname(doc.source_path);
      if (dir !== lastDir) {
        rows.push(h("tr", { class: "group" }, h("td", { colspan: "6" }, dir ? `${dir}/` : "(root)")));
        lastDir = dir;
      }
      rows.push(
        h(
          "tr",
          {},
          h("td", {}, h("span", { class: "fname" }, basename(doc.source_path))),
          h("td", {}, h("span", { class: "badge" }, doc.file_type)),
          h("td", { class: "num" }, String(doc.chunk_count)),
          h("td", { class: "num" }, bytes(doc.size_bytes)),
          h("td", { class: "muted" }, shortDate(doc.created_at)),
          h(
            "td",
            {},
            h(
              "div",
              { class: "row-actions" },
              h(
                "button",
                { class: "btn btn-small", type: "button", onClick: () => ctx.openSource(doc.id) },
                "View",
              ),
              canEdit ? armedDelete(doc) : null,
            ),
          ),
        ),
      );
    }
    tableHost.append(
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          {},
          h("caption", { class: "sr-only" }, "Indexed documents"),
          h(
            "thead",
            {},
            h(
              "tr",
              {},
              h("th", {}, "File"),
              h("th", {}, "Type"),
              h("th", { class: "num" }, "Passages"),
              h("th", { class: "num" }, "Size"),
              h("th", {}, "Added"),
              h("th", {}, h("span", { class: "sr-only" }, "Actions")),
            ),
          ),
          h("tbody", {}, rows),
        ),
      ),
    );
  }

  async function refresh() {
    try {
      docs = await api.documents();
    } catch (error) {
      clear(tableHost).append(
        h("div", { class: "error-panel", role: "alert" }, h("strong", {}, "Could not load documents"), h("p", {}, error.message)),
      );
      return;
    }
    renderTable(); // table first: the Ollama health probe behind /status can be slow
    renderBanner();
    ctx
      .refreshStatus()
      .then(renderBanner)
      .catch(() => {});
  }

  const filterInput = h("input", {
    class: "field",
    type: "search",
    placeholder: "Filter by path…",
    "aria-label": "Filter documents by path",
    onInput: (e) => {
      filter = e.target.value;
      renderTable();
    },
  });

  clear(root).append(
    rise(
      h(
        "div",
        { class: "view-head" },
        h("h1", {}, "The ", h("em", {}, "corpus")),
        h(
          "p",
          { class: "lede" },
          "Everything Ask and Search can see. Source files are split by function and class, documents by heading, so a citation can name the exact place.",
        ),
      ),
    ),
    rise(dropzone, 1),
    fileInput,
    folderInput,
    queue,
    banner,
    h("div", { class: "toolbar" }, h("span", { class: "label" }, "Indexed documents"), filterInput),
    tableHost,
  );
  tableHost.append(h("p", { class: "status-line" }, "Loading documents…"));
  await refresh();
}
