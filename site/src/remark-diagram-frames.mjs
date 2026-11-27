// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// Frame each diagram image: a paragraph that holds one local `.svg` image (the domain model's D2 diagrams)
// becomes a drawing-sheet frame around a sideways-scrolling sheet that shows the SVG at its natural size,
// so its labels stay readable, and an "Open full size" link below it.
// - When the generator wrote a dark render beside the SVG, `<name>.dark.svg` (tools/gen/contracts_gen/
//   domain_d2.py), the sheet holds both images; theme.css shows the one that matches [data-theme].
// - src/scripts/scroll-regions.ts makes the sheet a labelled, focusable region while it scrolls, and points
//   the link at the image the theme shows: Astro gives the images their built URLs after this plugin runs.
// It runs before Astro collects a page's images, so the dark image is built like the light one.
import { existsSync } from "node:fs";
import path from "node:path";

import { visit } from "unist-util-visit";

const isLocalSvg = (/** @type {string} */ url) => url.endsWith(".svg") && !/^([a-z][a-z0-9+.-]*:|\/\/)/i.test(url);

/** "Diagram 1 of record/part, part: the table below lists its relationships" → "Diagram 1 of record/part, part". */
export const diagramLabel = (/** @type {string} */ alt) => alt.split(":")[0].trim() || "Diagram";

export default function remarkDiagramFrames() {
  return (/** @type {import("mdast").Root} */ tree, /** @type {{ path?: string }} */ file) => {
    visit(tree, "paragraph", (node, index, parent) => {
      const content = node.children.filter((child) => !(child.type === "text" && !child.value.trim()));
      const [image] = content;
      if (content.length !== 1 || image.type !== "image" || !isLocalSvg(image.url) || !parent) return;
      const darkUrl = image.url.replace(/\.svg$/, ".dark.svg");
      const hasDark = Boolean(file.path && existsSync(path.join(path.dirname(file.path), decodeURI(darkUrl))));
      const images = [{ ...image, data: { hProperties: { className: hasDark ? ["bh-diagram-light"] : [] } } }];
      if (hasDark) images.push({ ...image, url: darkUrl, data: { hProperties: { className: ["bh-diagram-dark"] } } });
      const sheet = {
        type: "bhDiagramSheet",
        data: { hName: "div", hProperties: { className: ["bh-diagram-sheet"], dataScrollLabel: diagramLabel(image.alt ?? "") } },
        children: images,
      };
      const frame = { type: "bhDiagramFrame", data: { hName: "div", hProperties: { className: ["bh-diagram-frame"] } }, children: [sheet] };
      const open = { type: "html", value: '<p class="bh-diagram-open"><a hidden>Open full size</a></p>' };
      const figure = { type: "bhDiagram", data: { hName: "div", hProperties: { className: ["bh-diagram"] } }, children: [frame, open] };
      parent.children[/** @type {number} */ (index)] = /** @type {any} */ (figure);
    });
  };
}
