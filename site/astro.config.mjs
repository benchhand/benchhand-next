// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

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
  markdown: { remarkPlugins: [[remarkBaseLinks, { base, repoUrl }]] },
  // src/site-link.ts links "repo:<path>" to the repository; site-url.mjs reads release.toml, so
  // components get its result as a constant rather than importing it.
  vite: { define: { __BENCHHAND_REPO_URL__: JSON.stringify(repoUrl) } },
  integrations: [
    // The domain model draws its diagrams in Mermaid.
    // astro-mermaid must come before Starlight. Diagrams keep their natural size and scroll sideways
    // (theme.css) instead of shrinking to the column: useMaxWidth makes Mermaid size the SVG to 100%.
    mermaid({
      autoTheme: true,
      mermaidConfig: { flowchart: { useMaxWidth: false }, state: { useMaxWidth: false } },
    }),
    starlight({
      title: "benchhand",
      description: "An MCP server and CLI that guide an AI coding agent through a hardware design flow, with a design record.",
      logo: { light: "./src/assets/logo-light.svg", dark: "./src/assets/logo-dark.svg", alt: "" },
      // public/favicon.svg, Starlight's default path; it switches colour with prefers-color-scheme.
      favicon: "/favicon.svg",
      customCss: ["./src/styles/theme.css"],
      // A scrolling diagram must be reachable by keyboard: make each Mermaid panel a focusable region.
      head: [
        {
          tag: "script",
          content:
            "document.addEventListener('DOMContentLoaded',()=>{for(const d of document.querySelectorAll('pre.mermaid')){d.tabIndex=0;d.setAttribute('role','region');d.setAttribute('aria-label','Diagram, scrolls sideways');}});",
        },
      ],
      social: [{ icon: "github", label: "GitHub", href: repoUrl }],
      editLink: { baseUrl: `${repoUrl}/edit/main/site/` },
      components: {
        // Resolves the home page's action links against the site base and the repository.
        Hero: "./src/components/Hero.astro",
      },
      plugins: [starlightLinksValidator()],
      sidebar: [
        { label: "Get started", items: [{ autogenerate: { directory: "getting-started" } }] },
        {
          label: "Guides",
          items: [
            { label: "Tutorials", items: [{ autogenerate: { directory: "guides/tutorials" } }] },
            "guides/migration",
            "guides/writing-cel-rules",
            "guides/testing-rules",
            "guides/installing-providers",
            "guides/writing-a-provider",
            "guides/troubleshooting",
          ],
        },
        {
          label: "Concepts",
          items: [
            { label: "The design process", collapsed: true, items: [{ autogenerate: { directory: "concepts/process" } }] },
            { label: "The record", collapsed: true, items: [{ autogenerate: { directory: "concepts/record" } }] },
            { label: "Policy", collapsed: true, items: [{ autogenerate: { directory: "concepts/policy" } }] },
            { label: "Providers", collapsed: true, items: [{ autogenerate: { directory: "concepts/providers" } }] },
            { label: "Manufacturing", collapsed: true, items: [{ autogenerate: { directory: "concepts/manufacturing" } }] },
            { label: "Clients", collapsed: true, items: [{ autogenerate: { directory: "concepts/clients" } }] },
          ],
        },
        {
          label: "Reference",
          items: [
            { label: "Overview", link: "/reference/" },
            { label: "MCP tools", link: "/reference/mcp-tools/" },
            { label: "CLI", link: "/reference/cli/" },
            { label: "Flow", link: "/reference/contracts/flow/" },
            {
              label: "Contracts",
              collapsed: true,
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
              ],
            },
            { label: "Python API", collapsed: true, items: [{ autogenerate: { directory: "reference/python-api" } }] },
          ],
        },
        { label: "Contributing", items: ["contributing"] },
      ],
    }),
  ],
});
