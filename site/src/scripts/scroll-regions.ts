// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// A box that scrolls sideways must be reachable by keyboard and named for a screen reader (WCAG 2.1.1,
// axe scrollable-region-focusable), but a box that fits needs neither a tab stop nor a landmark. Each
// element with a `data-scroll-label` is a focusable region named by that label while its content is wider
// than it is, and a plain box otherwise; Expressive Code does the same for its code blocks.
// Diagram frames (src/remark-diagram-frames.mjs) also get their "Open full size" link pointed at the image
// the theme shows.

function updateRegion(box: HTMLElement): void {
  const scrolls = box.scrollWidth > box.clientWidth;
  if (scrolls && !box.hasAttribute("role")) {
    box.tabIndex = 0;
    box.setAttribute("role", "region");
    box.setAttribute("aria-label", `${box.dataset.scrollLabel}, scrolls sideways`);
  } else if (!scrolls && box.hasAttribute("role")) {
    box.removeAttribute("tabindex");
    box.removeAttribute("role");
    box.removeAttribute("aria-label");
  }
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
for (const box of document.querySelectorAll<HTMLElement>("[data-scroll-label]")) regions.observe(box);

updateFullSizeLinks();
new MutationObserver(updateFullSizeLinks).observe(document.documentElement, { attributeFilter: ["data-theme"] });
