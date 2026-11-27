// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// Resolve site and repository links in Markdown, as src/site-link.ts does for components:
// - a root-relative link gets the site base, so pages write `/reference/` and the built site links to
//   `/benchhand-next/reference/` (or `/reference/` when DOCS_URL is at a domain root);
// - "repo:docs/design-plan.md" links to the file on GitHub, so the repository name stays in
//   release.toml (ADR-0015).
// starlight-links-validator then sees the final URLs and checks them.
//
// The validator also reads the splash page's hero `actions[].link` from the front matter that this
// pipeline carries, so those links get the same treatment. The Hero component renders from the content
// collection's own copy of the front matter and resolves the links itself (src/site-link.ts).
import { visit } from "unist-util-visit";

/** @param {{ base: string, repoUrl: string }} options base with a leading and a trailing slash */
export default function remarkBaseLinks({ base, repoUrl }) {
  const prefix = base.replace(/\/$/, "");
  const resolve = (/** @type {string} */ url) => {
    if (url.startsWith("repo:")) return `${repoUrl}/blob/main/${url.slice("repo:".length)}`;
    if (url.startsWith("/") && !url.startsWith("//") && !url.startsWith(`${prefix}/`)) return prefix + url;
    return url;
  };
  return (/** @type {import("mdast").Root} */ tree, /** @type {{ data: any }} */ file) => {
    visit(tree, ["link", "image", "definition"], (node) => {
      const link = /** @type {{ url: string }} */ (node);
      link.url = resolve(link.url);
    });
    for (const action of file.data.astro?.frontmatter?.hero?.actions ?? []) {
      if (typeof action.link === "string") action.link = resolve(action.link);
    }
  };
}
