import { api } from "../api.js";
import { clear, h, rise } from "../dom.js";
import { bytes } from "../format.js";

const dot = (ok) => h("span", { class: `dot ${ok ? "ok" : "bad"}`, "aria-hidden": "true" });
const kv = (rows) =>
  h("dl", { class: "kv" }, rows.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, String(v))]));

export async function mountSystem(root, ctx) {
  const host = h("div", { class: "cards", "aria-live": "polite" });

  async function render() {
    let status;
    try {
      status = await ctx.refreshStatus();
    } catch (error) {
      clear(host).append(
        h("div", { class: "error-panel", role: "alert" }, h("strong", {}, "API unreachable"), h("p", {}, error.message)),
      );
      return;
    }
    const { database: db, ollama, config } = status;
    const missing = ollama.models.filter((m) => !m.installed);

    clear(host).append(
      rise(
        h(
          "article",
          { class: "card" },
          h("h2", {}, dot(db.reachable && db.pgvector), "Database"),
          db.reachable
            ? kv([
                ["PostgreSQL", "reachable"],
                ["pgvector", db.pgvector ? "installed" : "MISSING"],
                ["Documents", db.documents],
                ["Passages", db.chunks],
                ["Embedded", `${db.embedded_chunks} / ${db.chunks}`],
              ])
            : h("p", { class: "fix" }, "The API cannot reach PostgreSQL. Start it with ", h("code", {}, "docker compose up -d db"), "."),
        ),
      ),
      rise(
        h(
          "article",
          { class: "card" },
          h("h2", {}, dot(ollama.reachable && missing.length === 0), "Ollama"),
          kv([
            ["Server", ollama.reachable ? "reachable" : "unreachable"],
            ["Address", ollama.base_url],
            ...ollama.models.map((m) => [`${m.role} model`, `${m.name}${m.installed ? "" : "  (not installed)"}`]),
          ]),
          !ollama.reachable
            ? h("p", { class: "fix" }, "Start Ollama, then reload this page.")
            : missing.length
              ? h("p", { class: "fix" }, "Install with ", ...missing.flatMap((m, i) => [i ? " and " : "", h("code", {}, `ollama pull ${m.name}`)]), ".")
              : null,
        ),
        1,
      ),
      rise(
        h(
          "article",
          { class: "card" },
          h("h2", {}, "Configuration"),
          kv([
            ["Retrieval mode", config.retrieval_mode],
            ["Passages per answer", config.ask_top_k],
            ["Evidence gate (cosine)", config.min_evidence_score],
            ["Chunk size / overlap", `${config.chunk_max_chars} / ${config.chunk_overlap_chars} chars`],
            ["Upload limit", bytes(config.max_upload_bytes)],
          ]),
          h(
            "p",
            { class: "fix" },
            "The evidence gate was chosen from the threshold table on the Evaluation page. It only stops off-topic questions; the model handles near-misses. Revisit it if the embedding model changes.",
          ),
        ),
        2,
      ),
    );

    const actions = h("div", { class: "actions" });
    const recheck = h("button", { class: "btn", type: "button" }, "Recheck");
    recheck.addEventListener("click", render);
    actions.append(recheck);
    if (db.pending_chunks > 0 && ollama.reachable && ctx.can("editor")) {
      const embed = h("button", { class: "btn btn-primary", type: "button" }, `Embed ${db.pending_chunks} pending passages`);
      embed.addEventListener("click", async () => {
        embed.disabled = true;
        embed.textContent = "Embedding…";
        try {
          const { embedded } = await api.embed();
          ctx.toast(`Embedded ${embedded} passages`, "ok");
        } catch (error) {
          ctx.toast(error.message, "bad");
        }
        await render();
      });
      actions.append(embed);
    }
    host.append(actions);
  }

  clear(root).append(
    rise(
      h(
        "div",
        { class: "view-head" },
        h("h1", {}, "System ", h("em", {}, "status")),
        h("p", { class: "lede" }, "What the app depends on, and whether it is working right now."),
      ),
    ),
    host,
  );
  await render();
}
