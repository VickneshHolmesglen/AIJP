// A deliberately small Markdown renderer for the evaluation reports: headings, paragraphs, bullet
// lists, tables, **bold**, *italic*, `code`. It builds DOM nodes (never HTML strings), so report
// text cannot inject markup even if it contains angle brackets.

import { h } from "./dom.js";

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/;

function inline(text) {
  return text
    .split(INLINE)
    .filter((part) => part !== "")
    .map((part) => {
      if (part.startsWith("**") && part.endsWith("**")) return h("strong", {}, part.slice(2, -2));
      if (part.startsWith("`") && part.endsWith("`")) return h("code", {}, part.slice(1, -1));
      if (part.length > 2 && part.startsWith("*") && part.endsWith("*")) {
        return h("em", {}, part.slice(1, -1));
      }
      return part;
    });
}

const isTableLine = (line) => line.trimStart().startsWith("|");
const isSeparator = (cells) => cells.every((c) => /^:?-{3,}:?$/.test(c));

function cells(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}

function table(lines) {
  const rows = lines.map(cells);
  const head = rows[0];
  const body = rows.slice(1).filter((r) => !isSeparator(r));
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      {},
      h("thead", {}, h("tr", {}, head.map((c) => h("th", {}, inline(c))))),
      h("tbody", {}, body.map((r) => h("tr", {}, r.map((c) => h("td", {}, inline(c)))))),
    ),
  );
}

export function renderMarkdown(source) {
  const root = h("div", { class: "md" });
  const lines = source.split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      // The page already has an <h1>, so report headings start at <h2>.
      root.append(h(`h${Math.min(heading[1].length + 1, 4)}`, {}, inline(heading[2])));
      i += 1;
    } else if (isTableLine(line)) {
      const block = [];
      while (i < lines.length && isTableLine(lines[i])) block.push(lines[i++]);
      root.append(table(block));
    } else if (/^[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(h("li", {}, inline(lines[i++].replace(/^[-*]\s+/, ""))));
      }
      root.append(h("ul", {}, items));
    } else {
      const para = [];
      while (
        i < lines.length &&
        lines[i].trim() &&
        !isTableLine(lines[i]) &&
        !/^(#{1,4}\s|[-*]\s)/.test(lines[i])
      ) {
        para.push(lines[i++].trim());
      }
      root.append(h("p", {}, inline(para.join(" "))));
    }
  }
  return root;
}
