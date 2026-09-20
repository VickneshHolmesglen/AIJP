import { api } from "../api.js";
import { meter, provenance } from "../components.js";
import { append, clear, h, rise } from "../dom.js";
import { score, shortDate } from "../format.js";

const VERDICT = {
  consistent: { label: "Consistent", cls: "is-consistent" },
  potential_discrepancy: { label: "Potential discrepancy", cls: "is-discrepancy" },
  insufficient_evidence: { label: "Insufficient evidence", cls: "is-unknown" },
};

const DOWNGRADE = {
  evidence_gate:
    "Not enough relevant design or code evidence was found, so the model was not consulted.",
  missing_citations_on_both_sides:
    "The model offered a verdict without citing evidence on both the design and the code side, so it was withheld.",
  model_output_invalid: "The model's answer could not be understood, so no verdict is reported.",
  empty_explanation: "The model gave a verdict without an explanation, so it was withheld.",
};

const badge = (verdict) => {
  const v = VERDICT[verdict] ?? { label: verdict ?? "unknown", cls: "is-unknown" };
  return h("span", { class: `verdict ${v.cls}` }, v.label);
};

const asCitation = (e) => ({
  source_path: e.path,
  section: e.section,
  start_line: e.start_line,
  end_line: e.end_line,
  page: null,
});

/** "…caps stacks at 5 [D1] [C1]." becomes text with a chip per valid reference. */
function withRefs(text, byRef, ctx) {
  return text.split(/(\[[DC]\d+\])/).map((part) => {
    const match = /^\[([DC]\d+)\]$/.exec(part);
    const evidence = match ? byRef.get(match[1]) : null;
    if (!evidence) return part;
    return h(
      "button",
      {
        class: "cite",
        type: "button",
        "aria-label": `Open ${evidence.ref}: ${evidence.path}`,
        onClick: () => ctx.openSource(evidence.document_id, evidence.chunk_id),
      },
      evidence.ref,
    );
  });
}

function evidenceColumn(title, items, ctx) {
  return h(
    "section",
    { class: "evidence-col", "aria-label": title },
    h("div", { class: "label" }, title),
    items.length === 0
      ? h("p", { class: "muted" }, "Nothing relevant was found on this side.")
      : h(
          "ol",
          { class: "evidence-list" },
          items.map((e) =>
            h(
              "li",
              { class: `evidence ${e.cited ? "is-cited" : ""}` },
              h(
                "div",
                { class: "evidence-head" },
                h("span", { class: "evidence-ref" }, e.ref),
                e.cited ? h("span", { class: "evidence-flag" }, "cited") : null,
                e.origin === "symbol" ? h("span", { class: "evidence-flag muted" }, "found by name") : null,
              ),
              provenance(asCitation(e)),
              h(
                "div",
                { class: "src-foot" },
                e.cosine === null ? null : meter("cos", e.cosine, "cos"),
                h(
                  "button",
                  {
                    class: "btn btn-small",
                    type: "button",
                    onClick: () => ctx.openSource(e.document_id, e.chunk_id),
                  },
                  "Open in context",
                ),
              ),
            ),
          ),
        ),
  );
}

function stepSummary(step) {
  const o = step.output ?? {};
  if (step.status === "skipped") return o.reason ?? "skipped";
  if (step.status === "error") return o.error ?? "failed";
  switch (step.name) {
    case "search_design":
    case "search_implementation": {
      const best = Math.max(...o.passages.map((p) => p.cosine ?? 0), 0);
      return `${o.passages.length} passages, best cosine ${score(best)}`;
    }
    case "lookup_symbols":
      return `${o.passages.length} extra passages found by name`;
    case "evidence_gate":
      return `design ${score(o.design_best_cosine)} ${o.design_ok ? "ok" : "too low"}, code ${score(o.implementation_best_cosine)} ${o.implementation_ok ? "ok" : "too low"}`;
    case "judge":
      return `model said ${o.raw_verdict ?? "nothing usable"} (${o.prompt_tokens}+${o.completion_tokens} tokens)`;
    case "validate_verdict":
      return o.downgrade_reason ? `downgraded: ${o.downgrade_reason}` : `accepted: ${o.verdict}`;
    case "draft_action":
      return `drafted ${o.kind}, ${o.status}`;
    case "human_decision":
      return `${step.input?.decision ?? ""} by ${step.input?.actor ?? "unknown"}: ${o.action_status}`;
    default:
      return "";
  }
}

function auditTrail(run) {
  const total = run.steps.reduce((sum, s) => sum + s.duration_ms, 0);
  return h(
    "details",
    { class: "audit" },
    h("summary", {}, `How this was checked: ${run.steps.length} recorded steps, ${(total / 1000).toFixed(1)} s`),
    h(
      "div",
      { class: "table-wrap" },
      h(
        "table",
        {},
        h("caption", { class: "sr-only" }, "Audit trail"),
        h(
          "thead",
          {},
          h("tr", {}, h("th", { class: "num" }, "#"), h("th", {}, "Step"), h("th", {}, "Status"), h("th", { class: "num" }, "ms"), h("th", {}, "What happened")),
        ),
        h(
          "tbody",
          {},
          run.steps.map((s) =>
            h(
              "tr",
              {},
              h("td", { class: "num" }, String(s.seq)),
              h("td", {}, h("span", { class: "fname" }, s.name)),
              h("td", {}, h("span", { class: `badge step-${s.status}` }, s.status)),
              h("td", { class: "num" }, String(s.duration_ms)),
              h("td", { class: "muted" }, stepSummary(s)),
            ),
          ),
        ),
      ),
    ),
    h("p", { class: "note" }, "Steps store locations and counts, never document text. They are written as each step finishes."),
  );
}

function proposal(run, ctx, refresh) {
  const action = run.actions[0];
  if (!action) return null;
  const decided = action.status !== "pending";
  const buttons = h("div", { class: "actions" });
  const statusLine = h("p", { class: "status-line" });

  if (!decided && ctx.can("approver")) {
    const approve = h("button", { class: "btn btn-primary", type: "button" }, "Approve and create task");
    const reject = h("button", { class: "btn", type: "button" }, "Reject");
    const decide = async (fn, verb) => {
      approve.disabled = reject.disabled = true;
      try {
        const done = await fn(action.id);
        ctx.toast(done.status === "executed" ? "Task created" : `Action ${done.status}`, done.status === "failed" ? "bad" : "ok");
      } catch (error) {
        ctx.toast(`${verb} failed: ${error.message}`, "bad");
      }
      await refresh();
    };
    approve.addEventListener("click", () => decide(api.approve, "Approve"));
    reject.addEventListener("click", () => decide(api.reject, "Reject"));
    buttons.append(approve, reject);
    statusLine.textContent = "Nothing is created until you approve. What is approved is exactly what is shown here.";
  } else if (!decided) {
    statusLine.textContent = `Waiting for someone with the approver role to decide. Your key has the ${ctx.me?.role ?? "reader"} role, so you cannot approve or reject this.`;
  } else {
    statusLine.textContent =
      action.status === "executed"
        ? "Approved: the task was created."
        : action.status === "rejected"
          ? "Rejected: nothing was created."
          : "The action failed; nothing was created.";
  }

  return h(
    "aside",
    { class: `proposal ${decided ? "is-decided" : ""}`, "aria-label": "Proposed action" },
    h("div", { class: "label" }, decided ? "Drafted task" : "Proposed task, awaiting your approval"),
    h("h3", {}, action.payload.title),
    h("p", { class: "proposal-body" }, action.payload.description),
    h("p", { class: "muted mono" }, `Attaches ${action.payload.evidence.length} cited passages as references`),
    // Accountability: who asked for the check, and (once decided) who decided and how.
    h(
      "p",
      { class: "who-line" },
      "Requested by ",
      h("strong", {}, run.requested_by ?? "unknown"),
      decided ? [` · ${action.status} by `, h("strong", {}, action.decided_by ?? "unknown")] : null,
    ),
    statusLine,
    buttons,
  );
}

export async function mountVerify(root, ctx) {
  const input = h("textarea", {
    id: "claim",
    class: "prompt",
    rows: "2",
    placeholder: "Poison stacks up to 3 times.",
    "aria-describedby": "claim-hint",
  });
  const submit = h("button", { class: "btn btn-primary", type: "submit" }, "Check");
  const out = h("section", { class: "result", "aria-live": "polite" });
  const history = h("section", { class: "history" });
  const tasksHost = h("section", { class: "history" });

  /** `animate` is false when re-rendering the same run in place (after approve/reject). */
  function renderRun(run, animate = true) {
    const enter = (el, i) => (animate ? rise(el, i) : el);
    clear(out);
    if (run.status === "failed") {
      out.append(
        h(
          "div",
          { class: "error-panel", role: "alert" },
          h("strong", {}, "The check could not finish"),
          h("p", {}, run.error ?? "Unknown error"),
          h("a", { href: "#/system" }, "Open the System page"),
        ),
        auditTrail(run),
      );
      return;
    }
    const r = run.result;
    const evidence = [...r.design_evidence, ...r.implementation_evidence];
    const byRef = new Map(evidence.map((e) => [e.ref, e]));
    const secs = run.steps.reduce((sum, s) => sum + s.duration_ms, 0) / 1000;
    // dom.js append(), not Element.append(): the native one would print a missing (null) proposal
    // or downgrade note as the literal text "null".
    append(out, [
      enter(
        h(
          "div",
          { class: "kicker" },
          badge(r.verdict),
          h("span", { class: "meta" }, `${secs.toFixed(1)} s · ${r.usage.prompt_tokens + r.usage.completion_tokens} tokens`),
        ),
        0,
      ),
      enter(h("p", { class: "claim-echo" }, `“${run.claim}”`), 1),
      enter(h("p", { class: "answer-text" }, withRefs(r.explanation, byRef, ctx)), 2),
      r.downgrade_reason
        ? enter(h("p", { class: "note" }, DOWNGRADE[r.downgrade_reason] ?? r.downgrade_reason), 2)
        : null,
      enter(
        h(
          "div",
          { class: "evidence-cols" },
          evidenceColumn("The design says", r.design_evidence, ctx),
          evidenceColumn("The code and config show", r.implementation_evidence, ctx),
        ),
        3,
      ),
      enter(h("p", { class: "provenance-note" }, r.disclaimer), 4),
      proposal(run, ctx, () => reload(run.id)),
      auditTrail(run),
    ]);
  }

  async function reload(id) {
    try {
      renderRun(await api.run(id), false);
    } catch (error) {
      ctx.toast(error.message, "bad");
    }
    await loadLists();
  }

  async function run(event) {
    event.preventDefault();
    const claim = input.value.trim();
    if (claim.length < 3) return;
    submit.disabled = true;
    clear(out).append(
      h(
        "div",
        { class: "pending", "aria-busy": "true" },
        h("p", { class: "status-line" }, "Searching the design documents, then the code, then asking the model to compare. This takes 20–40 s locally…"),
        h("div", { class: "bar" }),
        h("div", { class: "bar" }),
        h("div", { class: "bar" }),
      ),
    );
    try {
      renderRun(await api.verify(claim));
      await loadLists();
    } catch (error) {
      clear(out).append(h("div", { class: "error-panel", role: "alert" }, h("strong", {}, "Request failed"), h("p", {}, error.message)));
    } finally {
      submit.disabled = false;
    }
  }

  async function loadLists() {
    try {
      const [runs, tasks] = await Promise.all([api.runs(), api.tasks()]);
      clear(history);
      if (runs.items.length) {
        history.append(
          h("div", { class: "label" }, "Recent checks"),
          h(
            "ul",
            { class: "run-list" },
            runs.items.map((r) =>
              h(
                "li",
                {},
                h(
                  "button",
                  { class: "run-item", type: "button", onClick: () => reload(r.id) },
                  badge(r.verdict ?? (r.status === "failed" ? "insufficient_evidence" : null)),
                  h("span", { class: "run-claim" }, r.claim),
                  h(
                    "span",
                    { class: "muted mono" },
                    `${r.status.replace("_", " ")} · ${r.requested_by ?? "unknown"} · ${shortDate(r.created_at)}`,
                  ),
                ),
              ),
            ),
          ),
        );
      }
      clear(tasksHost);
      if (tasks.items.length) {
        tasksHost.append(
          h("div", { class: "label" }, `Approved tasks (${tasks.total})`),
          h(
            "ul",
            { class: "task-list" },
            tasks.items.map((t) =>
              h(
                "li",
                { class: "task" },
                h("strong", {}, t.title),
                h(
                  "span",
                  { class: "muted mono" },
                  `${t.status} · approved by ${t.created_by ?? "unknown"} · ${shortDate(t.created_at)} · ${t.evidence.length} references`,
                ),
              ),
            ),
          ),
        );
      }
    } catch {
      /* lists are secondary; the main flow reports its own errors */
    }
  }

  const form = h(
    "form",
    { class: "ask-form", onSubmit: run },
    h("label", { class: "label", for: "claim" }, "A claim about how the project should behave"),
    input,
    h(
      "div",
      { class: "form-row" },
      submit,
      h("span", { class: "hint", id: "claim-hint" }, "Ctrl/⌘ + Enter. Compares what the design documents say with what the code and config show."),
    ),
    // h() drops the null, so a key that may run checks sees no note.
    ctx.can("editor")
      ? null
      : h(
          "p",
          { class: "role-note" },
          `Running a check needs an editor key; yours is ${ctx.me?.role ?? "reader"}. You can still read earlier checks below.`,
        ),
  );
  if (!ctx.can("editor")) {
    submit.disabled = true;
    input.disabled = true;
  }
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) form.requestSubmit();
  });

  clear(root).append(
    rise(
      h(
        "div",
        { class: "view-head" },
        h("h1", {}, "Design ", h("em", {}, "versus"), " code"),
        h(
          "p",
          { class: "lede" },
          "State a claim and the system gathers evidence from both sides. It reports consistent, a potential discrepancy, or that it cannot tell. It is triage from retrieved passages, never proof, and a discrepancy can only draft a task for you to approve.",
        ),
      ),
    ),
    rise(form, 1),
    out,
    history,
    tasksHost,
  );
  input.focus();
  await loadLists();
}
