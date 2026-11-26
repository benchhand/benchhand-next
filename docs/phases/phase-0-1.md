# Phases 0 and 1: summary for review

Status: waiting for the owner's review. Written 2026-11-25 at `main` `41598c2`, with the phase gate added in this commit. Phase 2 work (the TypeSpec migration and the record additions) sits on unmerged `pi-subagents/*` branches until this is approved.

## What was built

### Phase 0: repo and contracts

- **Repo:** `benchhand/benchhand-next`, public.
  - A uv workspace with five packages: `benchhand` (CLI), `benchhand-contracts`, `benchhand-core`, `benchhand-provider` and `benchhand-sdk`. The provider and SDK packages are stubs until Phase 4.
  - A pnpm `ui/` workspace, for the generated TypeScript types.
- **CI** (`.github/workflows/ci.yml`): lint, type checks (Python and TypeScript), the tests, built-wheel tests run outside the checkout, contract drift and breaking-change checks, and the slopvac prose gate on changed Markdown.
- **CodeQL:** GitHub default setup is on, covering Actions, JavaScript/TypeScript and Python. It runs weekly and on pushes. Its last analyses, on 2026-11-25, found 0 alerts. Nothing else is needed.
- **Reference material:** the prototype's tests, examples and schemas are under `reference/`, imported with their history. It is a read-only oracle.
- **ADRs:** 0001 to 0018. ADR-0017 was revised today: TypeSpec is the contract source. ADR-0018 says plain tool calls are the baseline, and drops forms from v1.
- **Provider protocol:** prose in `docs/contract/provider-protocol.md`, with its schemas in `contracts/provider/`.
- **Host probe:** results in `docs/client-support.md`. The hosts run are:
  - Claude Code CLI (headless and interactive);
  - Codex CLI;
  - OpenCode;
  - Pi (headless and interactive);
  - Kiro CLI, where the tools weren't exposed;
  - Claude Desktop.

  The probe is not run in the Codex/ChatGPT desktop app, and Kiro's tool exposure is not resolved. Both are paused at the owner's request.

### Phase 1: contracts and core

- **Contracts:** 21 JSON Schema 2020-12 files under `contracts/`, covering record (17), jobs, provider (2) and common. Generated from them, never edited by hand:
  - Pydantic models;
  - TypeScript types;
  - the published schemas;
  - docs (`docs/contract/generated/`);
  - examples.

  `just contracts-check` fails on drift, and on a breaking change without a major version bump. The TypeSpec migration (ADR-0017) is in progress on a branch.
- **Record service** (`benchhand_core.record`):
  - typed reads of every `hw/` document, with a strict YAML loader and CSV column checks;
  - writes that check file identity and round-trip before touching a file;
  - `validate()` with the ported rules: BOM, interfaces, assembly, drawing, decisions, and the joint coupling cycle;
  - findings that meet `common/finding.schema.json`.

  The reader accepts `record_version: 3` only. It refuses anything else with `record.version_unsupported` and changes nothing.
- **Job service** (`benchhand_core.jobs`):
  - start, status, list, result, progress, cancel and reap;
  - recovery after a restart, built on the kept process-identity rules, with a supervisor that kills the process group.
- **Tests:** 270 in the main suite plus the wheel tests. `just check` is green.

## Not built, which the plan puts in Phase 1

| Item | State | Effect |
|---|---|---|
| Record migrate service (prototype v2 to v3) | Built on a branch, not yet reviewed: `benchhand_core.record.migrate`, and the CLI `benchhand record migrate [--apply [--backup]] HW`. The rule table, how apply writes in place, and the three decided defaults are in `docs/contract/record-migration.md`. The test helper `tests/record/prototype_v2.py` is gone. | On a copy of `benchhand-test-project`, everything migrates except the Phase 2 assembly kinds (`bench`, `place`, `instructions`). |
| Record evidence service | Evidence documents are read and validated. Nothing writes evidence or checks what it cites. | Needed before verification and release work. |
| Record release service (snapshot, seal, verify, package) | Not started. | Needed before any version can be frozen. It must honour the ignore rules in bead `benchhand-3fc`. |
| Port of the cad-agent record test cases | The lamp-arm reference record and the validator cases that still hold are ported. The release and evidence cases wait on those services. | |

So Phase 1 isn't complete. I propose finishing these three services before Phase 2 merges; the decision is the owner's.

## Verification by running it

I ran this against a copy of the building agent's test project, `benchhand-test-project/hw`, which has 29 parts and an L3 DETAIL record. The copies are in `/tmp/bh-verify-*`.

1. **The prototype record as written:** `read_record` and `validate` on the v2 copy gave 241 findings and 43 read errors:
   - `record.version_unsupported` ("record_version 2 is not supported");
   - schema errors for v2 key names (`hole_d`, `depth_min`), CSV columns, and decisions without `id`;
   - `decision.reference` for each part citing an unreadable decision.

   Nothing in the copy changed. This is the designed refusal, and it shows the missing migrate service.
2. **`benchhand record migrate --apply hw`, on a copy committed to a new git repository:**
   - 46 of 3,559 files would change (732 diff lines), with 18 `migrate.gate_decision` info findings.
   - One validation error is left, in `hw/assembly.yaml` at `/operations/0/kind` (`bench`), so apply refuses: it exits 1 and `git status -- hw` shows nothing changed.
   - The test project already uses things benchhand-next doesn't have yet:
     - the `bench` kind (8 operations; prototype PR #334, sub-builds);
     - the `place` kind (23 operations; plan section 12b);
     - an `instructions` key on 40 operations.
3. **The same command, with those operations and keys stripped from the copy:**
   - It wrote 46 files, `hw/product.yaml` last, and printed `to undo: git -C <copy> restore -- hw`.
   - The other 3,513 files stayed byte-identical, 2,267 of them sealed history under `hw/versions/` and `hw/checks/`.
   - `validate` then gave 0 read errors and 0 findings across all 29 parts.
   - `git restore hw` put the copy back byte for byte.
   - An apply stopped after 1, 20 or 45 files and then rerun with `--backup` gave the same bytes as a clean run.
4. **Negative check:** with `hw/parts/GHA-0001/` moved away, there is exactly one finding, `bom.unknown_part`: "BOM PN GHA-0001 has no hw/parts/GHA-0001/part.yaml and is not an assembly".
5. **OS junk:** I wrote `.DS_Store`, `Thumbs.db`, `desktop.ini` and `__pycache__` into hw/, parts/, decisions/ and manufacturing/sources/. There were 0 read errors and 0 findings. A test now pins this.
6. **Jobs:**
   - a shell job ran to `succeeded`, and `result()` returned its JSON;
   - a `sleep 30` job, when cancelled, ended as `cancelled` with exit -15;
   - `list_jobs` showed both;
   - the run directory got its own `.gitignore`.
7. **CLI:** `benchhand version` prints `0.0.0`, and `benchhand record migrate` runs as in items 2 and 3. The other subcommands arrive in Phase 3.

## Gaps the run found, to add to Phase 2's record additions

- The `bench` assembly kind, with sub-builds and hold steps: prototype PR #334 and bead `c7q.28`.
- An `instructions` field on assembly operations.
- The `place` kind, already planned (section 12b).
- The prototype has moved past `release.toml` `reference_commit` `412b5d9`. `just reference-changes` lists open PRs #319 to #336 that touch the record. They are ported when they merge (ADR-0015).

## Open items

- Codex desktop probe and Kiro tool exposure: paused.
- The building agent's answers on `place` and test coupons were relayed by the owner.
- Beads: `benchhand-fct` (drawing fixes, Phase 4) and `benchhand-3fc` (ignore rules: setup, release and validate).
