// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

// Prefix the site base to root-relative links in Markdown, so pages write `/reference/` and the
// built site links to `/benchhand-next/reference/` (or `/reference/` when DOCS_URL is at a domain root).
// starlight-links-validator then sees the final URLs and checks them.
//
// The validator also reads the splash page's hero `actions[].link` from the front matter that this
// pipeline carries, so those links get the same prefix. The Hero component renders from the content
// collection's own copy of the front matter and prefixes the base itself (src/site-link.ts).
import { visit } from "unist-util-visit";

/** @param {{ base: string }} options base with a leading and a trailing slash */
export default function remarkBaseLinks({ base }) {
  const prefix = base.replace(/\/$/, "");
  const withBase = (/** @type {string} */ url) =>
    url.startsWith("/") && !url.startsWith("//") && !url.startsWith(`${prefix}/`) ? prefix + url : url;
  return (/** @type {import("mdast").Root} */ tree, /** @type {{ data: any }} */ file) => {
    if (!prefix) return;
    visit(tree, ["link", "image", "definition"], (node) => {
      const link = /** @type {{ url: string }} */ (node);
      link.url = withBase(link.url);
    });
    for (const action of file.data.astro?.frontmatter?.hero?.actions ?? []) {
      if (typeof action.link === "string") action.link = withBase(action.link);
    }
  };
}
