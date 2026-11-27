// @ts-check
import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";
import mermaid from "astro-mermaid";
import starlightLinksValidator from "starlight-links-validator";

import { base, repoUrl, site } from "./site-url.mjs";
import remarkBaseLinks from "./src/remark-base-links.mjs";

// Links that are broken in the synced sources and must be fixed there, each excluded exactly.
const KNOWN_BROKEN_LINKS = new Set([
  // tools/gen links manufacturing-selection's `transparency` property to a part.md heading that
  // doesn't exist: part.md declares transparency as an inline enum, not a definition.
  `${base}reference/contracts/record/part/#transparency`,
]);

export default defineConfig({
  site,
  base,
  markdown: { remarkPlugins: [[remarkBaseLinks, { base }]] },
  integrations: [
    // The architecture pages and the domain model draw their diagrams in Mermaid.
    // astro-mermaid must come before Starlight.
    mermaid({ autoTheme: true }),
    starlight({
      title: "benchhand",
      description: "An agent-driven, record-first CAD workflow over MCP.",
      social: [{ icon: "github", label: "GitHub", href: repoUrl }],
      editLink: { baseUrl: `${repoUrl}/edit/main/site/` },
      // Adds the "Planned" aside to pages that set `phase` (src/content.config.ts).
      components: { MarkdownContent: "./src/components/MarkdownContent.astro" },
      plugins: [
        starlightLinksValidator({ exclude: ({ link }) => KNOWN_BROKEN_LINKS.has(link) }),
      ],
      sidebar: [
        { label: "Home", link: "/" },
        { label: "Getting started", items: [{ autogenerate: { directory: "getting-started" } }] },
        { label: "Tutorials", items: [{ autogenerate: { directory: "tutorials" } }] },
        {
          label: "Manual",
          items: [
            { label: "The process", items: [{ autogenerate: { directory: "manual/process" } }] },
            { label: "The record", items: [{ autogenerate: { directory: "manual/record" } }] },
            { label: "Policy and CEL", items: [{ autogenerate: { directory: "manual/policy" } }] },
            { label: "Providers", items: [{ autogenerate: { directory: "manual/providers" } }] },
            { label: "Manufacturing", items: [{ autogenerate: { directory: "manual/manufacturing" } }] },
            { label: "Clients", items: [{ autogenerate: { directory: "manual/clients" } }] },
            { label: "Troubleshooting", items: [{ autogenerate: { directory: "manual/troubleshooting" } }] },
          ],
        },
        {
          label: "Reference",
          items: [
            { label: "Overview", link: "/reference/" },
            { label: "MCP tools", link: "/reference/mcp-tools/" },
            { label: "CLI", link: "/reference/cli/" },
            { label: "Flow", link: "/reference/flow/" },
            { label: "Codes and configuration", link: "/reference/codes/" },
            {
              label: "Contracts",
              collapsed: true,
              items: [{ autogenerate: { directory: "reference/contracts" } }],
            },
            { label: "Python API", items: [{ autogenerate: { directory: "reference/python-api" } }] },
            { label: "TypeScript API", link: "/reference/typescript-api/" },
          ],
        },
        {
          label: "Architecture",
          items: [
            { label: "Diagrams", items: [{ autogenerate: { directory: "architecture" } }] },
            { label: "Decision records", collapsed: true, items: [{ autogenerate: { directory: "adr" } }] },
          ],
        },
        { label: "Changelog", link: "/changelog/" },
        { label: "Planned pages", link: "/planned/" },
      ],
    }),
  ],
});
