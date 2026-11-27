/// <reference types="astro/client" />
// Turn a link written in a page's front matter or a component prop into the URL the built site uses.
// - "/reference/" is a site route: the site base is prefixed, as remark-base-links does for Markdown.
// - "repo:docs/design-plan.md" is a file in the repository: it links to the file on GitHub, so the
//   repository name stays in release.toml (ADR-0015).
// - Anything else (an absolute URL, "#anchor") is kept.

// astro.config.mjs defines it from site-url.mjs.
declare const __BENCHHAND_REPO_URL__: string;
const repoUrl = __BENCHHAND_REPO_URL__;

export function siteLink(link: string): string {
  if (link.startsWith("repo:")) return `${repoUrl}/blob/main/${link.slice("repo:".length)}`;
  if (link.startsWith("/") && !link.startsWith("//")) {
    const base = import.meta.env.BASE_URL.replace(/\/$/, "");
    return link.startsWith(`${base}/`) ? link : `${base}${link}`;
  }
  return link;
}
