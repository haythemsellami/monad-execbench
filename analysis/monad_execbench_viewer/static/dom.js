// DOM helpers. Imported names, labels, paths, selectors and snippets are
// untrusted: every binding here goes through textContent or attribute values,
// never markup.

const SVG_NS = "http://www.w3.org/2000/svg";

export function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    parent.append(
      child instanceof Node ? child : document.createTextNode(String(child)),
    );
  }
  return parent;
}

function assign(el, attrs) {
  if (!attrs) return el;
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.setAttribute("class", value);
    else if (key === "text") el.textContent = String(value);
    else if (key.startsWith("on") && typeof value === "function")
      el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  return el;
}

export function h(tag, attrs, ...children) {
  return append(assign(document.createElement(tag), attrs), children);
}

export function svg(tag, attrs, ...children) {
  return append(assign(document.createElementNS(SVG_NS, tag), attrs), children);
}

export function icon(name) {
  return svg(
    "svg",
    { class: "icon", "aria-hidden": "true", focusable: "false" },
    svg("use", { href: `#icon-${name}` }),
  );
}

export function corners() {
  return ["tl", "tr", "bl", "br"].map((position) =>
    h("i", { class: `corner ${position}`, "aria-hidden": "true" }),
  );
}

export function blueprint(attrs, ...children) {
  const classes = ["blueprint", attrs?.class].filter(Boolean).join(" ");
  return h("div", { ...attrs, class: classes }, corners(), ...children);
}

export function tag(text, variant = "", extra) {
  return h("span", { class: `tag ${variant}`.trim(), ...extra }, text);
}

export function unavailable() {
  return h("span", { class: "unavailable" }, "unavailable");
}

/** A formatted string, or the muted word "unavailable" for null. */
export function valueOr(text) {
  return text === null || text === undefined ? unavailable() : text;
}

const STATUS = {
  success: ["✓ success", "tag-success"],
  revert: ["⤺ revert", "tag-revert"],
  error: ["✕ error", "tag-error"],
};

export function statusTag(status) {
  const [label, variant] = STATUS[status] ?? [String(status), "tag-neutral"];
  return tag(label, variant);
}

/** Column label with a unit suffix that must not be uppercased. */
export function unitLabel(text, unit) {
  return h("span", null, `${text} `, h("span", { class: "unit" }, unit));
}

export function muted(text) {
  return h("span", { class: "muted" }, text);
}

export function fine(text, cls = "fine") {
  return h("p", { class: cls }, text);
}

export function note(text) {
  return h("p", { class: "footnote" }, text);
}

export function loading(text) {
  return h(
    "p",
    { class: "loading", role: "status" },
    h("span", { class: "spinner", "aria-hidden": "true" }),
    text,
  );
}

/**
 * Table from column descriptors and row arrays. Cells may be nodes, strings
 * or {node, class} objects. Column: {label, class, sortKey?}.
 */
export function table({ columns, rows, caption, attrs, rowAttrs }) {
  const head = h(
    "tr",
    null,
    columns.map((column) =>
      h("th", { class: column.class, scope: "col" }, column.head ?? column.label),
    ),
  );
  const body = h("tbody");
  rows.forEach((row, index) => {
    const tr = h("tr", rowAttrs ? rowAttrs(row, index) : null);
    row.cells.forEach((cell, cellIndex) => {
      const column = columns[cellIndex] ?? {};
      const value = cell && typeof cell === "object" && "node" in cell ? cell : null;
      const td = h("td", {
        class: [column.class, value?.class].filter(Boolean).join(" ") || null,
      });
      append(td, [value ? value.node : cell]);
      tr.append(td);
    });
    body.append(tr);
  });
  return h(
    "table",
    attrs,
    caption ? h("caption", { class: "visually-hidden" }, caption) : null,
    h("thead", null, head),
    body,
  );
}

export function select(labelText, options, value, onchange) {
  const control = h(
    "select",
    { onchange: (event) => onchange(event.target.value) },
    options.map(([key, text]) =>
      h("option", { value: key, selected: key === value ? true : null }, text),
    ),
  );
  return h(
    "label",
    { class: "field" },
    h("span", null, labelText),
    h("span", { class: "select" }, control),
  );
}

export function segmented(options, value, onselect, label) {
  return h(
    "div",
    { class: "segmented", role: "group", "aria-label": label },
    options.map(([key, text]) =>
      h(
        "button",
        {
          type: "button",
          "aria-pressed": key === value ? "true" : "false",
          onclick: () => onselect(key),
        },
        text,
      ),
    ),
  );
}

export function kv(rows) {
  return h(
    "table",
    { class: "kv" },
    h(
      "tbody",
      null,
      rows.map(([key, value]) =>
        h("tr", null, h("th", { scope: "row" }, key), h("td", null, value)),
      ),
    ),
  );
}

/** Set geometry through the CSSOM (allowed by style-src 'self'). */
export function geometry(el, properties) {
  for (const [key, value] of Object.entries(properties)) el.style[key] = value;
  return el;
}
