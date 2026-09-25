import { api } from "../api.js";
import { meter, passage } from "../components.js";
import { $, clear, h, rise } from "../dom.js";
import { score } from "../format.js";

const REASONS = {
  insufficient_evidence: {
    label: "Insufficient evidence",
    explain: (top, gate) =>
      top === null || top === undefined
        ? "No embedded passages matched. If you have just uploaded documents, embed them on the System page. Nothing was sent to the model."
        : `The best matching passage scored ${score(top)} cosine similarity, below the evidence gate of ${score(gate)}. Nothing was sent to the model.`,
  },
  model_declined: {
    label: "Model declined",
    explain: (top) =>
      `Passages were retrieved (best ${score(top)} cosine), but the model judged that they do not contain the answer, so it did not guess.`,
  },
  ungrounded_number: {
    label: "Number not verifiable",
    explain: () =>
      "The answer contains a number that is not in the cited passages, not in your question and not the result of a calculation the server ran, so it was withheld.",
  },
  calculation_failed: {
    label: "Calculation rejected",
    explain: () =>
      "The model's arithmetic could not be computed by the calculator (an invalid expression or a missing step), so the answer was withheld rather than show a number nobody computed.",
  },
  answer_truncated: {
    label: "Answer cut off",
    explain: () =>
      "The model's reply ran past the length limit before it finished, so it was withheld rather than show part of an answer. Rephrasing the question more specifically may help.",
  },
  uncited_answer: {
    label: "Answer withheld",
    explain: () =>
      "The model produced an answer without a citation that maps to a retrieved passage. An answer nobody can verify is not shown.",
  },
};

function chip(source, ctx) {
  return h(
    "button",
    {
      class: "cite",
      type: "button",
      "aria-label": `Open source ${source.ref}: ${source.citation.source_path}`,
      onClick: () => ctx.openSource(source.citation.document_id, source.chunk_id ?? null),
    },
    String(source.ref),
  );
}

/**
 * "…limit is 3 [1]." becomes text with a clickable footnote chip for each valid [n]. The model is
 * only asked (not required) to place [n] markers, so when it places none we still append a chip
 * for every verified citation: one click to the evidence must always be available.
 */
function withCitations(text, sources, ctx) {
  const byRef = new Map(sources.map((s) => [s.ref, s]));
  let inline = 0;
  const nodes = text.split(/(\[\d+\])/).map((part) => {
    const match = /^\[(\d+)\]$/.exec(part);
    const source = match ? byRef.get(Number(match[1])) : null;
    if (!source) return part;
    inline += 1;
    return chip(source, ctx);
  });
  if (inline === 0) nodes.push(" ", ...sources.map((s) => chip(s, ctx)));
  return nodes;
}

function meta(res, ms) {
  const tokens = res.usage.prompt_tokens + res.usage.completion_tokens;
  const bits = [`${(ms / 1000).toFixed(1)} s`];
  if (tokens) bits.push(`${tokens} tokens`);
  if (res.top_score !== null) bits.push(`best cosine ${score(res.top_score)}`);
  if (res.escalated === "used") bits.push("re-checked with reasoning");
  return h("span", { class: "meta" }, bits.join(" · "));
}

function answered(res, ms, ctx) {
  return h(
    "article",
    {},
    rise(h("div", { class: "kicker" }, h("span", { class: "tag" }, "Answer · grounded"), meta(res, ms))),
    rise(h("p", { class: "answer-text" }, withCitations(res.answer, res.sources, ctx)), 1),
    res.calculations && res.calculations.length
      ? rise(
          h(
            "div",
            { class: "calc" },
            h("div", { class: "label" }, "Calculated by the server"),
            h(
              "ul",
              { class: "calc-steps" },
              res.calculations.map((c) =>
                h("li", {}, h("code", {}, `${c.expression} = ${c.result}`)),
              ),
            ),
          ),
          2,
        )
      : null,
    rise(h("div", { class: "label" }, `Cited sources (${res.sources.length})`), 2),
    rise(
      h(
        "ol",
        { class: "sources" },
        res.sources.map((s) =>
          passage({
            ref: s.ref,
            chunkId: s.chunk_id,
            content: s.content,
            citation: s.citation,
            meters: meter("cos", s.score, "cos"),
            ctx,
          }),
        ),
      ),
      3,
    ),
  );
}

function refused(res, ms, question, ctx) {
  const reason = REASONS[res.reason] ?? { label: "Declined", explain: () => "" };
  const gate = ctx.status?.config.min_evidence_score;
  return h(
    "article",
    {},
    rise(h("div", { class: "kicker" }, h("span", {}, "No answer"), meta(res, ms))),
    rise(
      h(
        "div",
        { class: "stamp", role: "status" },
        h("p", { class: "stamp-title" }, "No answer"),
        h("p", { class: "stamp-reason" }, reason.label),
        h("p", { class: "stamp-body" }, reason.explain(res.top_score, gate)),
        h(
          "div",
          { class: "stamp-actions" },
          h(
            "a",
            { href: `#/search?q=${encodeURIComponent(question)}` },
            "See what search retrieves",
          ),
          h("a", { href: "#/documents" }, "Check the documents"),
        ),
      ),
      1,
    ),
  );
}

function pending() {
  return h(
    "div",
    { class: "pending", "aria-busy": "true" },
    h("p", { class: "status-line" }, "Retrieving passages, then asking the model. This can take 10–20 s locally…"),
    h("div", { class: "bar" }),
    h("div", { class: "bar" }),
    h("div", { class: "bar" }),
  );
}

export function mountAsk(root, ctx) {
  const history = ctx.state.askHistory;
  const input = h("textarea", {
    id: "q",
    class: "prompt",
    rows: "2",
    placeholder: "Where is enemy damage calculated?",
    "aria-describedby": "q-hint",
  });
  const submit = h("button", { class: "btn btn-primary", type: "submit" }, "Ask");
  const stop = h("button", { class: "btn", type: "button", hidden: true }, "Stop");
  const out = h("section", { class: "result", "aria-live": "polite" });
  const chips = h("div", { class: "chips" });
  let controller = null;

  function renderChips() {
    clear(chips);
    if (history.length === 0) return;
    chips.append(
      h("span", { class: "label" }, "Earlier this session"),
      ...history.map((q) =>
        h(
          "button",
          {
            class: "chip",
            type: "button",
            title: q,
            onClick: () => {
              input.value = q;
              input.focus();
            },
          },
          q,
        ),
      ),
    );
  }

  async function run(event) {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    controller = new AbortController();
    submit.disabled = true;
    stop.hidden = false;
    clear(out).append(pending());
    const started = performance.now();
    try {
      const res = await api.ask(question, controller.signal);
      const ms = performance.now() - started;
      clear(out).append(res.refused ? refused(res, ms, question, ctx) : answered(res, ms, ctx));
      if (!history.includes(question)) history.unshift(question);
      history.splice(5);
      renderChips();
    } catch (error) {
      if (error.name === "AbortError") {
        clear(out);
      } else {
        clear(out).append(
          h(
            "div",
            { class: "error-panel", role: "alert" },
            h("strong", {}, error.status === 503 ? "A dependency is unavailable" : "Request failed"),
            h("p", {}, error.message),
            error.status === 503 ? h("a", { href: "#/system" }, "Open the System page") : null,
          ),
        );
      }
    } finally {
      submit.disabled = false;
      stop.hidden = true;
      controller = null;
    }
  }

  stop.addEventListener("click", () => controller?.abort());
  const form = h(
    "form",
    { class: "ask-form", onSubmit: run },
    h("label", { class: "label", for: "q" }, "Your question"),
    input,
    h(
      "div",
      { class: "form-row" },
      submit,
      stop,
      h("span", { class: "hint", id: "q-hint" }, "Ctrl/⌘ + Enter to ask. Answers cite passages, or say there is no answer."),
    ),
  );
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) form.requestSubmit();
  });

  clear(root).append(
    rise(
      h(
        "div",
        { class: "view-head" },
        h("h1", {}, "Ask the ", h("em", {}, "project")),
        h(
          "p",
          { class: "lede" },
          "Answers come only from the documents you have indexed, each with the exact passages it relied on. When the evidence is not there, you get a refusal that says why.",
        ),
      ),
    ),
    rise(form, 1),
    chips,
    out,
  );
  renderChips();
  input.focus();
}
