// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// A box that scrolls sideways must be reachable by keyboard and named for a screen reader (WCAG 2.1.1,
// axe scrollable-region-focusable), but a box that fits needs neither a tab stop nor a landmark. Each
// element with a `data-scroll-label` is a focusable region named by that label while its content is wider
// than it is, and a plain box otherwise. Expressive Code makes a scrolling code block a region but leaves it
// unnamed, so two of them on a page break axe's landmark-unique; each gets a label here, which this script
// keeps up with Expressive Code's own updates (both set the same attributes while the block scrolls).
// Diagram frames (src/remark-diagram-frames.mjs) also get their "Open full size" link pointed at the image
// the theme shows.

function updateRegion(box: HTMLElement): void {
  if (box.scrollWidth > box.clientWidth) {
    box.tabIndex = 0;
    box.setAttribute("role", "region");
    box.setAttribute("aria-label", `${box.dataset.scrollLabel}, scrolls sideways`);
  } else if (box.hasAttribute("role")) {
    box.removeAttribute("tabindex");
    box.removeAttribute("role");
    box.removeAttribute("aria-label");
  }
}

/** "Code block 2 (sh)", or the block's title when it has one. */
function labelCodeBlocks(): void {
  document.querySelectorAll<HTMLElement>(".expressive-code pre").forEach((pre, index) => {
    const title = pre.closest(".frame")?.querySelector(".title")?.textContent?.trim();
    const language = pre.dataset.language ? ` (${pre.dataset.language})` : "";
    pre.dataset.scrollLabel = title ? `${title}, code block ${index + 1}` : `Code block ${index + 1}${language}`;
  });
}

function updateFullSizeLinks(): void {
  const dark = document.documentElement.dataset.theme === "dark";
  for (const diagram of document.querySelectorAll<HTMLElement>(".bh-diagram")) {
    const image =
      diagram.querySelector<HTMLImageElement>(dark ? "img.bh-diagram-dark" : "img.bh-diagram-light") ??
      diagram.querySelector<HTMLImageElement>("img");
    const link = diagram.querySelector<HTMLAnchorElement>(".bh-diagram-open a");
    if (!image || !link) continue;
    link.href = image.currentSrc || image.src;
    link.hidden = false;
  }
}

const regions = new ResizeObserver((entries) => {
  for (const entry of entries) updateRegion(entry.target as HTMLElement);
});
labelCodeBlocks();
for (const box of document.querySelectorAll<HTMLElement>("[data-scroll-label]")) regions.observe(box);
// Expressive Code adds or removes its region later, after its own debounce; name it whenever it does.
new MutationObserver((records) => {
  for (const { target } of records) {
    const pre = target as HTMLElement;
    if (pre.getAttribute("role") === "region" && !pre.hasAttribute("aria-label")) updateRegion(pre);
  }
}).observe(document.body, { subtree: true, attributeFilter: ["role"] });

updateFullSizeLinks();
new MutationObserver(updateFullSizeLinks).observe(document.documentElement, { attributeFilter: ["data-theme"] });
