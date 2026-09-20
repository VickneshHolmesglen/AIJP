import { api } from "../api.js";
import { clear, h, rise } from "../dom.js";
import { renderMarkdown } from "../markdown.js";

const KIND_LABEL = {
  qa: "Answer quality",
  retrieval: "Retrieval benchmark",
  consistency: "Design vs code",
};

export async function mountEvaluation(root, ctx) {
  const list = h("ul", { class: "report-list", "aria-label": "Reports" });
  const content = h("section", { "aria-live": "polite" });
  const layout = h("div", { class: "eval-layout" }, list, content);

  clear(root).append(
    rise(
      h(
        "div",
        { class: "view-head" },
        h("h1", {}, h("em", {}, "Measured"), ", not claimed"),
        h(
          "p",
          { class: "lede" },
          "Every number on this page was produced by the evaluation tooling and is shown exactly as written. Nothing here is typed in by hand.",
        ),
      ),
    ),
    layout,
  );

  let reports;
  try {
    reports = (await api.reports()).items;
  } catch (error) {
    content.append(h("div", { class: "error-panel", role: "alert" }, h("strong", {}, "Could not load reports"), h("p", {}, error.message)));
    return;
  }

  if (reports.length === 0) {
    clear(layout).append(
      h(
        "div",
        { class: "empty" },
        h("p", {}, "No reports yet."),
        h("p", {}, "Generate them with ", h("code", {}, "uv run python -m eval.retrieval"), " and ", h("code", {}, "uv run python -m eval.qa"), ". They appear here automatically."),
      ),
    );
    return;
  }

  async function show(report, button) {
    for (const el of list.querySelectorAll(".report-item")) el.classList.remove("is-active");
    button.classList.add("is-active");
    clear(content).append(h("p", { class: "status-line" }, "Loading…"));
    try {
      const { markdown } = await api.report(report.name);
      clear(content).append(
        h(
          "p",
          { class: "provenance-note" },
          `Source: eval/results/${report.name}.md · written by the evaluation runner on ${report.date}`,
          report.smoke ? " · SMOKE RUN: a small subset, not a full result" : "",
        ),
        renderMarkdown(markdown),
      );
    } catch (error) {
      clear(content).append(h("div", { class: "error-panel", role: "alert" }, h("p", {}, error.message)));
    }
  }

  const buttons = reports.map((report) => {
    const button = h(
      "button",
      { class: "report-item", type: "button" },
      h("strong", {}, KIND_LABEL[report.kind] ?? report.kind),
      h("small", {}, `${report.date}${report.smoke ? " · smoke" : ""}`),
    );
    button.addEventListener("click", () => show(report, button));
    list.append(h("li", {}, button));
    return button;
  });
  // Open the newest full report first (smoke runs are listed but not the default).
  const first = reports.findIndex((r) => !r.smoke);
  const index = first === -1 ? 0 : first;
  await show(reports[index], buttons[index]);
}
