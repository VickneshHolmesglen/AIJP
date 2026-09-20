import { h } from "./dom.js";
import { clamp01, clip, locator, score } from "./format.js";

/** path · section · lines, the identity of a passage. The vermilion part is the line range. */
export function provenance(citation) {
  return h(
    "div",
    { class: "prov" },
    h("span", { class: "path" }, citation.source_path),
    citation.section ? h("span", { class: "sec" }, citation.section) : null,
    locator(citation) ? h("span", { class: "lines" }, locator(citation)) : null,
  );
}

/**
 * A labelled bar. The label always shows the RAW value; `max` only scales the bar (default 1, so
 * cosine is absolute). `kind` "cos" paints it in the accent colour.
 */
export function meter(label, value, kind = "", max = 1) {
  const fill = h("span", { class: "meter-fill" });
  fill.style.width = `${(clamp01(max > 0 ? value / max : 0) * 100).toFixed(1)}%`;
  return h(
    "div",
    { class: `meter ${kind === "cos" ? "is-cos" : ""}`, title: `${label} ${score(value)}` },
    h("span", { class: "meter-bar", "aria-hidden": "true" }, fill),
    h("span", { class: "meter-label" }, `${label} ${score(value)}`),
  );
}

/**
 * One retrieved passage. `ref` is the number the answer cites as [n] (or the rank on the Search
 * page). Clicking "Open in context" shows the passage inside its whole document.
 */
export function passage({ ref, variant = "source", chunkId, content, citation, meters, ctx }) {
  // "source": a cited passage of an answer (big italic numeral). "hit": a search result (rank).
  return h(
    "li",
    { class: variant, id: variant === "source" ? `src-${ref}` : null },
    h("div", { class: variant === "source" ? "ref" : "rank" }, String(ref)),
    h(
      "div",
      { class: "src-body" },
      provenance(citation),
      h("p", { class: "snippet" }, clip(content, 360)),
      h(
        "div",
        { class: "src-foot" },
        meters,
        h(
          "button",
          {
            class: "btn btn-small",
            type: "button",
            onClick: () => ctx.openSource(citation.document_id, chunkId),
          },
          "Open in context",
        ),
      ),
    ),
  );
}
