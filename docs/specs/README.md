---
specs:
  - cel-pipeline
  - flow-engine
  - approvals
  - record-validation
not_yet_specced:
  - guide-service
  - version-snapshots
  - project-profile
  - selection-assessment
  - change-impact
  - existing-equipment
  - assembly-steps-and-coupons
  - annotation-set
---

# Capability specs

A spec turns one or more capabilities of the [catalogue](../architecture/capabilities.md) into requirements and work blocks. Each block is the size of one pull request. The catalogue says what exists and which phase builds the rest. The [issue register](../migration/issue-register.md) says what the prototype got wrong. The spec says what to build, in which order, and how a reviewer knows it is done.

`just specs` checks every spec, and `just specs --write` regenerates [phase-2.md](phase-2.md), the Phase 2 index. `just check` runs `just specs`.

## Files

- `README.md`: this page. Its front matter is the index of specs:
  - `specs` lists every spec id in order. The order breaks ties in the suggested block order.
  - `not_yet_specced` lists the Phase 2 capabilities that no spec covers yet.
- `<spec>.md`: one spec. Its file name is its id.
- `phase-2.md`: generated from the specs, the catalogue and the register. Don't edit it.

## Front matter

A spec starts with YAML front matter between two `---` lines. `tools/specs/capability_specs/spec.schema.json` is its schema.

| Key | What it holds |
|---|---|
| `spec` | The spec's id, which is its file name without `.md`. |
| `title` | The spec's title. |
| `status` | `draft`, `approved`, `in-progress`, `done` or `superseded`. |
| `capabilities` | The catalogue ids the spec covers. One spec covers a capability, at most. |
| `questions` | The catalogue's open-question ids that the spec depends on or works around. |
| `rules` | The register's design rules (`RULE-nn`) that the requirements apply. |
| `issues.closes` | Each register entry that a block closes: `id`, `block` and `test`, the test that proves the fix. |
| `issues.defers` | Each register entry joined to the spec that another capability closes: `id`, `to` (a capability id) and `reason`. |
| `blocks` | The work blocks: `id`, `title`, `size`, `requirements` and `depends_on`. |

A block id is a short upper-case prefix, a hyphen and a number, such as `FE-3`. Block ids are unique across every spec. `depends_on` holds three kinds of entry:

- a block id, of this spec or another;
- `question:<id>`, an open question of the catalogue. The block waits for the owner's answer;
- `capability:<id>`, a capability that no spec covers yet. When a spec covers it, the dependency names that spec's block instead.

`size` is `S` (a day or less), `M` (a few days) or `L` (a week or more), the scale of `docs/phases/prototype-port-331-341.md:30`.

## Body

The body has these sections, in this order.

1. **Baseline.** A line under the title: the commit of `main` the spec's pointers were checked against. The status is the front matter's, and the body doesn't repeat it.
2. **Capabilities.** Each capability id, linked to its catalogue entry, with the tools, CLI commands and contracts that the catalogue lists for it.
3. **Problem and users.** What goes wrong without the capability, and who meets it: the user, the agent, a provider author or a maintainer.
4. **Requirements.** A `## Requirements` section of bullets, each starting `- **REQ-n.**`, numbered from 1 within the spec. A requirement is testable. It cites its source: a `path:line` of the plan, an ADR or a contract page, or an issue-register id (`IR-nnn` or `RULE-nn`). A requirement with no source is marked `**Proposal**`, and it needs the owner's approval of the spec before its block starts. A requirement that waits on an open question names the question.
5. **Interfaces.** The MCP tools, CLI commands, contracts and provider methods the spec touches, with each new or changed contract named and its version bump.
6. **Issue register.** A table of the entries the spec closes, with the block and the test for each, and a table of the entries it defers, with the capability that closes each. A behaviour that another capability or a later phase must finish is named there as a handoff, with its capability.
7. **Prototype behaviour replaced.** The prototype files and symbols, as `docs/architecture/prototype-inventory.md` lists them, and the oracle tests under `reference/` whose cases the blocks port.
8. **Non-goals.** What the spec leaves out, and where it goes instead.
9. **Open questions.** Each catalogue question the spec cites, whether it blocks, and which blocks wait for it.
10. **Blocks.** One `### <id>: <title>` section for each block of the front matter. It gives the size and the dependencies, then a `**Scope.**` paragraph and an `**Acceptance.**` paragraph that names the tests.

A block is reviewable alone and leaves `main` green. A block that changes a contract changes the TypeSpec source, the generated files and the tests together.

## Register entries

A Phase 2 register entry is joined to a spec when one of its `prototype_paths` matches a prototype path that the catalogue lists for one of the spec's capabilities. It matches when it is the same file, or a file under a listed directory. The spec closes each joined entry, or defers it to the capability whose work closes it. A spec may also close an entry that isn't joined to it, when its blocks do the work. phase-2.md lists every Phase 2 entry that no spec closes.

## What `just specs` checks

- The index and each spec's front matter match their schemas, and each spec's id is its file name. A front-matter key given twice is refused, so a second key can't hide the first. Every Markdown file in `docs/specs/` is a listed spec, this page or the generated page.
- Every capability, open question, design rule and register id exists in the catalogue or the register, in the front matter and in the body.
- Every span in a spec's body that reads as a pointer, a path then a colon and a digit, is a repository-relative `` `path:line` `` or `` `path:first-last` ``. It names a file of the repository and lines that it has, and a range doesn't run backwards.
- A capability is covered by one spec at most. Each Phase 2 capability is covered by a spec or listed in `not_yet_specced`, and that list names only uncovered Phase 2 capabilities.
- Block ids are unique. Each dependency resolves to a block, a listed question or an uncovered capability, and the blocks form no cycle.
- The spec has a `## Requirements` section. Every top-level bullet in it is a well-formed REQ bullet, and no REQ bullet sits outside it. Each requirement cites a source that exists (a register id, a pointer that resolves, or `**Proposal**`), appears once and belongs to a block. Each block names only requirements of its spec.
- Each block has exactly one section, with its scope and its acceptance.
- A register entry is closed once, by a block of the closing spec. Specs that defer one entry agree on its capability. A deferral to a covered capability is closed by that capability's spec, and an entry that one spec closes isn't deferred by another to an uncovered capability. Each joined entry is closed or deferred.
- `phase-2.md` matches what `just specs --write` generates.

## Status

- `draft`: written, and waiting for the owner's review.
- `approved`: the owner approved it, and its blocks may start.
- `in-progress`: at least one block has merged.
- `done`: every block has merged, and the spec's issue entries are closed.
- `superseded`: another spec replaced it. It stays for its history.

A spec's blocks start after the owner approves it, and the phase still ends at its review gate (`docs/design-plan.md`, Steps).
