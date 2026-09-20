// Tiny DOM builder. Everything goes in through text nodes or setAttribute, never innerHTML, so
// text from uploaded files or from the LLM can never become markup. (The page's CSP would also
// block inline handlers and styles; `style` is rejected here so nobody tries.)

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key === "style") throw new Error("inline style attributes are blocked by the CSP");
    else if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else el.setAttribute(key, value === true ? "" : String(value));
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function clear(el) {
  el.replaceChildren();
  return el;
}

export const $ = (selector, root = document) => root.querySelector(selector);

/** Stagger the entrance of a view's blocks (CSS custom property, allowed by the CSP). */
export function rise(el, index = 0) {
  el.classList.add("rise");
  el.style.setProperty("--i", String(index));
  return el;
}
