import { api } from "../api.js";
import { meter, passage } from "../components.js";
import { clear, h, rise } from "../dom.js";

const MODES = [
  ["vector", "Vector"],
  ["lexical", "Lexical"],
  ["hybrid", "Hybrid"],
];

const SCORE_NOTE = {
  vector: "Ranked by cosine similarity of meaning.",
  lexical: "Ranked by PostgreSQL full-text score (keyword overlap). That bar is drawn relative to the best result; the number is the raw score. Cosine is shown for reference.",
  hybrid: "Ranked by Reciprocal Rank Fusion of both lists. The fused score has no fixed scale (its bar is relative to the best result), so only the cosine bar is comparable across queries.",
};

export function mountSearch(root, ctx, params) {
  const defaultMode = ctx.status?.config.retrieval_mode ?? "vector";
  const input = h("input", {
    id: "sq",
    class: "field",
    type: "search",
    placeholder: "poison stack limit",
    value: params.get("q") ?? "",
    autocomplete: "off",
  });
  const topK = h(
    "select",
    { class: "field", id: "topk", "aria-label": "Number of results" },
    [5, 10, 20].map((n) => h("option", { value: n }, `top ${n}`)),
  );
  const modeRadios = MODES.map(([value, label]) =>
    h(
      "label",
      {},
      h("input", { type: "radio", name: "mode", value, checked: value === defaultMode }),
      h("span", {}, label),
    ),
  );
  const out = h("section", { class: "result", "aria-live": "polite" });
  const currentMode = () => document.querySelector("input[name=mode]:checked")?.value ?? defaultMode;

  async function run(event) {
    event?.preventDefault();
    const query = input.value.trim();
    if (!query) return;
    const mode = currentMode();
    clear(out).append(h("p", { class: "status-line" }, "Searching…"));
    try {
      const started = performance.now();
      const res = await api.search(query, mode, Number(topK.value));
      const ms = performance.now() - started;
      clear(out);
      if (res.hits.length === 0) {
        out.append(
          h(
            "div",
            { class: "empty" },
            h("p", {}, "No passages matched."),
            mode === "vector" || mode === "hybrid"
              ? h("p", {}, "Vector search only sees embedded passages. Embed pending passages on the System page.")
              : null,
          ),
        );
        return;
      }
      const best = Math.max(...res.hits.map((hit) => hit.score));
      out.append(
        h("p", { class: "status-line" }, `${res.hits.length} passages · ${mode} · ${ms.toFixed(0)} ms`),
        h(
          "ol",
          { class: "hits" },
          res.hits.map((hit, i) =>
            passage({
              ref: i + 1,
              variant: "hit",
              chunkId: hit.chunk_id,
              content: hit.content,
              citation: hit.citation,
              meters: [
                mode === "vector"
                  ? null
                  : meter(mode === "lexical" ? "ts_rank" : "rrf", hit.score, "", best),
                hit.cosine === null
                  ? h("span", { class: "hint" }, "not embedded")
                  : meter("cos", hit.cosine, "cos"),
              ],
              ctx,
            }),
          ),
        ),
        h("p", { class: "note" }, SCORE_NOTE[mode]),
      );
    } catch (error) {
      clear(out).append(
        h(
          "div",
          { class: "error-panel", role: "alert" },
          h("strong", {}, error.status === 503 ? "Embedding service unavailable" : "Search failed"),
          h("p", {}, error.message),
        ),
      );
    }
  }

  clear(root).append(
    rise(
      h(
        "div",
        { class: "view-head" },
        h("h1", {}, "Search the ", h("em", {}, "passages")),
        h(
          "p",
          { class: "lede" },
          "The retrieval step on its own, before any model writes an answer. Compare vector, lexical and hybrid ranking on the same query.",
        ),
      ),
    ),
    rise(
      h(
        "form",
        { onSubmit: run },
        h("label", { class: "label", for: "sq" }, "Query"),
        input,
        h(
          "div",
          { class: "form-row" },
          h("div", { class: "seg", role: "radiogroup", "aria-label": "Retrieval mode" }, modeRadios),
          topK,
          h("button", { class: "btn btn-primary", type: "submit" }, "Search"),
        ),
      ),
      1,
    ),
    out,
  );
  if (input.value) run();
  else input.focus();
}
