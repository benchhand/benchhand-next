// @ts-check
import starlight from "@astrojs/starlight";
import { defineConfig } from "astro/config";
import mermaid from "astro-mermaid";
import starlightLinksValidator from "starlight-links-validator";

import { base, repoUrl, site } from "./site-url.mjs";
import remarkBaseLinks from "./src/remark-base-links.mjs";

export default defineConfig({
  site,
  base,
  markdown: { remarkPlugins: [[remarkBaseLinks, { base }]] },
  // src/site-link.ts links "repo:<path>" to the repository; site-url.mjs reads release.toml, so
  // components get its result as a constant rather than importing it.
  vite: { define: { __BENCHHAND_REPO_URL__: JSON.stringify(repoUrl) } },
  integrations: [
    // The architecture pages and the domain model draw their diagrams in Mermaid.
    // astro-mermaid must come before Starlight.
    mermaid({ autoTheme: true }),
    starlight({
      title: "benchhand",
      description: "An MCP server and CLI that guide an AI coding agent through a hardware design flow, with a design record.",
      logo: { light: "./src/assets/logo-light.svg", dark: "./src/assets/logo-dark.svg", alt: "" },
      // public/favicon.svg, Starlight's default path; it switches colour with prefers-color-scheme.
      favicon: "/favicon.svg",
      customCss: ["./src/styles/theme.css"],
      social: [{ icon: "github", label: "GitHub", href: repoUrl }],
      editLink: { baseUrl: `${repoUrl}/edit/main/site/` },
      components: {
        // Adds the "Planned" aside to pages that set `phase` (src/content.config.ts).
        MarkdownContent: "./src/components/MarkdownContent.astro",
        // Resolves the home page's action links against the site base and the repository.
        Hero: "./src/components/Hero.astro",
      },
      plugins: [starlightLinksValidator()],
      sidebar: [
        {
          label: "Start",
          items: [
            { label: "Home", link: "/" },
            { label: "Documentation index", link: "/docs/" },
            { autogenerate: { directory: "getting-started" } },
          ],
        },
        {
          label: "Guides and manual",
          items: [
            { label: "Tutorials", items: [{ autogenerate: { directory: "tutorials" } }] },
            { label: "The process", items: [{ autogenerate: { directory: "manual/process" } }] },
            { label: "The record", items: [{ autogenerate: { directory: "manual/record" } }] },
            { label: "Policy and CEL", items: [{ autogenerate: { directory: "manual/policy" } }] },
            { label: "Providers", items: [{ autogenerate: { directory: "manual/providers" } }] },
            { label: "Manufacturing", items: [{ autogenerate: { directory: "manual/manufacturing" } }] },
            { label: "Clients", items: [{ autogenerate: { directory: "manual/clients" } }] },
            { label: "Troubleshooting", items: [{ autogenerate: { directory: "manual/troubleshooting" } }] },
          ],
        },
        { label: "Architecture", items: [{ autogenerate: { directory: "architecture" } }] },
        {
          label: "Contracts",
          items: [
            { label: "Overview", link: "/reference/contracts/" },
            { label: "JSON Schemas", link: "/reference/contracts/schemas/" },
            { label: "Versioning", link: "/reference/contracts/versioning/" },
            { label: "Record migration", link: "/reference/contracts/record-migration/" },
            { label: "Provider protocol", link: "/reference/contracts/provider-protocol/" },
            { label: "Record documents", collapsed: true, items: [{ autogenerate: { directory: "reference/contracts/record" } }] },
            {
              label: "Provider, jobs and findings",
              collapsed: true,
              items: [
                { autogenerate: { directory: "reference/contracts/provider" } },
                { autogenerate: { directory: "reference/contracts/jobs" } },
                { autogenerate: { directory: "reference/contracts/common" } },
              ],
            },
            { label: "Domain model", collapsed: true, items: [{ autogenerate: { directory: "reference/contracts/domain-model" } }] },
          ],
        },
        { label: "Decision records", collapsed: true, items: [{ autogenerate: { directory: "adr" } }] },
        {
          label: "Reference",
          items: [
            { label: "Overview", link: "/reference/" },
            { label: "MCP tools", link: "/reference/mcp-tools/" },
            { label: "CLI", link: "/reference/cli/" },
            { label: "Flow", link: "/reference/flow/" },
            { label: "Codes and configuration", link: "/reference/codes/" },
            { label: "Python API", items: [{ autogenerate: { directory: "reference/python-api" } }] },
            { label: "TypeScript API", link: "/reference/typescript-api/" },
          ],
        },
        {
          label: "Roadmap",
          items: [
            { label: "Planned pages", link: "/planned/" },
            { label: "Changelog", link: "/changelog/" },
          ],
        },
      ],
    }),
  ],
});
