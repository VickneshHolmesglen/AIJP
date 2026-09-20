export function bytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function shortDate(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export const score = (x) => (x === null || x === undefined ? "n/a" : x.toFixed(3));

export const clamp01 = (x) => Math.max(0, Math.min(1, x ?? 0));

export function clip(text, max) {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}

/** "L9–14", "p.3", or "" depending on which provenance a chunk has. */
export function locator(c) {
  const parts = [];
  if (c.page !== null && c.page !== undefined) parts.push(`p.${c.page}`);
  if (c.start_line !== null && c.start_line !== undefined) {
    parts.push(
      c.end_line && c.end_line !== c.start_line
        ? `L${c.start_line}–${c.end_line}`
        : `L${c.start_line}`,
    );
  }
  return parts.join(" ");
}

export function dirname(path) {
  const i = path.lastIndexOf("/");
  return i === -1 ? "" : path.slice(0, i);
}

export function basename(path) {
  return path.slice(path.lastIndexOf("/") + 1);
}
