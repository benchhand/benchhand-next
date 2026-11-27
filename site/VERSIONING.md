# Versioning the docs site

The site publishes the latest build only (owner decision, 2026-11-27).
This note records how to publish more than one version later, what each option costs, and when to switch.
All sources were read on 2026-11-27; a source with no publication date says so.

## Recommendation

Keep latest-only until benchhand 1.0 ships. At the first release after 1.0 that raises a contract's major `x-version`, or the first time a 1.x line must stay documented beside a newer one, switch to per-version builds into subpaths of one Pages artifact (option B below).

Reasons:

- Nothing is released yet, and `docs/contract/versioning.md` says a narrowing keeps its version before the first release. Archiving versions now would archive drafts.
- A release already attaches a per-tag schema tarball with a `SHA256SUMS` (`release-docs`). That is the durable per-version record of the contracts until the site needs more.
- Option B reuses what exists: `release-docs` runs on a tag, `DOCS_URL` sets the base for each build, and a build of a tag's checkout regenerates the contract pages from that tag.
- The plugin (option A) keeps copies of the pages in the repository. The synced and generated pages are gitignored by design, so archived copies would have to be committed and could drift from the generator.

## Starlight options

### A. The `starlight-versions` plugin

Facts, from the plugin's docs on GitHub (`HiDeoo/starlight-versions`, main branch, read 2026-11-27) and the npm registry:

- The latest release is 0.10.2, published 2026-10-30. It needs `@astrojs/starlight` 0.39 or later; this site uses 0.43.2 (published 2026-11-26).
- Its docs call it opinionated and in early development, and warn to expect frequent changes.
- It uses folder-based versioning. Creating a version archives `src/content/docs/`, the assets and the sidebar configuration into a folder named for the version, such as `src/content/docs/1.0/`. The current docs stay in `src/content/docs/`.
- You add a version to `versions` in the plugin configuration and run the dev server, which archives the current state. Each version takes a `slug`, a `label` and a `redirect` strategy (`same-page` or `root`), and `current.label` names the latest build. `exclude` lists page globs that always show the latest content.
- The docs list the cost of versioning in general: more complexity, slower builds and more maintenance.
- Every version builds in one Astro run, so the site is one deployment.

Fit with this site, which is my reading, not the plugin's claim:

- `architecture/`, `adr/`, `reference/contracts/` and `reference/python-api/` are synced or generated and gitignored. The plugin would archive them as committed copies, or `exclude` would keep them latest-only, which defeats versioning the contract reference.
- Each archived version adds a copy of every hand-written page to the repository.

### B. Per-version builds into subpaths

Build each retained version from its tag and assemble one artifact:

- Check out `v1.0.x` and build with `DOCS_URL=https://<host>/<repo>/1.0/`; build the latest at the root. `site-url.mjs` already derives the base from `DOCS_URL`.
- Copy each build into `dist/<version>/` and upload the whole tree as one Pages artifact. A Pages deployment replaces the previous one, so every retained version must be in each deployment. Rebuild them all, or restore the earlier builds from a stored archive, for example a release asset or a branch.
- A version switcher is a Starlight component override that reads a `versions.json` written at assembly. A link to the same page in another version can 404, so fall back to that version's home page.
- The pages of each version are exactly what that tag generates, with no committed copies.

### C. A separate deployment per version

A branch or a separate Pages or hosting project for each version, with the main site linking to them. It isolates the builds, but it needs more than one Pages site, and a repository has one. I haven't researched it further, because B gives the same result in one deployment.

## What the schema `$id`s need

The `$id`s are `https://benchhand.github.io/benchhand/contracts/<dir>/<name>.schema.json`, with no version in them (owner decision, 2026-11-27). Each contract has its own `x-version`, a semver, in the schema.

- A site version, such as 1.0, doesn't map to one contract version. A contract page should show its `x-version`, and the versioned site shows the `x-version` that the tag carried.
- A `$id` names one schema, so it can only resolve to one build. It should resolve to the latest, at `/contracts/<name>` on the site root. A versioned copy at `/1.0/contracts/<name>` is not at the `$id`, and a tool that loads both under one `$id` would see two different documents with one identifier.
- Putting the major version into the `$id` (for example `.../contracts/v2/record/part.schema.json`) would give each major its own resolvable address. It also changes every identifier that `validate(schema_id, ...)`, the `$ref`s and stored data use, so it is a contract decision to take once, at the first major bump, not a docs change.
- The `$id`s don't resolve today, because the site isn't at the `$id` host (`README.md`, "The schema `$id`s"). Versioning doesn't change that.
- The per-release tarball keeps each tag's schemas by version, whatever the site shows.

## Pages size and build limits

From GitHub's "GitHub Pages limits" page (docs.github.com, no publication date, read 2026-11-27):

- A published site may be no larger than 1 GB.
- A deployment times out after 10 minutes.
- The soft bandwidth limit is 100 GB a month.
- The soft limit of 10 builds an hour doesn't apply to a site built and published by a custom Actions workflow, which this one is.

From the `actions/upload-pages-artifact` README (main branch, no publication date, read 2026-11-27): the artifact must be under 10 GB, and 1 GB is the recommended size, since a larger tarball is more likely to exceed the 10-minute deployment timeout.

## Build cost

Measured on 2026-11-27 on the author's Mac, for the current site:

| Measure | Value |
|---|---|
| Pages built | 124 |
| Files in `dist/` | 485 |
| Size of `dist/` | about 23 MB (HTML about 11 MB, `_astro` 9.5 MB, pagefind 1.4 MB, schemas 0.5 MB) |
| `pnpm build`, sync and Astro | about 13 s; Astro alone about 5 s |

Estimates for a versioned site, which I haven't measured:

- Option B, with N retained versions, costs N builds and about N times 23 MB. The size limit allows about 40 versions, but the 10-minute deployment timeout and the CI minutes bind first, and a long list is hard to use. Keep the latest and the supported minors, five or fewer.
- The CI cost of B is N times about 13 s plus the installs, unless earlier builds are restored from an archive. A rebuild of an old tag needs its own pinned toolchain, so an archive is safer than a rebuild of an old tag with newer tools.
- Option A has one Astro run, with the page count multiplied by the versions.

## Limits of the latest-only setup to keep in mind

- `release-docs` deploys whatever tag it runs on. A backport tag, such as `v0.9.1` after `v1.0.0`, would replace the site with the older docs. Before the first backport, deploy only when the tag is the highest `v*` tag, or move to option B.
- The `github-pages` environment must allow `v*` tags (`README.md`, "Workflows").
