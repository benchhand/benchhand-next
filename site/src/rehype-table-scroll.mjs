// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// Wrap every Markdown table in a box that scrolls sideways when the table is wider than the column, so the
// table keeps its own semantics and the box, not the table, becomes the scrolling region. The box's
// `data-scroll-label` names it after the table's number on the page and the heading above it, such as
// "Table 2, The two kinds of gate"; src/scripts/scroll-regions.ts makes it a focusable region with that
// label while it scrolls (axe scrollable-region-focusable, landmark-unique).
import { SKIP, visit } from "unist-util-visit";

const HEADING = /^h[2-6]$/;

/** @param {any} node */
function textOf(node) {
  if (node.type === "text") return node.value;
  return (node.children ?? []).map(textOf).join("");
}

export default function rehypeTableScroll() {
  return (/** @type {any} */ tree) => {
    let heading = "";
    let count = 0;
    visit(tree, "element", (node, index, parent) => {
      if (HEADING.test(node.tagName)) heading = textOf(node).trim();
      if (node.tagName !== "table" || !parent || index === undefined) return undefined;
      count += 1;
      const label = heading ? `Table ${count}, ${heading}` : `Table ${count}`;
      parent.children[index] = {
        type: "element",
        tagName: "div",
        properties: { className: ["bh-table-scroll"], dataScrollLabel: label },
        children: [node],
      };
      return [SKIP, index + 1];
    });
  };
}
