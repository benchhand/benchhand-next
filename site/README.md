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

The `$id`s resolve only when the site is published at `https://benchhand.github.io/benchhand/`, or when each `$id` URL redirects to the URL where the site serves that schema.
The JSON Schemas page carries a notice when the configured `DOCS_URL` doesn't serve the schemas at their `$id`s.
Until then they identify the schemas without locating them. The JSON Schemas page lists where this site serves each one.

## Workflows

- `docs-site` runs on pull requests that touch the site, `docs/`, `contracts/`, the generator, or the packages whose schemas, Python API and CLI the site documents. It runs `just contracts-drift` and fails when the committed generated files differ from a fresh run, then builds the site with the links validator and runs `pnpm test`. A run by hand also deploys to Pages.
- `release-docs` runs when a release is published and when a `v*` tag is pushed. Both run `just contracts-drift` on the tagged commit, regenerate the generated docs and build the site; a tag push stops there. A published release then
  - deploys the site to Pages, but only when its tag is the highest stable `vX.Y.Z` tag at that moment. The job checks this through the GitHub API inside the shared `pages` concurrency group, and a backport, an older release or a prerelease skips the deploy and says why in the job summary;
  - attaches `benchhand-schemas-<tag>.tar.gz` and `SHA256SUMS` to the release in every case. An upload failure fails the job.

The `github-pages` environment allows only the default branch by default. Add the tag pattern `v*` under Settings, Environments, `github-pages`, Deployment branches and tags, or the release run's deploy job is refused.

The versions of the tools in these workflows are pinned. `just` and D2 come from the versions in the workflow and `mise.toml`; keep them in step with `ci.yml`.

The site shows the latest build only. `VERSIONING.md` covers publishing a version for each release.

## What is hand-written and what is synced

Hand-written pages are the Markdown files that git tracks under `src/content/docs/`.
slopvac lints them, with the repository's `slopvac.toml`.

`pnpm sync`, which `pnpm build` runs first, writes these gitignored files:

| Script | Writes | From |
|---|---|---|
| `scripts/sync-docs.mjs` | `src/content/docs/reference/contracts/` | `docs/contract/*.md` and `docs/contract/generated/**` |
| | `public/contracts/` and `reference/contracts/schemas.md` | the published schemas in `packages/benchhand-contracts/src/benchhand_contracts/schemas/` |
| `scripts/python-api.mjs` | `src/content/docs/reference/python-api/` | griffe's dump of `benchhand_contracts`, `benchhand_provider` and `benchhand_sdk` |
| `scripts/cli-reference.mjs` | `src/content/docs/reference/cli.md` | Typer's `utils docs` on `benchhand.cli` |

Edit the sources, not the copies. Each synced page's edit link points at its source, and a generated page has none.
The design plan, the decision records and the architecture pages stay in the repository: a synced page that links to one links to it on GitHub.

### How the sync changes a page

- The first H1 becomes the front matter `title`. Each `README.md` becomes its directory's index page.
- A contract field page whose title names its file, such as `hw/parts/<PN>/part.yaml`, has that file name as its sidebar label.
- A relative link to a synced page becomes its site route, for example `../../common/finding.md` in a domain-model page becomes `/reference/contracts/common/finding/`. The heading anchor stays.
- A relative link to any other file in the repository becomes its GitHub URL on `main`, for example `../design-plan.md` and `contracts/record/part.tsp`. An image becomes its raw URL.
- A relative link to a file that doesn't exist fails the sync. Fix the link in the source doc; the sync has no exception list.
- Links inside code and Mermaid blocks are left alone.

The sync prints a count per rule and writes every rewrite to `.cache/link-rewrites.tsv`.

`src/remark-base-links.mjs` then prefixes the base to every root-relative link, so pages write `/reference/` under any base, and turns a `repo:docs/design-plan.md` link into the file's GitHub URL.
It does the same for the home page's hero links in the front matter, where the links validator reads them. `src/components/Hero.astro` renders those links through `src/site-link.ts`.
The links validator then fails the build on any broken page link or anchor, and has no exclusions.

## The CLI reference

`scripts/cli-reference.mjs` runs `uv run --locked typer benchhand.cli utils docs` in the workspace environment and writes the result as the CLI page.
Change a command's help in `packages/benchhand/src/benchhand/cli.py`; the build needs `uv` on `PATH` and the workspace synced.

## The Python API

`scripts/python-api.mjs` runs griffe (pinned in the script, through `uvx`), which reads each package without importing it, and renders the dump to MDX. It has these limits:

- It renders three packages, `benchhand-contracts`, `benchhand-provider` and `benchhand-sdk` (`PACKAGES` in the script), and only their public names. "Public" is defined once, by `publicNames` in the script: the names in a module's `__all__` where it has one, otherwise the functions, classes and attributes it defines without a leading underscore. `python-api.test.mjs` tests it.
- The renderer expects the repository's docstring style, reStructuredText-flavoured text. It doesn't parse Args, Returns or Raises sections.
- It renders functions and classes only. A class lists its public attributes and methods, and `__init__`.
- It shows docstrings as text. It turns reST ``` ``code`` ``` and `:role:` references into code spans.
- A griffe expression type that it doesn't know fails the render.
- It leaves out the generated models under `benchhand_contracts.models`, because the contract reference documents them.

The build needs `uvx` on `PATH` for this step.

## Mermaid

The domain model draws its diagrams in Mermaid. `astro-mermaid` renders them in the browser.
The sync copies the `.svg` and `.png` files of the synced directories next to their pages, so a committed D2 SVG renders where its Markdown embeds it.
An image elsewhere in the repository links to its raw file on GitHub.
