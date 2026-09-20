import { ApiError } from "../api.js";
import { clear, h, rise } from "../dom.js";

export async function mountLogin(root, ctx) {
  const input = h("input", {
    id: "key",
    class: "field key-field",
    type: "password",
    autocomplete: "off",
    spellcheck: "false",
    placeholder: "aijp_xxxxxxxx_…",
    "aria-describedby": "key-help",
  });
  const remember = h("input", { type: "checkbox", id: "remember" });
  const submit = h("button", { class: "btn btn-primary", type: "submit" }, "Sign in");
  const message = h("p", { class: "login-message", role: "alert" });
  if (ctx.loginNotice) message.textContent = ctx.loginNotice;

  async function signIn(event) {
    event.preventDefault();
    const key = input.value.trim();
    if (!key) return;
    submit.disabled = true;
    message.textContent = "";
    try {
      await ctx.signIn(key, remember.checked);
    } catch (error) {
      // The server gives one generic answer on purpose, and so do we.
      message.textContent =
        error instanceof ApiError && error.status === 0
          ? "Cannot reach the server."
          : "That key was not accepted.";
      input.select();
      submit.disabled = false;
    }
  }

  clear(root).append(
    rise(
      h(
        "div",
        { class: "view-head" },
        h("h1", {}, "Sign ", h("em", {}, "in")),
        h(
          "p",
          { class: "lede" },
          "This server needs an API key. Each key belongs to a named person and has a role: readers can ask and search, editors can also change the corpus, approvers can also authorise drafted tasks.",
        ),
      ),
    ),
    rise(
      h(
        "form",
        { class: "login-form", onSubmit: signIn },
        h("label", { class: "label", for: "key" }, "API key"),
        input,
        h(
          "label",
          { class: "remember", for: "remember" },
          remember,
          h("span", {}, "Keep me signed in for this browser tab"),
        ),
        h("div", { class: "form-row" }, submit),
        message,
        h(
          "p",
          { class: "hint", id: "key-help" },
          "Keys are created by whoever runs the server: ",
          h("code", {}, "python -m app.keys create --name you --role editor"),
          ". The key is kept in this page's memory only, unless you tick the box, and is never stored on the server in readable form.",
        ),
      ),
      1,
    ),
  );
  input.focus();
}
