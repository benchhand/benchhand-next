<!--
SPDX-FileCopyrightText: 2026 Sjors Robroek

SPDX-License-Identifier: MPL-2.0
-->

# Edit-loop performance: design input from the agentcad product test

Status: design input with the owner's answers recorded. It was written on 2026-11-27 against `main` at `e739221a`. The owner answered Q1 to Q6 on 2026-11-27 ([Decisions](#decisions)), and the gain sections below follow those answers. This note changes no contract, ADR or code. The beads in [Beads](#beads) deliver the changes. The register entries IR-198 to IR-212, the design rule RULE-39 and the catalogue entries record them ([Register and catalogue changes](#register-and-catalogue-changes)).

This note sits in a new `docs/design/` folder. It covers Phases 2, 3 and 4, and `docs/phases/` holds one gate document or survey per phase.

## Source

- **The test.** On 2026-11-27 the lamp-arm golden fixture (`reference/examples/lamp-arm`) was built with agentcad 0.8.1 and with the benchhand prototype at `7f174e3`.
  - `7f174e3` is 21 commits after the pin `412b5d9` (`release.toml`). The test found the bugs at `7f174e3`. At the pin, the source shows the same diff verdict rule, staging folder, per-check code digest and changed-only path (V). The other bugs weren't checked at the pin (U).
  - benchhand-next has no geometry path yet, so the prototype stood in for it.
- **The source files.** The report, the timing log and a pyinstrument profile of one check aren't in the repository. They are cited by name, as "agentcad product test 2026-11-27, REPORT §section".
- **Labels**, as in the report: **V** measured, **E** estimated from the profile, **U** not verified.
- **Prior work.** The CAD-libraries study synthesis, §2.7, compared agentcad by its source. This note adds what the product test measured. It doesn't repeat the study's adoptions. Where an adoption is already in the catalogue, this note cites it.

## Summary

| Gain | Phase | Lives in | Contract change | ADR |
|---|---|---|---|---|
| 1. Content-addressed fact cache | 4 (Q4) | host (in-process LRU), store (on disk), resident kernel (decoded shapes) | new `cache/fact`; `InitializeResult.provider.codeDigest` | none |
| 2. Resident kernels, a forked worker per job | 4 | resident kernel provider | `HookResultBase.warm`; the envelope's top-level `warm` (Q5) | new ADR, and an amendment to provider protocol §2 and §7; Windows takes the cold path (Q1) |
| 3. One edit-loop job | 4 | host (job), resident kernel | the `model.edit_loop` tool's input and output, which reuse the planned version-diff result | none |
| 4. Bounded results with the first actionable finding | 3 (envelope), 4 (kernel error location) | envelope | `Finding.line`; `KernelBuildPartResult.errorLocation`; a findings-order rule | none |
| 5. Recovering interrupted work | 2 (staging), 3 (idempotency) | store, job service | `JobRecord.idempotencyKey` and `inputsDigest` | none: jobs end with the session (Q2) |
| 6. Parallel warm-up and quiet kernel logs | 4 | host (environments), kernel provider | none | none |

## Gains

### 1. Content-addressed fact cache

- **What changes.**
  - The host computes each provider's code digest once, at provider start. The provider reports it in `initialize`, or it ships in the release manifest. A check reads the stored digest.
  - Derived per-part facts are keyed by input hashes, not by path or mtime. These facts are:
    - volume and mass properties;
    - validity;
    - the read-back of the STEP, STL and 3MF outputs, watertightness, and the 3MF material and colour;
    - drawing features;
    - the loaded definition used for posing.
  - A fact is valid for exactly one invalidation tuple. The tuple holds:
    - the fact kind and its shape version;
    - the sha256 of each input file;
    - the producing provider's code digest;
    - the digest of the request parameters that shape the fact.

    The fact records its tuple. A matching path is never evidence of an unchanged input.
  - With these keys, an unchanged part costs one lookup, and a changed part costs its real work.
- **Where it lives.**
  - The host holds an in-process LRU of facts.
  - The store backs the LRU on disk, so a new session starts warm.
  - The resident kernel provider keeps the decoded OCC shapes of the current and the previous version, keyed by STEP sha256, for check, diff, pose and render.
- **Already in the plan.**
  - The provider protocol lets the host cache hook results by input digest ([provider protocol §4](../contract/provider-protocol.md), line 89).
  - The middleware chain has a cache stage ([plan](../design-plan.md), line 65), but no phase delivers the chain. The catalogue's existing `no-phase` question covers that.
  - This gain names the facts, the key and the invalidation rule. The owner put the fact cache in Phase 4, with the kernel providers (Q4). The chain's own phase stays under `no-phase`.
- **Phase.** 4, with the kernel providers and check orchestration (Q4). The contract lands at the start of Phase 4.
- **Contract.**
  - A new contract `contracts/cache/fact.tsp`, published as `cache/fact.schema.json`.
  - `InitializeResult.provider` in `contracts/provider/protocol.tsp` gains `codeDigest`. A new optional field is a minor change ([provider protocol §9](../contract/provider-protocol.md)).
  - The draft below is small and bounded. Bead B1 adds it to `contracts/`.

  ```typespec
  namespace Cache.Fact;

  @pattern("^[0-9a-f]{64}$")
  scalar Sha256 extends string;

  union FactKind { "mass-props", "validity", "export-readback", "drawing-features", "pose-definition", "render" }

  /** The invalidation tuple: a fact is valid exactly for these values. */
  model FactKey {
    kind: FactKind;
    /** The semver of the fact kind's value shape. */
    factVersion: string;
    /** Input role (step, stl, 3mf, glb) to the sha256 of its bytes. The step role is the sha256 of the STEP data section only (Q6). */
    inputs: Record<Sha256>;
    /** The producing provider's code digest, from initialize. */
    code: Sha256;
    /** The canonical-JSON sha256 of the request parameters that shape the fact. */
    params: Sha256;
  }

  model FactEntry {
    key: FactKey;
    /** The canonical-JSON sha256 of key: the lookup key. */
    keyDigest: Sha256;
    producer: string;
    value: unknown;
  }
  ```

  - The STEP input is the sha256 of the STEP data section only, which ignores the header (Q6). The header carries a timestamp, and the study saw build123d write different bytes for the same shape. The whole-file sha256 stays for artifacts.
- **ADR.** None. The cache follows the protocol's reproducibility rule and the plan's cache stage.
- **Measurement.** On lamp-arm, after the report's one-part edit (the LMP-0002 pocket widened from 8 to 10 mm):
  - **Changed-only check.** The prototype took 10.7 s, and its profiled run took 11.3 s (V). Of this, 2.61 s was the code digest, 2.45 s the output read-back, 2.28 s the definition reload and 1.78 s the STEP volume read-back, against 0.15 s of pair geometry (V). The target is 1 to 2 s (E).
  - **Identical re-check.** The prototype took 7.5 s with every pair a cache hit (V). The target is 11 fact hits for 11 parts and no STEP read (E).
  - **Code digest.** It is computed once per provider process. A test counts the calls.
  - **New session.** The first check of a second session gets its facts from disk. A test checks the hit count.
  - **STEP header.** A STEP file that differs only in its header timestamp is a cache hit. A test checks it.

### 2. Resident kernels, with a worker forked per job

- **What changes.**
  - The kernel providers declare `resident = true`.
  - The provider imports OCP and the kernel once. Before any boolean runs, it forks a fresh worker for each job, because a fork after OCP's TBB thread pool starts deadlocks (agentcad's `commands/run.py`, U).
  - The provider kills the worker's process group when the job ends.
  - Each result says whether it ran warm. When the warm path is unavailable, the result says `warm: false` with the reason, such as no fork on the platform, a zygote crash or a forced cold run.
  - On Windows there is no fork, so the resident kernel takes a cold path and reports `warm: false` (Q1). Spawn-based worker pools stay a spike, not part of this gain.
  - agentcad falls back without saying so: on macOS its daemon fails when the socket path is longer than 104 characters, and no result reports it (V).
- **Where it lives.** The resident kernel provider. The workers are the provider's children, inside its process group.
- **Already in the plan.**
  - Residency exists: viewer and renderer providers stay resident ([plan](../design-plan.md), line 194, and [provider protocol §2](../contract/provider-protocol.md), line 52).
  - No provider outlives the host ([plan](../design-plan.md), line 183). The host's kill reaches the workers too, so this gain keeps that rule.
  - The kernels aren't listed as resident, and the manifest example says `resident = false` ([provider protocol §7](../contract/provider-protocol.md), line 118).
- **Phase.** 4, with the provider runtime and the kernel providers. The ADR comes before Phase 4 starts.
- **Contract.**
  - `HookResultBase` in `contracts/provider/protocol.tsp` gains `warm: {warm: boolean, reason?: string}`, with `reason` required when `warm` is false, as `Coverage` does.
  - The envelope gains the same field at its top level, on every tool result (Q5). A tool whose work ran in no provider still carries it. Bead B4's contract change settles what such a result reports.
  - The manifest's `resident` field exists already (`contracts/provider/manifest.tsp`, line 50).
- **ADR.** Yes: a new ADR, "Kernel providers stay resident and fork a worker per job", and an amendment to provider protocol §2 (residency and crashes) and to the §7 example. An amendment alone isn't enough, for three reasons:
  - A worker crash isn't a provider crash, so §2's restart-once rule needs a worker rule.
  - `fork` is POSIX-only, and the plan ships a Claude Desktop bundle for macOS and Windows ([plan](../design-plan.md), line 459). The ADR records that on Windows the resident kernel takes a cold path and reports `warm: false` (Q1), and that spawn-based pools stay a spike.
  - `maxInFlight` (§8) then counts workers.
- **Measurement.**
  - The prototype pays 3.26 s of cadquery import per build (V), and agentcad's warm daemon saves 2 to 3 s per command (V).
  - The target saves about 3 s per build, check, diff, inspect or render call (E).
  - The comparison is one call's wall time, warm and forced cold, on the same inputs, over 3 runs each. The report's runs were single, with about ±10 % noise.
  - A conformance case runs a boolean in a forked worker, which must finish within the hook deadline. Another case forces the cold path and checks for `warm: false` with a reason. A third checks that a platform without fork (Windows) takes the cold path and reports `warm: false` with the reason "no fork on the platform".

### 3. One edit-loop job

- **What changes.** One job builds the version, then checks and diffs only the changed parts, using the shapes already in memory (gains 1 and 2). It returns:
  - the changed parts;
  - the volume deltas per part: shared, A-only and B-only;
  - the blocking findings.
- **Where it lives.** The host runs it as one job (ADR-0018), and the resident kernel does the geometry.
- **Already in the plan.**
  - Work over about 30 s returns a job handle ([plan](../design-plan.md), line 353; ADR-0018).
  - The version-diff result contract is planned (catalogue `model-diff`, `contracts_planned`; study synthesis §6.2, rank 7).
  - The edit loop as one call is new.
- **Phase.** 4. It needs `model.build`, the check and `model.diff`.
- **Contract.** The input and output of the `model.edit_loop` tool in `contracts/`. The output reuses the version-diff result per part, and the findings use the envelope. Whether the loop is a tool of its own or a mode of `model.build` is the contract bead's choice. The catalogue records the tool as `proposed`.
- **ADR.** None.
- **Measurement.**
  - The prototype took 3 calls and 41.5 s: run 16.6 s, check 10.7 s and diff 14.2 s (V). agentcad took 1 call and 24.6 s, with an exact diff (V).
  - The report puts most of the standalone diff's 14.2 s down to reloading STEP (E).
  - The target is 1 call of about 15 s once gains 1 and 2 are in (E), over 3 runs.

### 4. Bounded results that carry the first actionable finding

- **What changes.** The short summary names:
  - the blocking pair and its mm³;
  - for a build error, the PN and the `file:line`;
  - for a diff, the changed parts.

  The first finding is the first one the agent can act on: the blocking findings come first.
- **Where it lives.** The envelope.
- **Already in the plan.**
  - The catalogue proposes the bounded envelope with `truncated`, `estimate` and a `retrieve` handle (capability `bounded-results`, from the study's §2.7). Its blocking question `bounded-results` waits on the owner.
  - Client output limits are in the plan ([plan](../design-plan.md), line 352).
  - This gain adds what the summary must contain. It doesn't add another bounding mechanism.
- **Phase.** 3 for the envelope rule and `Finding.line`, and 4 for the kernel's error location.
- **Contract.**
  - `contracts/common/finding.tsp`: `Finding` gains an optional 1-based `line`.
  - `contracts/provider/protocol.tsp`: `KernelBuildPartResult` gains `errorLocation: {path, line, function?}`.
  - `docs/contract/envelope.md` gains the order rule: blocking findings first.
  - An interference finding sets `subject` to the first PN, and its `message` names both PNs and the mm³.
- **ADR.** None.
- **Measurement.**
  - The prototype's short line was 180 to 215 B and said only `interference`, or gave the message without the PN and line. The detail was in a 116 KB JSON (V).
  - Tests on the interference and fillet cases check that the summary names the pair and 117.1 mm³, and `LMP-0002` with `model.py:169`.
  - The agent makes one call fewer per failure (E).

### 5. Recovering interrupted work

- **What changes.**
  1. **Staging collection.** The build's staging folder is named by its job id, not by a bare PID, and the version store collects a staging folder whose job has ended. The job record's `ProcessIdentity` already handles PID reuse (`contracts/jobs/job.tsp`, line 72), and the job service already cleans up on start (`packages/benchhand-core/src/benchhand_core/jobs/service.py`, lines 17-19). In the prototype, a leftover `.vN.partial-PID` also makes `store gc` refuse to run until someone deletes it by hand (`skills/cad-model/scripts/cadmodel/build.py`, lines 785-788, at the pin).
  2. **A dropped call.** A build that a dropped tool call started keeps running as a job, and `jobs.status` and `jobs.result` fetch it (ADR-0018). The same holds when the client disconnects while the server is still up: the job keeps running, and a client that reconnects can fetch its result. Jobs end with the session (Q2).
  3. **Idempotency keys.** `jobs.start` takes an idempotency key that binds the inputs:
     - the same key with the same inputs replays the job;
     - the same key with different inputs is refused as a conflict.
- **Where it lives.** The version store (folder collection) and the job service (keys).
- **Already in the plan.** The catalogue's `bounded-results` proposal already puts idempotency keys on `model.build` and `jobs.start` (study synthesis §6.2, rank 3). This gain adds the replay and conflict rules.
- **Phase.** 2 for the staging collection, with version snapshots ([plan](../design-plan.md), line 561). 3 for the keys, with `jobs.*` ([plan](../design-plan.md), line 573).
- **Contract.**
  - `JobRecord` in `contracts/jobs/job.tsp` gains `idempotencyKey` and `inputsDigest`, and the `jobs.start` input gains `idempotency_key`.
  - A conflict returns `status: refused` with a reason and a `next_actions` entry ([envelope](../contract/envelope.md), line 14).
  - The staging collection needs no contract: the job id names the folder.
- **ADR.** None. Jobs end with the session (Q2). A build that outlives the server, as agentcad's daemon did when its client was killed (V), would contradict D4 and the job service's owner rule, so it isn't adopted. After the session ends, the next start collects the staging folder, and the store's reuse of built parts makes a retry cheap.
- **Measurement.**
  - A test kills a build mid-run and checks that the next start collects its staging folder.
  - A test drops a call and checks that `jobs.status` still reports the job. A test disconnects the client while the server runs and checks that a new connection fetches the job's result with `jobs.result`.
  - A test replays a key and checks that no second build runs. A test changes the inputs under the same key and checks for `refused`.
  - The prototype's retry after the kill took 8.3 s, because the store kept the parts that were already built (V).

### 6. Parallel environment warm-up, and quiet kernel logs

- **What changes.**
  - The host warms the provider environments in parallel.
  - Kernel workers silence OCCT's "Statistics on Transfer" banners, which carry ANSI colours, and send OCCT messages as structured `$/log` lines.
- **Where it lives.** The host's environment builder, and the kernel provider's worker.
- **Already in the plan.**
  - The first start warms the environments in the background, with progress in `env.doctor` ([plan](../design-plan.md), line 266). The plan doesn't say whether in parallel.
  - stderr is a human log, and structured logs go through `$/log` ([provider protocol §1 and §5](../contract/provider-protocol.md), line 18).
- **Phase.** 4, with the provider environments and the kernel providers.
- **Contract.** None.
- **ADR.** None.
- **Measurement.**
  - The prototype's cold preflight took 4 min 12 s: the cadquery environment took 146 s and the build123d one 86 s, one after the other (V). Run in parallel, the pair takes about 150 s and saves about 90 s (E). Contention on the uv cache lock is untested (U).
  - The banners took 1.8 KB of stderr per build and 6.9 KB per drawing (V). The target is no banner bytes on stderr, with every OCCT message as a `$/log` line. A test writes a STEP file and checks stderr.

## Interference rule

This is RULE-39 in the register. The owner decided its threshold and fit limits (Q3).

- **The rule.**
  - Interference that the record declares is allowed, within the declared fit's own limits. A declaration is one of these:
    - an interference press fit or locating fit in `interfaces.yaml`, such as `press_fit` 5 H7/p6;
    - a heat-set insert on exactly that occurrence pair;
    - an explicit allow of the pair (the prototype's `--allow-interference REF:REF`).
  - The check reports each declared overlap as allowed, with its declared fit, its interface id and the measured mm³.
  - A declared fit's overlap is capped at the fit's own limits (IR-115). Overlap above them blocks, with a finding that names the fit, its interface id, the measured mm³ and the limit. An explicit allow and a heat-set insert name no fit limits, so nothing caps them.
  - A declared fit with zero overlap counts as realised (RULE-16). It isn't a finding.
  - Of the other measured overlaps, an undeclared one above the collision provider's stated tolerance blocks (RULE-28). The provider states the tolerance, so no fixed value applies. An undeclared overlap at or below it is a non-blocking sub-tolerance finding. An unknown measurement still fails (RULE-05).
- **The prototype at the pin** (V, `skills/cad-model/scripts/cadmodel/check.py`, lines 429-485; the threshold is `INTERFERENCE_MM3 = 1e-3` in `skills/cad-motion/scripts/pose.py`, line 114).
  - In the product test, LMP-0002/LMP-0005 overlapped by 1.50 mm³ under IF-001's declared 5 H7/p6 press fit and gave `allowed: true, ok: true`.
  - The clevis slot narrowed from 10.4 to 9.6 mm against a 10 mm tongue made an undeclared 117.1 mm³ LMP-0002/LMP-0003 overlap, which blocked (V).
  - Five behaviours at the pin matter. The port changes the first two and keeps the rest:
    - the prototype allows any overlap on a declared pair, and the port caps a declared fit at its limits (Q3);
    - the prototype fails a declared interference fit that measures no overlap (`declared_fit_not_realized`), and the port counts it as realised (Q3);
    - an allowed pair measured only inexactly fails (kept, RULE-05);
    - an allow that names no pair of the version fails (kept);
    - a failed measurement counts as unknown, and it fails (kept, RULE-05).
- **Existing rules.**
  - RULE-07 says designed interference never blocks, but not how it is reported. RULE-39 reports it, and bounds a declared fit by its limits.
  - RULE-28 makes an overlap below the measurement tolerance a non-blocking finding. RULE-39 uses the same tolerance, which the collision provider states (IR-021), in place of the prototype's fixed `INTERFERENCE_MM3`.
  - RULE-16 treats a fit modelled at basic size as realised when its overlap is zero. RULE-39 follows it.
  - IR-115 bounds a declared fit's overlap by the fit's limits. RULE-39 follows it.
  - No earlier rule states the report fields, so RULE-39 states them.
- **The mixed test.** Phase 4 ports it, with the interference check (catalogue `model-inspect`, and the collision provider that the reference map names). The register tracks it as IR-212.
  - One assembly has a declared press-fit overlap within the fit's limits and an undeclared overlap above the provider's tolerance.
  - The verdict is `fail`. Exactly one finding blocks, and it names the undeclared pair and its mm³.
  - The declared pair's row is allowed and doesn't block. It names the fit, the interface id and the mm³.
  - The exceeded-fit case. A second assembly has a declared fit whose overlap is above the fit's limits. The verdict is `fail`. Exactly one finding blocks, and it names the fit, the interface id, the measured mm³ and the limit.
  - The zero-overlap case. A declared interference fit with no overlap is realised and raises no finding.
  - The fixture is synthetic (RULE-22), or lamp-arm with the clevis edit.
  - The prototype tests these cases only one at a time (`reference/skills/cad-model/tests/test_cad_model.py`, lines 1876-1891).

## Rendering plan

Rendering belongs to Phase 4 (`render-chromium`, [plan](../design-plan.md), line 581). The current phase is 2, so this note doesn't profile the renderer. The steps are in order:

1. **Profile first.** Attribute the prototype's 17.9 s for 4 views (V) to launch, load, pose, render and write. The likely split is mostly cold start and per-view page work, not GPU time (U).
2. **Keep Chromium resident.** The plan already makes the renderer resident ([plan](../design-plan.md), line 194). Keep one warm page per project, then measure again. agentcad renders 3 views in 2.4 s through OCC offscreen in its warm daemon, at the zero pose with simple lighting (V).
3. **OCC offscreen only if still slow.** A fast preview path through OCC offscreen in the resident kernel comes only if step 2 is still slow. It needs a GL context, which is a risk headless and in the container (U). Chromium stays the renderer for review-quality images.
4. **Cache renders.** The key is the GLB sha256, the camera, the pose, the size and the renderer's code digest. The key uses the fact cache's tuple, with the fact kind `render` (gain 1).

The upside-down iso view is a prototype bug (IR-199), not a speed issue.

## What not to copy from agentcad

- An always-loaded 30 KB instructions file, or a 146 KB docs index. ADR-0011 serves guidance from the server, and the study rejects the `AGENTS.md` install (synthesis §2.7).
- A daemon that outlives the session ([plan](../design-plan.md), line 183).
- A fallback that hides a failed warm path. Every result reports `warm` (gain 2).
- Running the whole script again, with no reuse per part.
- Running validation twice per build on unchanged parts.

## Decisions

The owner answered Q1 to Q6 on 2026-11-27. Each answer is recorded where it binds: the gain, the register or the catalogue.

- **Q1. A fork per job, and Windows. Decided.** On Windows the resident kernel takes a cold path and reports `warm: false`. The new resident-kernel ADR (B3) records this. Spawn-based worker pools stay a spike. This binds gain 2.
- **Q2. Jobs and the session. Decided.** Jobs end with the session. A client that disconnects while the server is still up can still fetch the job's result. A job that outlives the server isn't adopted. This binds gain 5 and the catalogue's `job-service`.
- **Q3. The interference threshold and the fit limits. Decided.**
  - The blocking threshold for an undeclared overlap is the collision provider's stated tolerance (RULE-28), not a fixed 0.001 mm³.
  - A declared fit's overlap is capped at the fit's own limits (IR-115). Overlap above them blocks.
  - A declared fit with zero overlap counts as realised (RULE-16).
  - This rewrites RULE-39 and IR-212. See [Interference rule](#interference-rule).
- **Q4. The fact cache's phase. Decided.** The fact cache belongs to Phase 4, with the kernel providers. The middleware chain's own phase stays open under `no-phase`.
- **Q5. `warm` in the envelope. Decided.** `warm` sits at the top level of the envelope, on every tool result.
- **Q6. The STEP hash in the fact key. Decided.** A part's facts are keyed by the hash of the STEP data section only, ignoring the header. The whole-file sha256 stays for artifacts.

## Beads

Filed in the `bhn` ledger on 2026-11-27. The ids follow the note's numbering. Phase labels are `phase-2` to `phase-4`. B3 and B19 have priority 1, the rest priority 2.

| # | Bead | Title | Phase | Depends on |
|---|---|---|---|---|
| B1 | bhn-ufw | Fact cache contract and host LRU | 4 | none |
| B2 | bhn-4d2 | Code digest once per provider | 4 | B1 |
| B3 | bhn-s57 | ADR: resident kernels fork a worker per job | before 4 | none |
| B4 | bhn-6t0 | Resident kernel providers with a forked worker per job and `warm` in results | 4 | B3 |
| B5 | bhn-9x4 | The `model.edit_loop` job | 4 | B1, B4 |
| B6 | bhn-4vc | The envelope's first actionable finding | 3 (envelope), 4 (kernel) | none |
| B7 | bhn-l9w | Staging collection by job id | 2 | none |
| B8 | bhn-55v | Idempotency keys on `jobs.start` | 3 | none |
| B9 | bhn-wav | Parallel environment warm-up and quiet OCCT logs | 4 | none |
| B10 | bhn-5lj | Render profile, then a resident Chromium and a render cache | 4 | B1 |
| B11 | bhn-nub | Port IR-198: assembly drawing paths under a relative output folder | 4 | none |
| B12 | bhn-w23 | Port IR-199: the iso camera keeps +Z up | 4 | none |
| B13 | bhn-9mh | Port IR-200: the short result names the blocking detail | 3 | B6 |
| B14 | bhn-6wk | Port IR-201: a diff is `ok` without a verdict | 4 | none |
| B15 | bhn-98o | Port IR-202: interrupted staging folders are collected | 2 | B7 |
| B16 | bhn-8ru | Port IR-203: no OCCT banners on stderr | 4 | B9 |
| B17 | bhn-1et | Port IR-204: the assembly drawing returns the bounded envelope | 4 | B6 |
| B18 | bhn-72b | Port IR-205: a changed-only check reuses unchanged parts' facts | 4 | B1 |
| B19 | bhn-xqo | The mixed interference test (RULE-39, IR-212) | 4 | none |

The dependency column lists only the beads that block each other. Work that has no bead yet, such as the provider runtime, the kernel providers, `model.build` and the interference check, is named in each bead's description. B3's phase label is `phase-3`, since the ADR comes before Phase 4 starts. B6 carries both `phase-3` and `phase-4`. The acceptance of each bead is in the ledger.

## Register and catalogue changes

- **Register** (`docs/migration/issue-register.yaml`):
  - IR-198 to IR-205 are the 8 prototype bugs.
  - IR-206 to IR-211 are the distinct slowness and recovery findings:
    - the code digest;
    - the cold kernel import;
    - the three-call edit loop;
    - the serial environment warm-up;
    - the slow renders;
    - work lost to a killed run.
  - IR-212 is the mixed interference test, with the exceeded-fit and zero-overlap cases.
  - RULE-39 is the interference rule, as decided in Q3.
  - The register's source pattern now accepts "agentcad product test 2026-11-27, REPORT §section".
- **Catalogue** (`docs/architecture/capabilities.yaml`), all `proposed`:
  - the capabilities `fact-cache`, `resident-kernels` and `edit-loop`;
  - the tool `model.edit_loop`;
  - a note on `jobs.start` about the key semantics;
  - notes on `resident-kernels`, `job-service` and `fact-cache` that cite the decisions Q1, Q2, Q4 and Q6;
  - a new source kind, `design`, for a name a design note proposes, checked as a path:line pointer like `plan`.

  The open questions `resident-kernel-fork` (Q1) and `job-outlives-session` (Q2) are removed, with their references, since the catalogue's schema has no decided status.
