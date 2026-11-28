# benchhand Constitution

## Core Principles

### I. MCP Is the Workflow, and the Server Guides It

- The MCP server MUST be the only interface that runs the design workflow (ADR-0001).
- The `benchhand` CLI MUST stay a launcher and admin tool. It MAY add read-only subcommands that
  inspect a project.
- The server process MUST be the runner: it hosts the preview pages and manages the provider jobs
  (ADR-0004).
- Guidance MUST come from the server through `flow.guide` and the server instructions. Skills
  stay minimal (ADR-0011).
- Plain tool calls MUST work in every host. A rich interaction is an enhancement with a fallback
  chain (ADR-0008, ADR-0018).

### II. Contracts Have One Source

- Every owned message and record shape MUST have exactly one source, in TypeSpec under
  `contracts/`, emitted to JSON Schema 2020-12 (ADR-0017).
- Python models, TypeScript types, MCP tool schemas and reference docs MUST be generated from
  that source. Nobody hand-writes a copy of a shape.
- Generated output MUST NOT be edited by hand. A fix goes into the source, and the files are
  regenerated.
- A contract change MUST follow `docs/contract/versioning.md`, with a version bump and a
  migration note when it changes a shape.

### III. Every Integration Is a Provider

- Kernels, the CAD application, solvers, the renderer, process checks, part sources, artifact
  storage and policy MUST sit behind a provider interface (ADR-0006).
- Providers MUST run out of process over the provider protocol, JSON-RPC 2.0 over stdio, each in
  its own environment (ADR-0013).
- The core MUST NOT import a CAD kernel or FreeCAD.
- GPL and AGPL tools MUST run only as separate processes or containers, never imported
  (RULE-44).

### IV. The Flow Is Data, the Rules Are CEL, and Gates Guide

- The stage and gate graph MUST be data in `flow.yaml`. Every condition in it MUST be CEL,
  compiled and checked before load (ADR-0014, ADR-0020).
- Gates steer the standard process. They are not a security control (ADR-0003).
- A stage moves only through `flow.transition`. A gate's approval MUST be recorded in its decision
  record, which names the transition it approves (RULE-35).
- Design freeze and release MUST always need the user's explicit approval. A policy that sets
  either gate to `auto` MUST be refused when it loads (owner, 2026-11-28).
- Building and checking MAY run at any stage. Tools that seal, freeze or release MUST be
  checked against the stage (owner, 2026-11-28).
- A design change MUST reopen only the approvals it touches (ADR-0019).

### V. Results Are Honest

- Unknown MUST never count as pass. Not applicable MUST be explicit and carry its reason. A
  result MUST NOT drop an item without a finding (RULE-05).
- Malformed input MUST give a named finding, never a crash. Exit 2 is reserved for usage and
  infrastructure errors (RULE-08).
- An aggregate of passes and not-assessed checks MUST report not_assessed, never pass (RULE-34).
- A result's first finding MUST be its first actionable one, with its subject and `path:line`
  (owner, 2026-11-28).
- A freeze MUST carry the evidence digest, and MUST be refused when the evidence assessment
  refuses (owner, 2026-11-28).

### VI. The Record Is the Truth; Derived State Is Disposable

- The authored record MUST live in `design/`, sealed output in `.benchhand/sealed/`, and
  deliverables in `releases/<REV>/` (ADR-0023).
- `state.sqlite` and every cache MUST NOT hold the only copy of anything that matters. Deleting
  them MUST lose no work.
- A sealed version MUST be immutable. Versions MUST be sealed on the main line only.
- Each sealed artifact MUST be content-addressed by its sha256, and the record MUST state each
  approval's fingerprint.

### VII. STEP AP242 Is the Primary Exchange Format

- Every model MUST export to STEP AP242, and AP242 is the primary format for exchange and review.
- `product.step` MUST hold only what ships: subassemblies, then `[Made]` and `[Purchased]` within
  each, then the kit (owner, 2026-11-28).
- Context, tooling, joints, poses, envelopes, findings and construction geometry MUST go into a
  scene file that is never released. Working geometry MUST be hidden by default.
- The same structure MUST apply to a single part and to an assembly.

### VIII. Rewrite to the Prototype's Behaviour

- The prototype `benchhand/benchhand` is a behavioural reference, not code to port (ADR-0012).
- `reference/` MUST stay read-only. Its cases are ported into new tests.
- Every prototype issue and bead MUST be tracked in `docs/migration/issue-register.yaml`. The
  register's design rules are binding product rules.
- `release.toml` `reference_commit` MUST record the last prototype commit reflected here.
  `just reference-changes` lists what landed after it (ADR-0015).
- The repo swap MUST wait until benchhand-next matches the prototype on the golden end-to-end run.

### IX. Tests Test Real Behaviour

- Tests MUST follow `docs/testing.md`. Each test guards behaviour benchhand has, and prefers one
  real path over several mocked units.
- Tests MUST NOT test generated code, third-party libraries, or a mock against itself.
- A test that needs FreeCAD, a kernel or Chromium MUST run with the end-to-end tests, unless it is
  a provider's own conformance test.
- Test data MUST be synthetic, or the public LMP lamp-arm fixture. Test-project geometry MUST
  NOT be copied into the tool's tests (RULE-22).

### X. Public by Default

- The repository is public. Tracked files, beads and specs MUST carry no test-project data and no
  home-directory paths. `just issues` enforces the private patterns.
- Every source file MUST carry SPDX headers, and `reuse lint` MUST pass. Owned code is MPL-2.0.
- Third-party code keeps its licence. A design from another project MUST be rewritten unless the
  owner approves porting that file (RULE-46).
- Secrets MUST never enter the repository, a command line or a log.

## Technology and Quality Constraints

- **Languages:** a Python host and core, kernel and FreeCAD providers in their own Python
  environments, and TypeScript for the browser UIs. Rust is not used (ADR-0012).
- **Workspaces:** a uv workspace for Python and a pnpm workspace for the UIs and contracts.
- **Complexity:** functions MUST stay within the ruff complexity limits. `just lint` enforces the
  limits at their configured values, and a change that exceeds them is refactored.
- **Types:** `just typecheck` (pyright and the UI type check) MUST pass with no errors.
- **Tools:** the repo's tools are pinned through mise. End users do not need mise.
- **FreeCAD:** each release lists its supported FreeCAD versions in `freecad-versions.toml`,
  and only those are supported (ADR-0005).
- **Feature flags:** new behaviour that is not ready ships behind an OpenFeature flag in
  `packages/benchhand/src/benchhand/flags.yaml`, off by default. Only the CLI or server edge
  evaluates a flag, once per run. Each flag names its owner and removal date.
- **The full check:** `just check` MUST pass before a commit is merged into `main`.

## Development Workflow

- **Specs:** features are specified with Spec Kit in `specs/NNN-slug/`. Each flow stage and each
  platform area has its own spec. The earlier `docs/specs/` is archived once `specs/` replaces it.
- **Tasks:** task state lives in the beads ledger (`bhn`), never in `tasks.md` (speckit-beads).
  Each commit and PR names its bead.
- **Phases:** each phase of `docs/design-plan.md` ends at a review gate. The phase doc
  `docs/phases/phase-N.md` is written, the built code is run against a copy of a real record, and
  the owner approves before the next phase's work merges.
- **Decisions:** a decision that is hard to reverse gets an ADR in `docs/adr/`. An owner decision
  is dated and cited where it applies.
- **Changes:** work is trunk-based on short branches. A PR states its bead, and a `Flag:` line
  when it adds a flag.
- **Subagents:** each subagent launch names its model. The strongest model does boundary work, a
  cheaper model does work a contract or test bounds, and a different model family reviews.
- **Docs:** the user docs site documents benchhand as at its first release. Generated reference
  stays generated. Deliverable prose passes slopvac.

## Governance

- This constitution overrides any practice that conflicts with it. `AGENTS.md` holds the
  day-to-day guidance for agents. ADRs and the design plan hold the detailed decisions.
- An owner decision that conflicts with a principle amends this constitution, through
  `/speckit.constitution`, before work relies on it.
- Versions follow semantic versioning:
  - MAJOR: a principle is removed or redefined;
  - MINOR: a principle or section is added, or materially expanded;
  - PATCH: wording only.
- `/speckit.plan` MUST pass its Constitution Check, and `/speckit.analyze` MUST report no
  violation, before implementation starts. A justified exception is recorded in the plan's
  Complexity Tracking table.
- Reviews check each change against these principles. A violation is a blocking finding.

**Version**: 1.0.0 | **Ratified**: 2026-11-28 | **Last Amended**: 2026-11-28
