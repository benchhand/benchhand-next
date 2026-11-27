# The benchhand documentation site

An [Astro Starlight](https://starlight.astro.build/) site, built from this directory with pnpm.
Node and pnpm are pinned in `package.json` (`engines`, `packageManager`).

```sh
pnpm --dir site install --frozen-lockfile
pnpm --dir site build      # sync, then astro build with the links validator
pnpm --dir site test       # each schema's $id is served by the build
pnpm --dir site preview    # serve dist/
```

## Where the site is published

The site is published on GitHub Pages for `benchhand/benchhand-next`, at `https://benchhand.github.io/benchhand-next/`.
A custom domain comes later.

`site-url.mjs` holds the one config value, the environment variable `DOCS_URL`. It is the full URL of the site root, and the site's origin and base path are both derived from it:

| `DOCS_URL` | Origin | Base |
|---|---|---|
| unset | `https://<owner>.github.io` | `/<name>/`, with owner and name from `release.toml` `repo` |
| `https://docs.example.org/` | `https://docs.example.org` | `/` |
| `http://localhost:4321/` | `http://localhost:4321` | `/` |

The workflows read `DOCS_URL` from a repository variable of the same name, and use the default when it is unset.
Because the default follows `release.toml`, the repo swap moves the site to `https://benchhand.github.io/benchhand/` without an edit.

### Switch to a custom domain

1. In the DNS zone, add a `CNAME` record from the host name (for example `docs.example.org`) to `benchhand.github.io`.
2. In the repository's Settings, Pages, enter the custom domain and enable HTTPS. A site that a workflow deploys takes its domain from this setting; a `CNAME` file in the artifact is ignored.
3. Set the repository variable `DOCS_URL` to `https://docs.example.org/`. The base becomes `/`, so no path prefix remains.
4. Run the `release-docs` workflow again, or the `docs-site` workflow by hand, to rebuild with the new URL.

### The schema `$id`s

Every schema's `$id` is `https://benchhand.github.io/benchhand/contracts/<name>` (owner decision, 2026-11-27), and the site serves `<name>` at `/contracts/<name>` below its root.
`pnpm test` checks that mapping for every schema: the path of the `$id` below its prefix must be a file under `dist/contracts/` with the schema's own bytes.

The `$id`s don't resolve until the site is published at `https://benchhand.github.io/benchhand/`, or at a domain that redirects to that address.
Until then they identify the schemas without locating them. The JSON Schemas page lists where this site serves each one.

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

`src/remark-base-links.mjs` then prefixes the base to every root-relative link, so pages write `/reference/` under any base.
`astro.config.mjs` `KNOWN_BROKEN_LINKS` excludes the broken anchors that the synced sources contain, one by one.

## Placeholder pages

A page whose front matter sets `phase: N` is an outline of a page that Phase N of `docs/design-plan.md` writes.
`src/components/MarkdownContent.astro` shows the "Planned" aside on it, so its own prose carries no status wording.
`scripts/planned-pages.mjs` fails the build when a `phase` names no phase of the plan, or when such a page has status wording of its own.
It lists the pages by phase on `/planned/`.

## The Python API

`scripts/python-api.mjs` runs griffe (pinned in the script, through `uvx`), which reads `benchhand_contracts` without importing it, and renders the dump to MDX. It has these limits:

- It renders one package, `benchhand-contracts`, and only its public names. "Public" is defined once, by `publicNames` in the script: the names in a module's `__all__` where it has one, otherwise the functions, classes and attributes it defines without a leading underscore. `python-api.test.mjs` tests it.
- The renderer expects the repository's docstring style, reStructuredText-flavoured text. It doesn't parse Args, Returns or Raises sections.
- `benchhand-provider`, the provider runtime, has a hand-written placeholder page, `reference/python-api/benchhand-provider.md`, with `phase: 4`. The renderer takes it over when the package has a public API on main.
- It renders functions and classes only. A class lists its public attributes and methods, and `__init__`.
- It shows docstrings as text. It turns reST ``` ``code`` ``` and `:role:` references into code spans.
- A griffe expression type that it doesn't know fails the render.
- It leaves out the generated models under `benchhand_contracts.models`, because the contract reference documents them.

The build needs `uvx` on `PATH` for this step.

## Mermaid

The architecture pages and the domain model draw their diagrams in Mermaid. `astro-mermaid` renders them in the browser.
The sync copies the `.svg` and `.png` files of the synced directories next to their pages, so a committed D2 SVG renders where its Markdown embeds it.
An image elsewhere in the repository links to its raw file on GitHub.
