# The benchhand documentation site

An [Astro Starlight](https://starlight.astro.build/) site, built from this directory with pnpm.
Node and pnpm are pinned in `package.json` (`engines`, `packageManager`).

```sh
pnpm --dir site install --frozen-lockfile
pnpm --dir site build      # sync, then astro build with the links validator
pnpm --dir site test       # each schema's $id is served by the build
pnpm --dir site preview    # serve dist/
```

## Base path and URL

`site-url.mjs` reads two environment variables:

| Variable | Default | Use |
|---|---|---|
| `DOCS_SITE` | `https://benchhand.github.io` | The origin the site is published at. |
| `DOCS_BASE` | `/benchhand` | The path below the origin. Set `DOCS_BASE=/` for a local copy. |

The contracts' `$id`s are `https://benchhand.github.io/benchhand/contracts/...`.
With the defaults, the site serves each published schema at its `$id`, and `pnpm test` checks that.
`pnpm test` reads the same variables as the build, so run both with the same values.

## What is hand-written and what is synced

Hand-written pages are the Markdown files that git tracks under `src/content/docs/`.
slopvac lints them, with the repository's `slopvac.toml`.

`pnpm sync`, which `pnpm build` runs first, writes these gitignored files:

| Script | Writes | From |
|---|---|---|
| `scripts/sync-docs.mjs` | `src/content/docs/architecture/` | `docs/architecture/*.md` |
| | `src/content/docs/adr/` | `docs/adr/*.md` |
| | `src/content/docs/reference/contracts/` | `docs/contract/*.md` and `docs/contract/generated/**` |
| | `public/contracts/` and `reference/contracts/schemas.md` | the published schemas in `packages/benchhand-contracts/src/benchhand_contracts/schemas/` |
| `scripts/python-api.mjs` | `src/content/docs/reference/python-api/` | griffe's dump of `benchhand_contracts` |
| `scripts/planned-pages.mjs` | `src/content/docs/planned.md`, `src/generated/plan-phases.json` | the `phase` of each page, and `docs/design-plan.md` |

Edit the sources, not the copies. Each synced page's edit link points at its source.

### How the sync changes a page

- The first H1 becomes the front matter `title`. Each `README.md` becomes its directory's index page.
- A relative link to a synced page becomes its site route, for example `../adr/0017-contracts.md` becomes `/adr/0017-contracts/`. The heading anchor stays.
- A relative link to any other file in the repository becomes its GitHub URL on `main`, for example `../design-plan.md` and `contracts/record/part.tsp`. An image becomes its raw URL.
- A relative link to a file that doesn't exist fails the sync. `KNOWN_MISSING_TARGETS` lists the known exceptions, each with its reason. They are still rewritten to GitHub.
- Links inside code and Mermaid blocks are left alone.

The sync prints a count per rule and writes every rewrite to `.cache/link-rewrites.tsv`.

`src/remark-base-links.mjs` then prefixes `DOCS_BASE` to every root-relative link, so pages write `/reference/` under any base.
`astro.config.mjs` `KNOWN_BROKEN_LINKS` excludes the broken anchors that the synced sources contain, one by one.

## Placeholder pages

A page whose front matter sets `phase: N` is an outline of a page that Phase N of `docs/design-plan.md` writes.
`src/components/MarkdownContent.astro` shows the "Planned" aside on it, so its own prose carries no status wording.
`scripts/planned-pages.mjs` fails the build when a `phase` names no phase of the plan, or when such a page has status wording of its own.
It lists the pages by phase on `/planned/`.

## The Python API

`scripts/python-api.mjs` runs griffe (pinned in the script, through `uvx`), which reads `benchhand_contracts` without importing it, and renders the dump to MDX. It has these limits:

- It renders one package, `benchhand-contracts`, and only the names in its `__all__`.
- It renders functions and classes only. A class lists its public attributes and methods, and `__init__`.
- It shows docstrings as text. It turns reST ``` ``code`` ``` and `:role:` references into code spans, and it doesn't parse Args, Returns or Raises sections.
- A griffe expression type that it doesn't know fails the render.
- It leaves out the generated models under `benchhand_contracts.models`, because the contract reference documents them.

The build needs `uvx` on `PATH` for this step.

## Mermaid

The architecture pages and the domain model draw their diagrams in Mermaid. `astro-mermaid` renders them in the browser.
The sync copies the `.svg` and `.png` files of the synced directories next to their pages, so a committed D2 SVG renders where its Markdown embeds it.
An image elsewhere in the repository links to its raw file on GitHub.
