// Prefix the site base to root-relative links in Markdown, so pages write `/reference/` and the
// built site links to `/benchhand-next/reference/` (or `/reference/` when DOCS_URL is at a domain root).
// starlight-links-validator then sees the final URLs and checks them.
import { visit } from "unist-util-visit";

/** @param {{ base: string }} options base with a leading and a trailing slash */
export default function remarkBaseLinks({ base }) {
  const prefix = base.replace(/\/$/, "");
  return (/** @type {import("mdast").Root} */ tree) => {
    if (!prefix) return;
    visit(tree, ["link", "image", "definition"], (node) => {
      const url = /** @type {{ url: string }} */ (node).url;
      if (url.startsWith("/") && !url.startsWith("//") && !url.startsWith(`${prefix}/`)) {
        /** @type {{ url: string }} */ (node).url = prefix + url;
      }
    });
  };
}
