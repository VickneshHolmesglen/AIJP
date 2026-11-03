"""Render a design-audit JSON (app/design_audit.py) as ONE static HTML page.

No script, no external request: the page can be hosted anywhere (e.g. GitHub Pages) and shows
exactly what the tool produced. Every piece of text in it came from a document or a model, so all
of it goes through html.escape; nothing is inserted as markup.

A claim may carry an optional "review" object added by a person after the run
({"verdict_correct": true|false, "note": "..."}); the page shows it next to the tool's verdict and
counts reviewed claims in the summary, so a reader sees how far the output was checked by hand.
"""

from html import escape
from typing import Any

_ORDER = ["potential_discrepancy", "consistent", "insufficient_evidence", "failed"]
_LABEL = {
    "potential_discrepancy": "Possible mismatch",
    "consistent": "Consistent",
    "insufficient_evidence": "Not enough evidence",
    "failed": "Check failed",
}

_CSS = """
:root{--bg:#f6f4ef;--ink:#1d1b18;--mute:#6b665d;--line:#ddd7cb;--card:#fff;
--bad:#b4442c;--bad-bg:#fbe9e4;--ok:#2f6f4f;--ok-bg:#e3f1e8;--na:#6b665d;--na-bg:#ece9e2}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:48px 20px 80px}
h1{font-size:2rem;line-height:1.2;margin:0 0 8px}h2{font-size:1.15rem;margin:40px 0 12px}
.lede{color:var(--mute);margin:0 0 24px;max-width:70ch}
.meta{font-size:.85rem;color:var(--mute);margin:0 0 28px}
.meta code{font-size:.85rem}
.tally{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 12px;padding:0;list-style:none}
.tally li{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px}
.tally b{font-size:1.4rem;display:block}
.claim{background:var(--card);border:1px solid var(--line);border-left-width:5px;
border-radius:8px;margin:0 0 14px;padding:0}
.claim.potential_discrepancy{border-left-color:var(--bad)}
.claim.consistent{border-left-color:var(--ok)}
.claim summary{cursor:pointer;padding:14px 18px;list-style:none;display:flex;gap:12px;
align-items:baseline}
.claim summary::-webkit-details-marker{display:none}
.claim .body{padding:0 18px 18px}
.badge{flex:none;font-size:.75rem;font-weight:600;text-transform:uppercase;letter-spacing:.04em;
padding:2px 8px;border-radius:99px;background:var(--na-bg);color:var(--na)}
.potential_discrepancy .badge{background:var(--bad-bg);color:var(--bad)}
.consistent .badge{background:var(--ok-bg);color:var(--ok)}
.loc{font-size:.8rem;color:var(--mute);font-family:ui-monospace,Consolas,monospace}
blockquote{margin:10px 0;padding:6px 12px;border-left:3px solid var(--line);color:var(--mute)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:12px}
.cols>div{min-width:0}
.claim summary,.claim .body>p,blockquote,.loc{overflow-wrap:anywhere}
@media (max-width:760px){.cols{grid-template-columns:1fr}}
.cols h3{font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);
margin:0 0 6px}
pre{margin:0 0 10px;padding:10px;background:#f3f1ec;border:1px solid var(--line);
border-radius:6px;font-size:.78rem;line-height:1.45;overflow:auto;max-height:340px;
white-space:pre}
.review{margin:10px 0;padding:8px 12px;border-radius:6px;background:#f3f1ec;font-size:.9rem}
.none{color:var(--mute);font-style:italic}
footer{margin-top:48px;font-size:.85rem;color:var(--mute)}
.links{margin:-8px 0 24px;font-weight:600}
a{color:inherit}
"""


def _evidence(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<p class="none">nothing cited</p>'
    out = []
    for e in items:
        where = f"{e['path']}:{e['start_line']}-{e['end_line']}"
        section = f" · {e['section']}" if e.get("section") else ""
        out.append(
            f'<div class="loc">{escape(where)}{escape(section)}</div>'
            f"<pre><code>{escape(e.get('text', ''))}</code></pre>"
        )
    return "".join(out)


def _claim(c: dict[str, Any], document: str) -> str:
    verdict = c["verdict"] if c["verdict"] in _LABEL else "failed"
    review = c.get("review")
    review_html = ""
    if isinstance(review, dict):
        ok = review.get("verdict_correct")
        mark = "Checked by hand: verdict " + ("correct" if ok else "WRONG")
        note = f" — {escape(review['note'])}" if review.get("note") else ""
        review_html = f'<div class="review"><b>{mark}</b>{note}</div>'
    is_open = " open" if verdict == "potential_discrepancy" else ""
    where = f"{document}:{c['line']}" + (f" · {c['section']}" if c.get("section") else "")
    return f"""<details class="claim {verdict}"{is_open}>
<summary><span class="badge">{escape(_LABEL[verdict])}</span>
<span>{escape(c["claim"])}</span></summary>
<div class="body">
<div class="loc">{escape(where)}</div>{review_html}
<blockquote>{escape(c["quote"])}</blockquote>
<p>{escape(c["explanation"])}</p>
<div class="cols">
<div><h3>Design cites</h3>{_evidence(c.get("design_evidence", []))}</div>
<div><h3>Code and data cite</h3>{_evidence(c.get("implementation_evidence", []))}</div>
</div>
</div></details>"""


def _sorted(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        claims,
        key=lambda c: _ORDER.index(c["verdict"]) if c["verdict"] in _ORDER else len(_ORDER),
    )


def _section(report: dict[str, Any]) -> str:
    claims = _sorted(report["claims"])
    under = (
        f" · passages under “{escape(report['section_filter'])}”"
        if report.get("section_filter")
        else ""
    )
    skipped = len(report.get("passages_failed", []))
    skipped_note = f" · {skipped} passage(s) skipped: the model failed on them" if skipped else ""
    return f"""<h2><code>{escape(report["document"])}</code></h2>
<p class="meta">{len(claims)} claims from {report["passages_read"]} passages{under}{skipped_note} ·
model {escape(report["model"])} (local), judge {escape(report["judge_mode"])} ·
{report.get("minutes", "?")} min · generated {escape(report["generated"])}</p>
{"".join(_claim(c, report["document"]) for c in claims)}"""


def render_html(
    reports: list[dict[str, Any]],
    title: str,
    intro: str = "",
    footer: str = "",
    links: list[tuple[str, str]] | None = None,
) -> str:
    """One page for one or more audited documents, with a tally over all of them. `links` are
    (label, https URL) pairs shown under the title; anything that is not https is refused."""
    for _, url in links or []:
        if not url.startswith("https://"):
            raise ValueError(f"only https links are allowed: {url!r}")
    nav = " · ".join(
        f'<a href="{escape(url, quote=True)}">{escape(label)}</a>' for label, url in links or []
    )
    claims = [c for r in reports for c in r["claims"]]
    counts = {v: sum(1 for c in claims if c["verdict"] == v) for v in _ORDER}
    reviewed = [c for c in claims if isinstance(c.get("review"), dict)]
    right = sum(1 for c in reviewed if c["review"].get("verdict_correct"))
    tally = "".join(f"<li><b>{n}</b>{escape(_LABEL[v])}</li>" for v, n in counts.items() if n)
    if reviewed:
        tally += f"<li><b>{right} / {len(reviewed)}</b>verdicts confirmed by hand</li>"
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>{_CSS}</style></head>
<body><main>
<h1>{escape(title)}</h1>
<p class="lede">{escape(intro)}</p>
{f'<p class="links">{nav}</p>' if nav else ""}
<ul class="tally">{tally}</ul>
<p class="meta">Each verdict is triage, not proof: the model reads retrieved passages and cannot
run the game. A verdict is only shown if it cites evidence on both the design and the code side;
otherwise it is reported as “not enough evidence”.</p>
{"".join(_section(r) for r in reports)}
<footer>{escape(footer)}</footer>
</main></body></html>
"""
