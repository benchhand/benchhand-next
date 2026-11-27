# CAD Agent platform: MCP server, middleware, and packaging

Status: revision 4. It applies the 7 review comments on revision 3 and the temporary-repo note. D1–D9 were settled in the Inbox thread "CAD platform design", and D10–D17 come from the plan reviews.

## Decisions

| # | Topic | Decision |
|---|---|---|
| D1 | Interface | MCP is the only way to run the workflow. The product is called **benchhand**, and so are its CLI and its new repo. The CLI is a thin launcher and admin tool: `benchhand mcp`, `benchhand serve`, `install`, `doctor`, `setup`, `policy`, `rules compile` and `debug call`. Providers can add subcommands (section 7). The per-skill `uv run --script` commands are not carried over. |
| D2 | Install | No separate install step. Each harness's MCP config runs `uvx benchhand@<ver> mcp`, and uv fetches and caches the package on first start. `uv tool install benchhand` is optional, for pinned or offline use. An optional OCI image ships FreeCAD, both kernels, Chromium and the cache. It is started through the same entry point: `uvx benchhand@<ver> mcp --container` is a small launcher that runs the configured container runtime (Docker, Podman, nerdctl or Colima) with `run -i`, forwards stdio, and cleans up the container. The harness only ever starts a normal command (section 8). |
| D3 | Gates | Gates steer the standard process; they are not a security control. The server doesn't defend against a malicious agent. It makes the guided path the easy one, and catches honest mistakes such as skipped steps, approval without asking, or a stale version. Each project sets a mode per gate in `hw/policy.yaml`: `ask` (the default) \| `chat` \| `auto` (for dev and tests). `benchhand policy` and the `policy.*` resources change it, and every relaxation is recorded in a DR. |
| D4 | Server and runner lifetime | The harness starts the MCP server from its config. That process **is** the runner: it hosts the preview, viewer, concept and prototype pages on loopback HTTP, and it manages the provider workers and jobs. It lives as long as the harness session, so the spike isn't needed. A slow first start is acceptable next to how long CAD jobs take. `benchhand serve` runs the same preview host without an agent, for browsing a project. |
| D5 | FreeCAD | Supported versions are listed explicitly in `freecad-versions.toml`, shipped with each benchhand release. Each entry has the version, platforms, download URLs, sha256 and a status: `supported`, `deprecated` or `removed`. The managed download (with your consent, into `~/.local/share/benchhand/freecad/<ver>`) offers only supported versions. A host FreeCAD is accepted only if its version is on the list. Any other version is refused with a fix; `--allow-unsupported` exists for development only, and its results are marked UNKNOWN. When FreeCAD releases a new version, we qualify it with the compatibility suite in our CI, add it to the list, and ship a release. |
| D6 | Plugins | Every part of the system goes behind a provider interface from the first release: kernels, the CAD application, solvers, the renderer and viewers, process checks, artifact storage, and policy. Kernels, process checks and policy get full docs and conformance kits first; the rest are documented as experimental. |
| D7 | Build API | Output tools, part SDK, parametric generators, inspect tools, draft preview, concept scene tools, viewer and gallery control, typed record operations, engineering calculators, and the layout skeleton as a reviewable draft. |
| D8 | Client features | Interaction adapts to each client's capabilities, with a fallback chain for each interaction (section 11). |
| D9 | First-class hosts | Claude Code CLI, Claude Desktop, Codex CLI, the Codex / ChatGPT desktop app, OpenCode, Kiro CLI and Pi. Other MCP hosts work through the fallbacks without a guarantee. |
| D10 | Transport | **stdio** by default, with `benchhand mcp --http` as an option (section 3). |
| D11 | Steering | Guidance comes from the server, and skills are minimal. One bootstrap skill and the server `instructions` tell the agent to call `flow.guide`. That tool returns the current stage's instructions, the relevant tools and the next action (section 9). |
| D12 | Language | Chosen as a greenfield design, without weighing reuse: a **Python** host and core, kernel and FreeCAD providers in their own Python environments, and **TypeScript** for the browser UIs. Rust is not used. Existing code is a behavioural reference, not something carried over wholesale: each module is rewritten where that gives cleaner separation, better abstraction or other gains, and kept only where it is already clean (section 4). |
| D13 | Provider protocol | Providers are out-of-process JSON-RPC 2.0 plugins on the slopvac 3.0 plugin protocol, plus progress and artifact messages. Each provider runs in its own environment, which also keeps the kernels' OCP versions apart (section 6). |
| D17 | Contracts | Every owned contract has one machine-readable source in TypeSpec under `contracts/`, emitted to JSON Schema 2020-12 (ADR-0017): the provider protocol, MCP tool inputs and outputs, the result envelope, the record schemas, `flow.yaml` and policy files. Python models, TypeScript types, MCP tool schemas and reference docs are generated from the published schemas. A CI check fails on drift, and runtime validation enforces the contracts at every boundary (section 6a). |
| D14 | Flow and rules | One rules language: **CEL**. The stage and gate graph is structure, so it is data (`flow.yaml`): nodes, gates and edges. Every condition in it is CEL: transition guards, gate requirements, VOID cascade scope, check selection and process dispatch. Decision tables become ordered CEL rule lists, written as cel-policy files and compiled before load (ADR-0020). GoRules ZEN is dropped. React Flow renders the flow state (section 5). |
| D15 | Repo | Work happens in a temporary new repo, `benchhand/benchhand-next`, set up as a two-level uv workspace plus a pnpm UI workspace. The current repo, `github.com/benchhand/benchhand` (checked out locally as `cad-agent`), stays the reference until `benchhand-next` matches it on the golden end-to-end run. Then the two are swapped (see "Repo swap"). |
| D16 | Capability probe | A dev-only tool (`tools/probe/`), run by hand in each host. It isn't shipped to end users and isn't run in CI. |

## Context

The prototype (`cad-agent`) is 15 harness skills (`skills/cad-*`), about 90k lines of Python, run as PEP 723 `uv run --script` CLIs through `skills/cad-flow/scripts/run.py`. It works, but it is hard to install and manage:

- **Install has many steps.**
  - Clone the repo, then run `harness/install.py --harness X`.
  - Set `$CAD_SKILLS`.
  - Run `setup.py`, then `setup.py --yes`.
  - Run `preflight.py --warm --background`, then `--status --wait`.
  - Install FreeCAD 1.1.4 by hand.
- **Deterministic logic sits in skill folders, wired by path hacks.** There are 129 `sys.path.insert` or `spec_from_file_location` imports, and 51 of them reach into `cad-record/scripts`. `freecad_runtime.find_freecadcmd` loads `cad-flow/scripts/preflight.py` by file path.
- **The process lives in prose.** `cad-flow/SKILL.md` has about 20 MUST/NOT rules, and `flow.md` "Gate control" defines PROVISIONAL, APPROVED and VOID. The agent writes `hw/decisions/DR-###.md` and `product.yaml flow.stage` itself, and `validate.py` and `release.py` only catch mistakes afterwards. Open beads `c7q.2`, `c7q.3` and `c7q.4` ask for the missing stage and decision CLIs and for one machine-readable result envelope.
- **Each server runs its own lifecycle.** `cad-concept/serve.py`, `cad-viewer/cadviewer/host.py` and `cad-render` (Playwright) each have their own session files, process groups, idle timeouts and ports.
- **Harness workarounds are documented one by one.** The README covers the Codex sandbox blocking loopback, Chromium and Qt, the Kiro headless `/cad-flow` parsing, and Claude `--max-turns`.

Intended outcome:
- Adding one MCP entry per harness is the whole install.
- The `benchhand` MCP server owns the deterministic code, the process, the integrations and the preview hosting.
- The guidance comes from the server, so steering files stay minimal.
- The core is middleware over pluggable providers.

## Approach

### 1. Layered architecture

```
 Harness (Claude Code / Claude Desktop / Codex CLI+app / OpenCode / Kiro / Pi / any MCP client)
   │  bootstrap skill + server instructions: "call flow.guide"
   ▼  stdio (default) | streamable HTTP on loopback (--http)
 benchhand MCP server  ── one process per harness session, started from the MCP config
   ├── MCP surface: tools · resources · prompts · skills-over-MCP · Apps · tasks/jobs (no elicitation in v1, ADR-0018)
   ├── interaction layer: picks App / chat / image / URL per client capability
   ├── preview host (loopback HTTP): viewer, concept, gate page, flow view, prototype pages
   └── core
        ├── flow engine: flow.yaml graph + state machine, CEL guards, decision records, policy
        ├── guide service: per-stage/role instructions served by flow.guide (from today's SKILL.md prose)
        ├── record service: schemas, typed record ops, validate, migrate, evidence, release
        ├── job service: long jobs, process groups, progress, cancellation (today process_lifecycle)
        ├── middleware chain: validation → policy → audit → provenance → cache → telemetry
        └── provider host: JSON-RPC 2.0 plugin protocol (slopvac-3 style), lifecycle, timeouts
   ▼  JSON-RPC over stdio, one subprocess per provider, each in its own uv env
 Providers: kernel-cadquery · kernel-build123d · freecad · solver-calculix · collision-fcl ·
            render-chromium · viewer-ocp · checks-process · store-fs · policy-default
```

### 2. Repository and package layout (temporary repo `benchhand/benchhand-next`)

Two levels (`packages/` and `providers/`) are enough. Deeper nesting would only add indirection: each package is already a single concern, and the provider protocol is the boundary that matters.

```
benchhand/
  packages/                      uv workspace members (Python)
    benchhand/                   CLI + MCP server + preview host; the `uvx benchhand` distribution
    benchhand-contracts/         generated pydantic models + validators from contracts/ (never hand-edited)
    benchhand-core/              flow engine, guide, record, jobs, middleware, provider host (no CAD deps)
    benchhand-provider/          provider runtime: framing, lifecycle, hooks, conformance kit
    benchhand-sdk/               part SDK imported by model.py (safe booleans, holes, fillets, fonts…)
  providers/                     each its own pyproject + pinned env; built-ins ship in the wheel extras
    kernel-cadquery/  kernel-build123d/  freecad/  solver-calculix/  collision-fcl/
    render-chromium/  viewer-ocp/  checks-process/  store-fs/  policy-default/
  ui/                            pnpm workspace (TypeScript, React); built to static assets in packages/benchhand
    viewer/  concept/  gate-card/  flow-view/  shared/
  contracts/                     TypeSpec sources, emitted to the published JSON Schema 2020-12: provider protocol, MCP tools, envelope, record, flow, policy (D17)
  flow/                          flow.yaml, guides/<stage>.md, CEL rule lists (*.celpolicy) and their rules bundle, policies
  harness/                       install templates: MCP registration, bootstrap skill, agent profiles
  container/                     OCI image (FreeCAD AppImage extracted, kernels, Chromium)
  tools/probe/                   dev-only capability probe (D16), not packaged
  tools/celcheck/                the pinned cel-go rule compiler (Go), shipped as the benchhand-celcheck platform wheel (ADR-0020)
  docs/  adr/  contract/  client-support.md
  examples/lamp-arm/             golden end-to-end fixture
```

History: `git filter-repo` brings over the test suites, examples, schemas and harness templates with their history, as reference material and fixtures. Production code is written fresh (section 4). The current `benchhand/benchhand` repo keeps receiving only fixes until the swap.

**Repo swap** (once parity is reached):
1. Rename `benchhand/benchhand` to `benchhand/benchhand-legacy` and archive it. GitHub redirects the old URL until the name is reused.
2. Rename `benchhand/benchhand-next` to `benchhand/benchhand`. This takes over the name, so the redirect from step 1 stops. Clones of the legacy repo must update their remote, which the archive README explains.
3. Move the open beads, the issues that should survive, and the release tags to keep.
4. Update the Claude plugin marketplace (`/plugin marketplace add benchhand/benchhand`), the PyPI project URLs, the GHCR image path and the docs links.

Until the swap, everything that carries the repo name reads it from one place, `release.toml` (ADR-0015), in CI and in the templates: the plugin marketplace, the image tags and the docs links. The swap is then a single change.

### 3. Transport: stdio vs localhost HTTP (D10)

| | stdio (default) | Streamable HTTP on 127.0.0.1 (`--http`) |
|---|---|---|
| Lifecycle | The harness starts and stops it, and kills the process group when the session ends (Pi documents this). No orphaned servers. | Someone has to start and stop a daemon. |
| Host support | All 7 first-class hosts. Claude Desktop local servers and MCPB bundles are stdio only. | Most hosts. Claude.ai web connectors can't reach localhost anyway. |
| Auth and safety | None needed. | Needs a bearer token and DNS-rebinding and Host checks. |
| Sessions | One server per session, with no shared state to coordinate. | One server shared by sessions, which survives a harness restart. |
| Container | `docker run -i` works as a stdio server. | Port mapping is needed. |

stdio carries only MCP. The preview host is a separate loopback HTTP listener inside the same process, with ephemeral ports, Host-header checks and a random path token, all reused from `serve.py`. Its URLs appear in tool results. `--http` is for users who want one shared server or a remote container.

### 4. Language choice (D12)

This compares the options greenfield, ignoring what exists today. One fixed point: CadQuery, build123d, OCP and the FreeCAD API are Python-only, so the kernel and FreeCAD providers are Python processes whatever the host is. The question is the host and core language: MCP server, flow engine, record service, job service, preview host and provider host.

| Criterion | Python | TypeScript | Rust |
|---|---|---|---|
| Runtimes on the user's machine | One. uv and Python are needed for the providers anyway. | Two: Node and uv/Python. | Binary plus uv/Python. |
| Provider SDK and conformance kit | Same language as most providers: one implementation of the contract, one test harness. | Second implementation needed in Python for the providers. | Same. |
| Domain maths in the host (fits, stack-ups, BOM roll-up, evidence digests) | numpy and the scientific stack. | Weaker. | Good, but slower to write. |
| MCP SDK | v2: 2026-07-28 and older; FastMCP has Apps helpers. No tasks extension yet. | The reference SDK; `ext-apps` and tasks are likely first. | `rmcp` trails. |
| Browser UI | — | Native. | — |
| CEL | `cel-expr-python` (Google, young) checks at load and evaluates; a pinned cel-go tool compiles rule lists, in CI and in `benchhand rules compile` only (ADR-0020) | `@bufbuild/cel` evaluates checked rules; its checker isn't public | `cel-core` |
| Contract codegen (D17) | `datamodel-code-generator` → pydantic v2 | `json-schema-to-typescript` | `typify` |
| Performance needs | The host is I/O and orchestration bound; heavy work is in providers. | Same. | Its strength isn't needed here. |
| Contributors | CAD and engineering people mostly write Python. | Web. | Systems. |

**Choice: Python host and core; TypeScript for the UIs; no Rust.** TypeScript is the runner-up. It would win if the product became mainly the inline App UI and MCP-feature work, and it could take over the host later because the provider protocol and contracts are language-neutral. The trade-off accepted: Python lacks the tasks extension for now, and job handles cover that gap (section 11).

**Rewrite, don't port.** The existing code is a behavioural reference and test oracle, not a source tree to move. Each module is redesigned around the new boundaries: core, contracts, providers and MCP. Code is kept only where it is already clean and fits those boundaries. Likely examples are the ISO 286 data and fit maths, the process-identity logic in `process_lifecycle`, the safe-boolean volume checks, and the Host-header guard. Everything else, including the 20k-line record and validation layer, is rewritten against the generated contracts. Test cases from `cad-agent` are ported as acceptance fixtures to keep the behaviour.

### 5. Flow engine and rules (D14)

The process is data, so it can be read, validated, rendered and extended without code changes. It uses **one rules language, CEL**.

**Why the graph isn't CEL.** CEL is an expression language. It evaluates a condition against inputs and returns a value; it has no notion of nodes, edges, state or history. A stage graph is structure: which stages exist, which gates sit between them, and what reopens on VOID. So the structure is data, and every *decision* inside it is CEL. That is the standard split: Kubernetes ValidatingAdmissionPolicy and Google IAM Conditions are configuration objects with CEL inside them.

**Why not CEL and ZEN together.** They overlap. ZEN's decision tables are rows of conditions with outputs, and an ordered list of CEL rules expresses the same thing with one evaluator, one syntax and one schema. ZEN's real extra is its table editor UI, which we don't need. ZEN is dropped.

- **`flow.yaml`** (schema-validated, D17) defines:
  - the stages (enum from the record contract) and the guide fragment for each stage and role (section 9);
  - the gates. Each gate has a `kind` (`single-human` or `provisional+full+human`) and CEL `requires` expressions. For example, PROVISIONAL requires `version.fast_checks.all(c, c.status == "pass")`. APPROVED requires `full_check.status == "pass" && prev_human_gate.approved && (policy.mode == "auto" || answer.present)`.
  - the edges, with CEL guards, and a CEL `void_scope` that selects the later stages a VOID reopens.
- **Design changes after an approval** (ADR-0019). Each human-gate approval records the items it approved, with their fingerprints. A later change to one of those items marks only that item `changed_since_approval`. The stage stays where it is, and the next human gate confirms the item with a diff. A CEL rule in `flow.yaml` selects the affected items. New items go through the current stage's checks. VOID at the stage's own gate, and the engineering change after freeze, are unchanged.
- **Rule lists** replace the tables. Each is a cel-policy file (`flow/*.celpolicy`) in the restricted profile of ADR-0020: one `match` block of choices, evaluated first-match, with no `variables`, `aggregate` or nested rule. Every choice has an `output`, every choice but the last has a `condition`, and the last is unconditional. The compiled list's result type must match the slot type its kind declares. Rule lists are compiled before load, not checked at load (see **CEL pipeline**):
  - **checks by iteration:** the condition `stage in ["parts","detail"] && iteration == "commit"` gives the output `["form_check", "check_changed_only"]`;
  - **process-check dispatch:** process × operation × material → handlers. The final choice outputs `"unknown"`, a value the rule-list schema reserves, and the host records it as UNKNOWN coverage, never PASS;
  - **fidelity per stage**;
  - **rigor policy:** extra requirements under `regulated`.

  Every list except dispatch ends with an explicit default of the same type as its other outputs.
- **Interpreter.** A small state machine in `benchhand-core`, about 300 lines plus tests. It loads `flow.yaml` and checks every standalone CEL expression in it once at start: gate `requires`, edge guards and `when`, `void_scope` and the approval-scope selector. A typo fails at load and not mid-flow, with every issue reported by its path in the file, line and column. It loads the compiled rule lists from the rules bundle, then runs transitions. CEL activation variables are typed from the contracts (D17) through a generated descriptor set. A scope is typed only when it is structural, so the checker catches wrong field names, wrong operand types and reads of omitted fields. Every record is validated against its JSON Schema before activation. The interpreter is the normal writer of `flow.stage` and `hw/decisions/`.
- **Policy providers** (D6) contribute extra rule lists or gate requirements in CEL. No code is needed for most policies. A provider's rule lists, like a project's, are compiled with `benchhand rules compile`. A gate's contributed requirements hold as well as the flow's. How contributed rule lists combine with the flow's own is **open for the owner** (ADR-0020, "Open items"). Each list ends with an unconditional choice, so an evaluation order alone would let the first list's default mask the rest. The Phase 1 contracts branch proposes, pending the owner: per kind, the contributions in ascending provider name, then the flow's list; the first list whose output isn't the kind's reserved no-match value wins; for rigor every list must give true. Contributed lists end in the no-match value, so a contribution that doesn't match passes to the next list.
- **CEL pipeline** (ADR-0020):
  - **Engines.** The host checks standalone expressions and evaluates every rule with `cel-expr-python`, Google's C++-backed binding (0.1.x), behind one adapter (`load`, `check`, `program`, `eval`, `identity`). A pinned `cel-go` tool (`tools/celcheck/`) is the reference checker: it compiles rule lists in CI and under `benchhand rules compile`, and it is the conformance oracle. No other CEL engine runs in benchhand. The browser shows results the server computed.
  - **Environment.** For each rule scope, `contracts_gen` generates a FileDescriptorSet and an environment profile manifest from the published schemas. The manifest holds the descriptor set's SHA-256, the declarations, the extension versions, the checker options and the checkers of record. The profile digest is the SHA-256 of the manifest's canonical bytes under RFC 8785 (JCS), which is normative; a cross-adapter test vector checks that both engines produce the same bytes. Both engines refuse descriptor-set bytes whose SHA-256 differs from the manifest's, then build their environment from the manifest and refuse an extension version or option they don't implement.
  - **Compiled rule lists.** The cel-go tool compiles each rule list into one CheckedExpr in the rules bundle. The bundle is bound by the profile digest, the checker of record and each payload's SHA-256, and each entry also records its source's SHA-256. benchhand's own lists are compiled in CI. A project's and a policy provider's are compiled with `benchhand rules compile`, which runs the same tool from the `benchhand-celcheck` platform wheel. The host verifies the digests and refuses a missing or stale entry, naming the command to run.
  - **Conformance.** In CI, each engine passes the supported-profile cases of its role. The cel-go tool passes the typed accept, reject, profile and presence cases, the cel-policy refusal fixtures and the tampered-bundle cases. cel-expr-python passes the same typed cases, refuses the tampered bundles and evaluates every CheckedExpr the tool shipped. CI fails when the two disagree on a shipped standalone expression. cel-spec's simple tests run on both against a committed failure baseline; the suite starts as the research's subset, 1,640 of cel-spec's 2,344 simple tests, and its scores are diagnostic data about that subset.
- **Kubernetes controls** (`research/cel-k8s/REPORT.md`, numbered as in its adopt table):
  - Adopted: structural scopes (1), flat unions in the contract (2), all issues with paths at load (4), an output type per slot (5), never passing a broken rule (6), environment profiles (9), pinned behaviour (11), the extension inventory (12), library discipline (13), absent versus null with a `has()` lint (24), table-driven rule tests (25) and the environment as data (26).
  - Adopted as an estimate only: cel-go's static cost estimate in CI (8).
  - Deferred: collection bounds, the nesting lint and a runtime limit (7), cost budgets (8), provider profile negotiation (9), and `introduced < removed` tests until a second profile exists (12). Also deferred: `message_expr` (14), finding `code` and `path` (15), transition rules (16), ratcheting (17), typed policy-provider params (19), `variables` (20) and a `rules test` command (25).
  - Not adopted: a `dyn` escape hatch (3), diff-against-stored environments (10), `optionalOldSelf` (18), informational type checks (21), `matchConditions` and `auditAnnotations` (22), and property-name escaping (23), which the generator replaces by refusing reserved words.
- **React Flow** (`@xyflow/react`) draws `flow.yaml` and the project's live state in the preview host's flow view and in the gate card: the current stage, open gates, provisional and void history, and the evidence for each gate.
- **Not used:** GoRules ZEN (duplicates CEL), `json-rules-engine` (JS only), React Query Builder (only for a future policy-authoring UI; it can export CEL, so adding it later needs no format change).

Scope: guidance, not security (D3). The engine refuses out-of-order transitions with a reason and the next action, and records who approved what and through which channel. It doesn't sign decisions or stop direct edits to `hw/`; `validate` reports those as findings.

### 6. Provider protocol (D13)

This is modelled on the slopvac 3.0 plugin protocol (`slopvac/docs/contract/plugin-protocol.md`, the `slopvac-plugin` Python runtime and its conformance kit).

- **Transport.** JSON-RPC 2.0 over the provider's stdin and stdout, with LSP `Content-Length` framing, size and depth limits, and logs on stderr kept in a ring buffer.
- **Lifecycle.** `initialize` with version-range and capability negotiation (provider kinds, hooks, required and optional features), then `initialized`, then work, then `shutdown` and `exit`. The host kills the whole process group, and no provider outlives the server.
- **Pre-spawn manifest.** A `benchhand-provider.toml` per provider declares:
  - its kind and hooks;
  - its environment spec: `requires-python` and pinned dependencies, or "use FreeCAD's Python";
  - its external needs (FreeCAD, Chromium, network).

  `doctor` reads the manifests without starting anything.
- **The host owns the timeouts.** Per-hook deadlines, plus `$/cancelRequest` with a grace period before the kill.
- **Additions beyond slopvac v1:**
  - Provider-to-host `$/progress` and `$/log` notifications for long jobs, which feed MCP progress, tasks and job handles.
  - Results carry artifact paths, not bytes.
  - Long-lived providers (viewer, renderer) stay resident for the session, with warm imports. That replaces today's warm-up step.
- **Dropped from slopvac:** the content-hash trust ceremony, because this isn't a security boundary (D3). Built-in providers ship with the package. Third-party providers are listed in `benchhand.toml` or come from entry points.
- **Environments.** The host builds each provider's uv environment from its manifest, keyed by dependency set (the idea behind `cadmodel/scriptenv.py`, redesigned). CadQuery (OCP 7.9) and build123d (OCP 8.0) never share a process. The kernel `build` hook is defined fresh in `contracts/`, with `cadmodel/runner.py`'s request and result as the behavioural reference.
- **Hook families:**

  | Kind | Hooks |
  |---|---|
  | `kernel` | `build`, `export`, `inspect` |
  | `cad-app` | `drawing`, `assembly`, `fem` |
  | `solver` | `solve` |
  | `collision` | `check`, `sweep` |
  | `renderer` | `render`, `snapshot` |
  | `viewer` | `show`, `compare`, `capture` |
  | `process-check` | `check` |
  | `store` | `put`, `get`, `list` |
  | `policy` | `evaluate` |

  A missing provider or hook returns UNKNOWN coverage, never PASS.

### 6a. Contracts: generated and enforced (D17)

Every boundary has one machine-readable contract, and no hand-written copy of it exists anywhere.

- **Source of truth:** TypeSpec under `contracts/` (ADR-0017). `tsp compile` emits a JSON Schema 2020-12 bundle, and a tested normaliser splits it into one published schema per contract. The published schemas are committed; they are language-neutral, which suits a protocol that providers in any language implement, and every generator and validator reads them. They are versioned with `$id` and a semver per contract. The contracts cover:
  - the provider protocol: the `initialize` exchange, every hook's params and result, and errors;
  - each MCP tool's input and output (`outputSchema` and `structuredContent`);
  - the result envelope (`status`, `findings`, `artifacts`, `next_actions`);
  - the record documents (product, part, assembly, interfaces, requirements, BOM and verification rows, decisions, evidence, manifests);
  - `flow.yaml`, the rule lists, `hw/policy.yaml`, `benchhand.toml` and `benchhand-provider.toml`;
  - the CEL environment profile manifest and the rules bundle (ADR-0020);
  - the preview-host HTTP API and the App `postMessage` payloads.
- **Generated, never edited** (one `just contracts` / `benchhand-dev gen` task):
  - pydantic v2 models and validators in `packages/benchhand-contracts` (`datamodel-code-generator`);
  - TypeScript types and runtime validators in `ui/shared/contracts` (`json-schema-to-typescript` + Ajv standalone);
  - MCP tool `inputSchema` and `outputSchema`, registered from the same files;
  - the FileDescriptorSet and the environment profile manifest of each CEL rule scope, and its cel-go env YAML (ADR-0020);
  - reference docs (`docs/contract/*.md`) and the accepted-values resources the agent reads (closes `ci7.2`).
- **Enforced:**
  - **CI drift check:** regenerate and fail on any diff, as `harness/generate.py --check` does today. A breaking schema change needs a major version bump, checked by a schema diff tool against the last release.
  - **Runtime, both directions:**
    - the provider host validates every JSON-RPC message it sends and receives;
    - the MCP server validates tool inputs and its own outputs;
    - record writes are validated before touching disk;
    - the preview host validates its HTTP and App messages.

    A violation is a typed error with the schema path, never a silent coercion. Validation runs in development and production; only the hot geometry payloads skip deep validation, with size limits instead.
  - **Conformance kits** for host and provider, as in slopvac. They are generated from the contracts: one valid and one invalid example per message, round-tripped by every built-in provider in CI.
  - **Examples are tested:** every `examples` block in a schema must validate, and the shipped example records (`ci7.1`) validate in CI.

### 7. CLI (D1)

`benchhand` (Typer) subcommands:
- `mcp [--http] [--project DIR]` starts the MCP server. This is what the MCP configs run.
- `serve [--project DIR] [--open]` runs the preview host alone (viewer, flow view, gallery) for browsing a project without an agent.
- `install --harness X [--user|--project DIR] [--container]` writes the MCP registration, the bootstrap skill, the agent profiles and the harness-specific settings (section 10).
- `doctor [--warm] [--json]` replaces preflight. `setup [--yes]` replaces setup and includes the FreeCAD managed install.
- `policy get|set` changes the gate modes and records the DR.
- `rules compile [--project DIR]` compiles a project's or a policy provider's rule lists into their rules bundle with the pinned cel-go tool (ADR-0020).
- `debug call <tool> [json]` calls a tool through the same code path, for development.

Extensibility: a provider manifest may declare `[cli]` subcommands, which are mounted as `benchhand <provider> <cmd>` and run through the provider protocol. An example is `benchhand freecad probe`. Python entry point `benchhand.cli` is the in-process alternative for core packages.

### 8. Prerequisites, FreeCAD and the container

- `doctor` runs the same checks as today's `preflight.py`: uv, the provider environments, Chromium, the three.js vendor cache and FreeCAD. It adds the provider manifests, the MCP registration of each installed harness, and the startup-timeout settings. Each failed check comes with an explicit fix, and `--json` gives machine output. The `env.doctor` tool returns the same report to the agent.
- `FreeCADProvider` owns:
  - the lookup (`FREECADCMD`, PATH, the macOS bundle, AppImage, the managed directory);
  - the managed install (D5), from the supported list in `freecad-versions.toml`;
  - version gating: a FreeCAD that isn't on the supported list is refused with a fix that names the supported versions and offers the managed install;
  - the `freecadcmd` job runner, redesigned from `freecad_runtime.py`.

  **Qualifying a new FreeCAD version** is a release-engineering task, not something users run. CI runs the compatibility suite against it: imports (Part, TechDraw, Assembly, FEM), templates, and golden TechDraw export, assembly solve and FEM cases compared with the current baselines. If it passes, we add an entry (URLs, sha256, `supported`) and ship a release. A version that has been superseded moves to `deprecated` (a warning) and then `removed`. The list starts with 1.1.4 only.
- **First start.** `uvx` fetches the package, then warms the provider environments in the background, with progress visible in `env.doctor`.
  - Codex's default MCP `startup_timeout_sec` is 10 s, so `install` sets 120 s for Codex and checks the OpenCode 30 s `startup` timeout.
  - The server answers `initialize` before warm-up finishes.
- **How the harness starts the container.** A harness starts an MCP server by spawning a command and speaking MCP over its stdin and stdout. It doesn't care what the command is. `docker run -i` is such a command: with `-i`, Docker attaches the container's stdin and stdout to its own, so the container's `benchhand mcp` becomes the server. This is how Docker's own MCP catalog servers are run. Writing a raw `docker run` line into each harness config has problems, though:
  - most configs can't expand the project directory (`${PWD}` support varies by host);
  - the port and user mapping differ per OS;
  - Docker Desktop must already be running.

  So the config entry stays the same command as without the container, `uvx benchhand@<ver> mcp --container`. That small launcher:
  1. resolves the project directory from the working directory, from MCP `roots` when the client sends them, or from `--project`;
  2. picks the container runtime (see "Container runtime" below) and checks that it is reachable, or else serves a one-tool error server whose `env.doctor` explains the fix, so the harness doesn't just show "server failed";
  3. pulls the pinned image (`ghcr.io/<repo>:<ver>`, with `repo` from `release.toml`) if it is missing, reporting progress on stderr;
  4. picks a free loopback port for the preview host;
  5. starts `<runtime> run -i --rm --init --name benchhand-<session> --label benchhand.launcher=<pid> -v <project>:<project> -w <project> --user <uid>:<gid> -p 127.0.0.1:<port>:<port> -e BENCHHAND_PREVIEW_PORT=<port> <image> mcp` as a child, pumps stdio both ways, and **supervises it** instead of `exec`-ing (see "Container termination").

- **Container runtime (configurable).** Not everyone has Docker. The runtime is chosen in this order: `--runtime`, `BENCHHAND_CONTAINER_RUNTIME`, `[container] runtime` in `benchhand.toml`, then auto-detection of `podman`, `docker` and `nerdctl` on PATH. Each value is a binary name or path plus a *profile* that knows the flag differences:

  | Profile | Covers | Differences |
  |---|---|---|
  | `docker` | Docker Desktop, Docker Engine, Colima (docker context), OrbStack, Rancher Desktop (moby) | none (reference) |
  | `podman` | Podman, Podman Desktop, podman machine | `--userns=keep-id` instead of `--user` when rootless |
  | `nerdctl` | containerd, Colima `--runtime containerd` (`colima nerdctl --`), Rancher Desktop (containerd), Lima | no `--init` on older versions, so the image uses `tini` as its entrypoint |

  A custom binary can name its profile, for example `runtime = "colima nerdctl --"` with `profile = "nerdctl"`. `doctor` reports the runtime it picked, why, its version, and whether the daemon or VM is running (for Colima and podman machine, the fix names `colima start` or `podman machine start`).
- **Container termination.** The launcher must leave nothing behind, whether the harness ends cleanly or not:
  - **Clean end.** The harness closes stdin. The launcher closes the container's stdin, `benchhand mcp` sees end of input and exits, tini (PID 1, via `--init` or the entrypoint) reaps any children, and `--rm` removes the container.
  - **Signals.** The launcher traps SIGTERM, SIGINT and SIGHUP. It runs `<runtime> stop --time 10 benchhand-<session>`, waits, then runs `<runtime> rm -f`. The client process's own signal proxy isn't relied on, because it behaves differently across runtimes and is lost when the client is SIGKILLed.
  - **Hard kill of the launcher.** Every container carries the `benchhand.launcher` pid and start identity as labels. On each start, the launcher lists `label=benchhand.launcher` containers and removes any whose launcher process no longer exists, using the same pid-reuse-safe identity check as the job service. `benchhand doctor --clean` does the same by hand.
  - **Inside the container.** The server also exits on stdin EOF and on SIGTERM. It stops its provider process groups first, so FreeCAD and Chromium inside never outlive it.
  - Tests cover each runtime profile available on the CI runner: stdin close, SIGTERM, SIGKILL of the launcher followed by the next start, and checks that no container is left and no `--rm` leftovers remain.

  Mounting the project at the same absolute path means every path in a result is a real host path.
- **Why nothing is rejected.** The harness runs MCP servers outside the agent's sandbox (Codex does this by design), and the agent never types `docker`. So shell sandboxes, approval prompts, and loopback, Chromium or Qt restrictions don't apply. Inside, FreeCAD runs with `QT_QPA_PLATFORM=offscreen` and Chromium is headless.
- **Host notes:**
  - On macOS, Docker Desktop, Colima, OrbStack, Rancher Desktop or podman machine has to be running.
  - Claude Desktop starts servers with no project directory, so the project comes from `user_config` in the `.mcpb` or from a `project.open` tool call.
  - `doctor` checks that the runtime is present, the image digest matches the pinned version, and a project file can be written and read through the mount.
- The server reads Codex's `codex/sandbox-state` capability, if present, to steer the agent, for example by reporting that the project is read-only.

### 9. Guidance from the server; minimal steering (D11)

The agent doesn't need a skill that lists which tool to call when. One tool carries the process.

- **`flow.guide(role?, unit?)`** returns:
  - the current stage and its goal;
  - the steps for this stage and role, rendered from `flow/guides/<stage>.md`, which is today's SKILL.md and `flow.md` prose cut per stage;
  - the tools relevant now, with short why/when notes;
  - open gates and what each one needs;
  - the next action.

  Every other tool's result envelope also carries `next_actions`, so the agent rarely needs to call the guide again.
- Tool descriptions say what a tool does and its preconditions. The guide says when to use it. That keeps descriptions short, which matters because hosts defer or limit tool lists (Claude Code tool search, OpenCode code mode, Codex's 512-character instructions).
- **Bootstrap.** The server `instructions` (first 512 characters self-contained) and a single bootstrap skill `benchhand/SKILL.md` of about 20 lines both say: "This project uses benchhand. Call `flow.guide` before starting and whenever unsure; follow its next action; ask the user at gates as instructed."
- The **agent profiles** (concept designer, part designer, analyst, reviewers, clerk) stay, because subagent delegation needs harness-native profiles. Their bodies shrink to the role and "call `flow.guide(role=…, unit=…)`". They are generated from the neutral `agents/*.md` by the existing `harness/generate.py`, which keeps the tier and model rendering and the `CHEAP_ELIGIBLE` allowlist.
- The same guide content is also served as MCP prompts (`/benchhand:stage`), as `guide://stage/<stage>` resources, and through Skills-over-MCP where a host supports it. That gives one source, published several ways.

### 10. Harness integration and distribution

`benchhand install --harness X` writes, for each host:

| Host | MCP registration | Bootstrap skill | Agent profiles | Extras |
|---|---|---|---|---|
| Claude Code | plugin `.mcp.json` (or project `.mcp.json`) | plugin skill | plugin agents | the `/plugin marketplace` route stays |
| Claude Desktop | `.mcpb` bundle (`user_config`: FreeCAD path, container on/off), built in CI | — | — | the bundle runs `uvx benchhand mcp` |
| Codex CLI and app | plugin manifest or `config.toml` `[mcp_servers.benchhand]` with `startup_timeout_sec` and `tool_timeout_sec` | plugin skill | `.codex/agents/*.toml` | `approval_policy.granular.mcp_elicitations = true` hint |
| OpenCode | `opencode.json` `mcp.servers.benchhand` (`type: local`) | `.opencode/skills` | `.opencode/agents` | timeouts |
| Kiro CLI | `mcp.json` and the agent profile `mcpServers` | `.kiro/skills` | `.kiro/agents` | — |
| Pi | Pi package (npm/git) with an extension calling `pi.registerMcpServer`, or `.pi/mcp.json` | package skill | — | the extension adds a gate dialog and opens preview URLs |

### 11. Adaptive interaction layer (D8)

The `interaction` component reads the client capabilities: on 2026-07-28 from each request, otherwise from `initialize`. It has overrides for clients known to advertise wrongly. Each interaction has an ordered chain, and the last entry always works.

| Interaction | 1st | 2nd | Last resort |
|---|---|---|---|
| **Human gate** | MCP App gate card (packet, renders, flow view, Approve or Request changes) | none (form elicitation dropped in v1, ADR-0018) | The agent presents the packet and the gate-page URL in chat, asks, and passes your reply to `flow.record_decision` (`channel: chat`, your words quoted) |
| **Preview for you** | Preview-host page at a loopback URL, in every host. Where Apps render, the App (`ui://benchhand/viewer`) is a thin shell that embeds the same page (CSP `frameDomains` set to the preview origin). | URL in the tool result | Absolute paths |
| **Preview for the agent** | PNG snapshots as image content | `resource_link` to the snapshot files | Absolute paths |
| **Structured questions** (GROUND, INTENT, SPECIFY) | MCP App form (nested schemas) | none (form elicitation dropped in v1, ADR-0018) | Asked in chat, recorded through `record.*` |
| **Long jobs** | Tasks extension (`tasks/get`, `tasks/update`, `tasks/cancel`) | Progress notifications on a bounded call | `jobs.start`, `jobs.status`, `jobs.result` |
| **Media out** | Image content + `resource_link` | Preview-host URL | Path |

URL-mode elicitation is not used, and since ADR-0018 neither is form mode: the baseline is a client with plain tool calls, and every workflow must complete on it. Preview URLs go in tool results.

Rules:
- An empty or declined answer means no answer, and the gate stays open. Codex auto-review has been seen answering with empty content (openai/codex#23383).
- Images are downscaled to stay under client limits: Claude Code `MAX_MCP_OUTPUT_TOKENS` defaults to 25k, and Codex has `output_token_limit`.
- A tool that can run longer than about 30 s returns a task or a job handle (ADR-0018). Codex `tool_timeout_sec` defaults to 60 s, and Pi's timeout is 60 s, reset by progress.
- Everything is local. Claude.ai web connectors can't reach localhost.

The server is built on the MCP Python SDK v2 (2026-07-28 plus every earlier revision). The SDK has no tasks extension yet (python-sdk#2806), so job handles are the main path and the tasks adapter sits behind a flag. Apps are built with FastMCP `apps` helpers or raw `ui://` resources with `_meta.ui`.

### 12. Build API (D7)

The agent writes `model.py` (CadQuery or build123d) for real geometry. Routine work is done by tools:

- **Output.** Each takes a version reference and returns artifacts. Nothing is scripted by the agent:
  - `model.build`: STEP AP242, GLB and the manifest;
  - `model.export`: STL and 3MF;
  - `render.*`, `drawing.*`, `bom.*` and `motion.render`.
- **Part SDK** (`benchhand-sdk`): `safe_cut`, `safe_fuse`, holes, fillets, components and fonts with stable imports. `sdk://describe` lists the signatures.
- **Generators:**
  - ISO and ASME holes and counterbores;
  - purchased fasteners and bearings (`bd_warehouse`);
  - bosses, ribs and sheet flanges.

  They emit reviewable `model.py` fragments.
- **Inspect:** `model.measure`, `section`, `mass_props` and `interference`.
- **Draft preview:** `preview.part` and `preview.assembly` build without making a version, return snapshots, and update the live viewer.
- **Concept scene tools:** `concept.add_variant`, `concept.set_primitive` and `concept.snapshot`.
- **Viewer and gallery:** `viewer.show`, `compare`, `capture` and `camera`.
- **Preview hosting:** `preview.serve(kind, target)` hosts the viewer, concept, gallery, flow view, or a prototype page or rendering the agent produced, and returns its URL. `preview.stop` and `preview.list` manage them.
- **Typed record ops:** `record.add_requirement`, `add_interface`, `add_part`, `set_route`, `add_evidence` and `add_bom_row`, validated on write. This closes `c7q.13`.
- **Calculators:** `fits.lookup`, `fits.stackup`, `fea.case_from_requirement` and `motion.pose`.
- **Layout skeleton:** `layout.from_concept` writes each inferred value as a bounded assumption, which must be accepted or edited at LAYOUT freeze. The draft can never be frozen as it is.

### 12a. Documentation set: annotations, groups, materials and finish

STEP AP242 stays the primary deliverable for every released version. Everything in this section is added beside it and is built from the same version, so the STEP, the drawings, the FreeCAD document and the viewer always show the same names, groups and materials.

**One annotation set per part and assembly** (a new contract, `contracts/record/annotations`). The tools derive it from the record and the user can edit it; nothing is drawn by hand:

- **Groups:** the assembly tree (subassemblies), plus a sourcing group for every part: make, buy or existing (`make_buy`, including the `existing` value from prototype PR #333). Fasteners and purchased hardware go in buy; reference and construction geometry go in its own group.
- **Callout targets:** each part, and each recognised feature (hole, thread, slot, fit, sealing face), with a label: part number, name, material and finish.
- **Materials:** one material per body, from the record. It drives the section hatch, the render appearance, the mass, and the label.
- **Surface finish:** per part and per face where it matters (Ra, process such as anodise, powder coat, polish), from requirements and the DFM review.
- **Notes:** general and per-group notes, and weld callouts for welded joints.
- **Assembly order:** numbered steps from the assembly sequence (the motion and interference data already orders them), each step naming the parts it adds and the fasteners with their torque.

**Outputs, each with the ADR-0018 baseline:**

| Output | What it holds | Baseline | Richer version |
|---|---|---|---|
| Part drawings (TechDraw, ported) | Views, dimensions, tolerances, sections with material hatch, detail views, centre marks, title block, plus surface finish symbols, weld symbols and notes | PDF and SVG sheets, and a text list of views, dimensions and symbols | none |
| Keynoted section details | In the style of FreeCAD's `ArchDetail.FCStd` example: a section through the assembly in which every region is hatched by material and labelled with a leader (part number, material, finish, sourcing group) | PNG and SVG, plus the keynote list as text | Viewer layer |
| Assembly drawings (ported, extended) | Exploded view, balloons, parts list grouped by make, buy and existing, and one sheet per assembly step with the step's parts and fasteners | PDF and SVG, the parts list as CSV, the steps as text | Step-through in the viewer |
| Labelled views | A render with numbered callouts and a legend, for the person and for the agent's own review | PNG and the legend as text | Interactive viewer: hover or click a part, switch groups (sourcing, subassembly, material) on and off, step through the assembly order |
| FreeCAD document | A structured `.FCStd`: an Assembly with joints, one group per subassembly and per sourcing group, a Construction group, named bodies with materials assigned, sketches with construction geometry kept, and the TechDraw pages inside | The file, and its object tree as text | none |

Reference examples, shipped with FreeCAD 1.1 under `share/examples`:
- `ArchDetail.FCStd`: 40 material objects and one section, with every layer labelled by leader on one TechDraw page. This is the model for keynoted details.
- `AssemblyExample.FCStd`: a named Assembly with links, joints and a joint group.
- `EngineBlock.FCStd`: named feature groups and a Construction group.
- `BIMExample.FCStd`: 24 groups, dimensions and an annotation on a page.

The acceptance tests compare the object tree and page contents against these patterns, not the pixels.

**Customer equipment and other non-product geometry.** This comes from the test project's brief (`benchhand-test-project/.cad-work/lead/architect-prompt-reference-geometry.md`) and prototype PR #333. Two separate fields:

- **`make_buy` on the part: `make`, `buy` or `existing`.** It says who provides the part. `existing` parts need a dimension range with a basis (measured, standard, user-declared or assumed) and its sources. They may not have a supplier or an order code, and they generate no purchase, route, process, form or manufacture obligations. Those obligations are recorded as `not_applicable`, with the role as the reason, never silently skipped. Interface, clearance, sweep and access obligations stay.
- **`role` on an occurrence or subassembly: `product`, `context` or `tooling`.** It says what the exports do with it. The default comes from the part: `existing` gives `context`, anything else gives `product`. An occurrence can override it, for example a bought jig used as `tooling` in one assembly.

Each version then exports:
- `product.step` (AP242) and `product.glb`, with `product` occurrences only. This is the released deliverable.
- `scene.step` and `scene.glb`, with every occurrence. The checks, motion and sweeps read the scene, and a release can attach it as installation context.

The STEP/GLB agreement check runs on both. The release refuses a product export that contains a `context` or `tooling` part.

In the documentation set:
- the parts list leaves out `context` and `tooling`, and the BOM and build guide add a table "Customer-furnished equipment (not supplied)" with the required ranges;
- drawings draw context parts in phantom lines;
- renders and the viewer ghost them, with a toggle.

When a dimension is a range, the clearance and sweep checks run at both ends. A change to existing geometry makes the geometry, interface and clearance evidence stale, not the purchase evidence.

### 12b. Assembly steps and joint evidence

These come from the test project's L3 DETAIL run. Under the prototype's rules, 22 joint obligations could never pass.

**Placement is not a joint.** Assembly operations get a `place` kind beside `insert`, `fasten`, `press_fit`, `heat_set`, `retaining_ring` and the others:

- A `place` step installs a part: a sleeve, a ring, washers, a collar held by a pinch screw, a hanger held by a bolt, a harness held by ties. Order, access and interference are checked as for any step.
- It makes no joint of its own, so it gets no retention or edge-distance obligation.
- It must name the step that retains it (`retained_by: <step id>`). The record refuses a `place` step without one, or with a `retained_by` that names a step that isn't a joint.
- The retaining joint keeps its full evidence rules, and its evidence covers the parts it holds. A change to that joint makes the placed parts' evidence stale too.
- `existing` parts are never the `part` of a step, only its `into` (section 12a). So the customer's equipment is never placed or joined.

**Test coupons are evidence.** Some joint evidence can only come from a physical test: insert pull-out, screw torque, a bonded magnet's push-out, the push-out of a snap or a retaining ring.

- **Coupons from the requirement.** The tool proposes test coupons from the verification rows that need a physical test. It adds them to the calibration print job, so they come from the same printer, material and settings as the parts.
- **What a result records:**
  - the method and the instrument (scale, torque screwdriver);
  - the measured values and their uncertainty;
  - the test conditions (temperature, wet or dry, conditioning time);
  - the print job and material lot.
- **Conditions limit what passes.** A result passes only the conditions it was tested under. A requirement at -10 deg C wet and at +40 deg C needs the coupon conditioned to each case. A room-temperature result leaves those cases provisional, and says so in the gate packet.
- **User-measured results** use the source kind `user_measured`, with the uncertainty the instrument gives. A kitchen scale is coarse, and the margin check uses that uncertainty.

### 13. Client capability research (as of 2026-11; recheck at implementation)

| Host | Skills (native) | Prompts | Resources | Image results | Form elicitation | URL elicitation | Tasks | MCP Apps | Install route |
|---|---|---|---|---|---|---|---|---|---|
| Claude Code CLI | ✓ | ✓ slash cmds | ✓ @-mention | ✓ inline | ✓ | ✓ (≥2.1.287) | ✓ beta (≥2.1.304) | ✗ (text only) | plugin with `.mcp.json` + skills |
| Claude Desktop (chat, local stdio/MCPB) | via plugin | ✓ | ✓ | ✓ | ✗ not advertised | ✗ | ✗ | ✓ | `.mcpb` (macOS/Windows) or plugin |
| Codex CLI | ✓ | ? | ? | ? | ✓ (≥0.129) | ? | ✗ | ✗ | plugin or `config.toml` |
| Codex / ChatGPT desktop app | ✓ (plugins) | | | | ✓ form (stdio) | advertised | ✗ | ✓ (fixed in 26.616) | shares `~/.codex/config.toml` |
| OpenCode | ✓ | ✓ `<server>:<prompt>` | ✓ (tools) | ? | ✓ | ✓ (link) | ✗ | ✗ | `opencode.json`; execution timeout 12 h |
| Kiro CLI/IDE | ✓ | ✓ (user-initiated) | ✓ (`#` mention) | ? | ? | ? | ✗ | Kiro Crew ✓ | `mcp.json` / agent profile |
| Pi | ✓ (Agent Skills) | ? | ✓ (images as images) | ✓ | not documented | not documented | ✗ | ✗ (`ui://` omitted) | Pi package or `.pi/mcp.json`; 60 s timeout, reset by progress |
| VS Code Copilot / Cursor (secondary) | — | ✓ | ✓ | ✓ | ✓ | ? | ✗ | ✓ | `mcp.json`; VS Code supports Skills-over-MCP |

✓ = documented or verified · ✗ = not supported · ? = not documented; to be checked with the dev probe (D16).

The dev probe (`tools/probe/`) is a throwaway MCP server. A developer registers it by hand in each host. It records the advertised capabilities and tries each interaction, and the developer commits the results to `docs/client-support.md`. It isn't shipped and isn't run in CI.

Sources:
- Claude Code MCP docs: https://code.claude.com/docs/en/mcp
- Codex MCP docs: https://developers.openai.com/codex/mcp
- Codex elicitation: https://codex.danielvaughan.com/2026/05/08/codex-cli-mcp-elicitations-human-in-the-loop-structured-input/
- Codex MCP Apps: openai/codex#21019
- Codex MCP servers run outside the sandbox by design: openai/codex discussion
- OpenCode MCP docs: https://opencode.ai/docs/mcp-servers/
- Pi docs: `docs/mcp.md`, `docs/skills.md` and `docs/packages.md`
- MCP extension support matrix: https://modelcontextprotocol.io/extensions/client-matrix
- Elicitly elicitation support matrix: https://www.elicitly.ai/docs/elicitation/support-matrix/
- MCP 2026-07-28 changelog: https://modelcontextprotocol.io/specification/2026-07-28/changelog
- Skills-over-MCP extension: https://modelcontextprotocol.io/extensions/skills/overview
- MCPB: https://claude.com/docs/connectors/building/mcpb
- cel-expr-python: https://pypi.org/project/cel-expr-python/
- slopvac 3.0 plugin protocol: `~/personal/dev/slopvac/docs/contract/plugin-protocol.md`

## Behavioural reference map (from `benchhand/benchhand` into `benchhand/benchhand-next`)

This table says where each piece of current behaviour ends up. It is not a list of files to move: each destination is a redesign (section 4), and the source supplies the behaviour, edge cases and test cases.

| Behaviour now in `benchhand/benchhand` (local `cad-agent`) | Owned in `benchhand/benchhand-next` by |
|---|---|
| `skills/cad-record/scripts/*`, `skills/cad-record/schemas/*` | `contracts/record/` (schemas redesigned), `packages/benchhand-core/record/` |
| `skills/cad-flow/scripts/process_lifecycle.py`, `scratch.py` | `benchhand-core/jobs/`, `benchhand-core/work/` |
| `skills/cad-flow/scripts/preflight.py`, `setup.py` | `packages/benchhand/cli/doctor.py`, `setup.py` |
| `skills/cad-flow/SKILL.md`, `references/flow.md`, the other `SKILL.md` prose | `flow/flow.yaml`, `flow/guides/<stage>.md`, `flow/*.celpolicy` |
| `skills/cad-model/scripts/cadmodel/{runner,scriptenv}.py`, `run_*.py` | `benchhand-provider/`, `providers/kernel-*/` |
| `skills/cad-model/scripts/cadmodel/{safe,holes,fillets,components,fonts,…}.py` | `packages/benchhand-sdk/` |
| `skills/cad-model/scripts/cadmodel/{check,mesh,occ,diff,…}.py` | `providers/collision-fcl/`, `providers/kernel-*/inspect` |
| `skills/cad-drawings/scripts/*`, `cad-analysis/scripts/*`, `cad-motion/scripts/freecad_assembly.py` | `providers/freecad/`, `providers/solver-calculix/` |
| `skills/cad-motion/scripts/*` (other) | `providers/collision-fcl/` + `benchhand-core/motion/` |
| `skills/cad-render/*`, `skills/cad-design/scripts/review_render.py` | `providers/render-chromium/`, `ui/` |
| `skills/cad-viewer/*`, `skills/cad-concept/*` | `providers/viewer-ocp/`, `ui/viewer`, `ui/concept`, the preview host |
| `skills/cad-design/scripts/process_checks/*`, `form_check.py` | `providers/checks-process/` (dispatch → CEL rule list) |
| `skills/cad-fits`, `cad-bom`, `cad-recheck` scripts | `benchhand-core/{fits,bom,recheck}/` |
| `agents/*.md`, `harness/generate.py`, `harness/install.py` | `harness/` (templates) + `benchhand install` |
| `examples/lamp-arm/` | `examples/lamp-arm/` (golden fixture) |

## Reuse

Code is reused only where it is already clean and fits the new boundaries (section 4). Everything else is a behavioural reference.

**Candidates to keep, after review:**
- `cad-fits/data/iso286.json` and the fit and stack-up maths in `fits.py` and `stackup.py`.
- The process-identity rules in `cad-flow/scripts/process_lifecycle.py`: start identity, process groups and pid-reuse safety.
- The volume-envelope checks in `cadmodel/safe.py`, which go into `benchhand-sdk`.
- The Host-header and DNS-rebinding guard and the SRI-pinned vendor cache in `cad-concept/scripts/serve.py`.
- The tier and model rendering and `CHEAP_ELIGIBLE` in `harness/generate.py`.

**Behavioural references only (redesigned):**
- `cadmodel/runner.py`, the kernel request and result, which become the kernel `build` hook.
- `cadmodel/scriptenv.py`, environments keyed by dependency set, which become provider environments.
- `cad-flow/scripts/preflight.py`, which becomes `doctor`.
- `cad-record/scripts/*`, which becomes the record service against the generated contracts.
- `process_checks/dispatch.py`, which becomes the CEL dispatch rules.
- The viewer, concept and render hosts, which become the preview host and providers.

**External templates:**
- slopvac `docs/contract/plugin-protocol.md` and `packages/slopvac-plugin` (framing, lifecycle, conformance kit), the template for `benchhand-provider`.
- Its `schemas/v3/plugin-protocol.schema.json`, the template for contracts-as-source.

## Steps (phased)

Every phase ends at a review gate. When a phase's work is done:
1. Write a phase summary in `docs/phases/phase-N.md (phases 0 and 1 share `phase-0-1.md`)`: what was built, what was left out and why, the open items, and how it was verified.
2. Verify it by running it, not only through the test suite. Run the built services or CLI against a real project record (a copy of `benchhand-test-project`), and record the commands and their output in the summary.
3. Stop. Send the summary to the owner and wait for approval before starting the next phase. Work for the next phase may sit on an unmerged branch, but it isn't merged and the phase box isn't ticked until the owner approves.

- [ ] **Phase 0: repo and contracts.**
  - Create the temporary `benchhand/benchhand-next` repo: uv workspace, pnpm `ui/`, CI, the complexity ratchet and the slopvac prose check. Keep the repo name in one place, `release.toml` (ADR-0015).
  - Import the reference material (tests, examples, schemas) with `git filter-repo` to keep its history. Production code is written fresh.
  - Write ADRs for D1–D17.
  - Write the provider protocol contract (slopvac v1 plus progress and artifacts) as prose in `docs/contract/`, with its contract in `contracts/`.
  - Run the dev probe by hand in the 7 hosts and commit `docs/client-support.md`.
- [ ] **Phase 1: contracts and core.**
  - Write `contracts/` (record, envelope, provider protocol, flow, policy) and the codegen with its CI drift check.
  - Build `benchhand-contracts` and the record service against it: typed reads and writes, validate, migrate and evidence. Versioning (snapshot, seal, verify) moves to Phase 2 with the freeze, and release packaging to Phase 4 with the outputs it packages (owner decision, 2026-11-25).
  - The prototype is still changing. Migrate and evidence port its behaviour as of `release.toml` `reference_commit`, and stay extendable. Every prototype change that merges later is ported by its own reviewed step (ADR-0015, `just reference-changes`): a contract change, a new migrate rule with a fixture, and an evidence rule if it applies. The migrate rules are a table, one row per prototype change, so a new row needs no restructuring.
  - Port the record test cases from `cad-agent` as acceptance fixtures.
  - Add the job service, built on the kept process-identity rules.
- [ ] **Phase 2: flow engine.**
  - `flow.yaml` plus the interpreter, CEL guards and policy (`hw/policy.yaml`), and the cel-policy rule lists for checks-by-iteration, fidelity and dispatch.
  - The CEL pipeline (ADR-0020):
    - the scope definitions, and the `contracts_gen` targets: the structural-scope check, the FileDescriptorSet, the environment profile manifest with its JCS digest, and the env YAML, all under the drift check;
    - the JCS test vector that the cel-go tool and the host must reproduce byte for byte;
    - the profile-manifest and rules-bundle contracts in `contracts/`;
    - the pinned cel-go tool in `tools/celcheck/`, and the CI step that compiles `flow/*.celpolicy` into the rules bundle and fails on a stale entry;
    - the host's adapter over `cel-expr-python`, its bundle verification and its refusal of a missing or stale entry;
    - refusal fixtures for the cel-go tool and the host: a descriptor set whose bytes don't match the manifest's SHA-256 is refused before an environment is built;
    - the supported-profile gate in CI, per engine role.
  - Version snapshots, seal and verify, used by the freeze and `--since-version` baselines. They honour the project ignore rules (bead `benchhand-3fc`).
  - Decision records, VOID cascade, the result envelope and `next_actions`.
  - Scoped approvals (ADR-0019): the approval scope in the decision contract, `changed_since_approval`, and the gate packet's changed-since-approval section.
  - Cut `flow/guides/*.md` from the current SKILL.md and `flow.md` prose.
  - Closes `c7q.2`, `c7q.3`, `c7q.4` and `c7q.14`.
  - Record contract additions, in TypeSpec (the move happened in Phase 1, ADR-0017):
    - `make_buy: existing` and the occurrence `role` (section 12a);
    - the annotation set (section 12a);
    - the `place` step kind with `retained_by`, and test-coupon evidence with test conditions (section 12b).
    - Obligation generation marks parts nobody orders, and placed parts, `not_applicable` with a reason.
- [ ] **Phase 3: MCP server and CLI.**
  - `benchhand mcp` on stdio (`--http` optional), built on the Python SDK v2.
  - Tools: `flow.guide`, `flow.*`, `project.*`, `record.*`, `env.doctor` and `jobs.*`.
  - Resources (record, schemas, accepted values, guides) and prompts.
  - The chat fallbacks of the interaction layer.
  - The `benchhand` CLI: `mcp`, `doctor`, `setup`, `policy`, `rules compile` and `debug call`.
  - The `benchhand-celcheck` platform wheels, built in CI from `tools/celcheck/`, which `rules compile` runs (ADR-0020).
  - An install smoke test for `rules compile`: on each supported target, install `benchhand` from the built wheels into a fresh environment and compile a sample project's rule lists with the installed `benchhand-celcheck` binary, then load the bundle. The same test runs in the container image.
- [ ] **Phase 4: providers.**
  - `benchhand-provider` runtime and conformance kit.
  - Providers: kernel-cadquery and kernel-build123d, freecad (managed install and compatibility probe), solver-calculix, collision-fcl, render-chromium, checks-process (CEL dispatch) and store-fs.
  - `benchhand-sdk`.
  - The output, inspect, generator, calculator, motion, drawing, analysis, BOM and release tools. Release packaging (`hw/releases/<REV>/`, refusal checks and the acceptance digest against the freeze) is built here.
  - The documentation set (section 12a):
    - the annotation-set contract;
    - surface finish, weld symbols and notes on part drawings;
    - keynoted section details;
    - assembly drawings grouped by make, buy and existing, with one sheet per assembly step;
    - labelled views as PNG;
    - the structured `.FCStd` export (`cad-app` `document.export`);
    - STEP AP242 stays the primary deliverable.
  - Provider-declared CLI subcommands.
- [ ] **Phase 5: preview host and the richer interactions.**
  - The preview host plus `ui/`: viewer, concept, gallery, gate card and flow view (React Flow).
  - `preview.*`, `viewer.*` and `concept.*`, draft preview, and `layout.from_concept`.
  - Viewer layers from the annotation set: callouts, a legend, group toggles (sourcing, subassembly, material) and assembly-step playback.
  - MCP Apps shells, image results, and the tasks adapter behind a flag (no form elicitation, ADR-0018).
  - `benchhand serve`.
- [ ] **Phase 6: harness integration.**
  - `benchhand install` for the 7 hosts: MCP registration with timeouts, the bootstrap skill, agent profiles from `harness/generate.py`, and the Pi package with its extension.
  - Skills-over-MCP serving.
  - `install --container`.
- [ ] **Phase 7: packaging and release.**
  - PyPI `benchhand` and `benchhand-celcheck`, the OCI image (GHCR), the Claude Code plugin and marketplace, the Claude Desktop `.mcpb`, the Codex plugin and the Pi package.
  - Docs: README, walkthrough and client support.
  - Golden parity with the current repo, then the repo swap (section 2).

## Verification

- **Behavioural parity.** The test cases from every `cad-agent` per-skill suite are ported as acceptance fixtures against the new APIs, and they pass.
- **Contracts.** The codegen drift check is clean. A schema diff against the last release flags a breaking change without a major bump. The runtime validators reject a malformed message at every boundary (provider, MCP, record, preview host), and the generated conformance examples round-trip through every built-in provider.
- **Golden end-to-end.** `examples/lamp-arm` goes from GROUND to RELEASE through MCP tools only, driven by a scripted MCP client.
  - It is run once per capability profile: chat only (the release gate, ADR-0018), Apps, tasks.
  - The STEP, drawings, EBOM and verification must match the `cad-agent` baseline.
- **Flow tests.**
  - An out-of-order transition is refused with a reason and the next action.
  - An empty or declined answer leaves the gate open.
  - Approval DRs record the channel and the user's words.
  - A VOID cascades to later stages.
  - A change to an approved item reopens only that item's approval, and the next gate shows its diff (ADR-0019).
  - A PROVISIONAL without passing fast checks is refused.
  - A policy change produces a DR.
  - `flow.yaml`, the policies and the rule lists validate against their schemas. Every standalone CEL expression compiles and type-checks at load, and a rule list whose bundle entry is missing or stale is refused at load.
  - `flow.guide` covers every stage and role.
- **Provider conformance.**
  - The slopvac-style host and plugin conformance suites pass for every built-in provider.
  - A fake provider in a third environment is discovered, negotiated, timed out, cancelled and killed correctly.
  - A missing provider gives UNKNOWN.
  - CadQuery and build123d build in one run without conflict.
- **FreeCAD.**
  - The compatibility suite passes on every `supported` version in `freecad-versions.toml`, starting with 1.1.4. A newer FreeCAD release runs as an informational qualification job.
  - The managed download verifies the sha256 for each listed platform.
  - An unlisted host FreeCAD is refused with a fix.
  - `CAD_REQUIRE_FREECAD=1` still fails CI hard.
- **Install smoke**, on macOS arm64 and Linux x86_64 in CI, using each host's config format and a scripted MCP client:
  - generate the config with `benchhand install`;
  - start it cold with `uvx`, which must stay within the configured startup timeout;
  - `env.doctor` reports green;
  - one `model.build`, one `preview.serve` and one gate;
  - one `benchhand rules compile` from the installed `benchhand-celcheck` wheel, whose bundle the host then loads.

  The container launcher gets the same check: no runtime gives the error server, and with a runtime the image is pulled and the paths round-trip through the mount. A manual pass in the real hosts happens before each release.
- **Preview host.** No orphaned processes after the session is killed (`process_lifecycle` identity tests). The Host-header and DNS-rebinding tests from `serve.py` pass.

## Open questions

- None blocking. The "?" cells in the capability table are settled by the manual probe in Phase 0.
- **For the owner: composing policy providers' rule lists** (section 5, ADR-0020). The Phase 1 contracts branch's proposal waits for confirmation before Phase 2 builds the merge.
- The shipped guideline sets become a benchhand package asset when the guideline catalog is ported. Until then the evidence reader's caller names their directory (`read_built_version(shipped_guidelines=...)`). `reference/` stays a test oracle only.
