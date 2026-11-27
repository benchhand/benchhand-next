<!--
SPDX-FileCopyrightText: 2026 Sjors Robroek

SPDX-License-Identifier: MPL-2.0
-->

# Edit-loop performance: design input from the agentcad product test

Status: design input for the owner's review. It was written on 2026-11-27 against `main` at `e739221a`. It proposes changes and doesn't make any. No contract, ADR or code changes. The register entries IR-198 to IR-212, the design rule RULE-39 and the catalogue entries record the proposals ([Register and catalogue changes](#register-and-catalogue-changes)).

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
| 1. Content-addressed fact cache | 4 | host (in-process LRU), store (on disk), resident kernel (decoded shapes) | new `cache/fact`; `InitializeResult.provider.codeDigest` | none |
| 2. Resident kernels, a forked worker per job | 4 | resident kernel provider | `HookResultBase.warm`; the envelope's `warm` | new ADR, and an amendment to provider protocol §2 and §7 |
| 3. One edit-loop job | 4 | host (job), resident kernel | the `model.edit_loop` tool's input and output, which reuse the planned version-diff result | none |
| 4. Bounded results with the first actionable finding | 3 (envelope), 4 (kernel error location) | envelope | `Finding.line`; `KernelBuildPartResult.errorLocation`; a findings-order rule | none |
| 5. Recovering interrupted work | 2 (staging), 3 (idempotency) | store, job service | `JobRecord.idempotencyKey` and `inputsDigest` | none, unless jobs outlive the session (Q2) |
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
  - This gain names the facts, the key and the invalidation rule, and puts the cache in Phase 4.
- **Phase.** 4, with the kernel providers and check orchestration. The contract lands at the start of Phase 4.
- **Contract.**
  - A new contract `contracts/cache/fact.tsp`, published as `cache/fact.schema.json`.
  - `InitializeResult.provider` in `contracts/provider/protocol.tsp` gains `codeDigest`. A new optional field is a minor change ([provider protocol §9](../contract/provider-protocol.md)).
  - The draft below is small and bounded. It isn't added to `contracts/` before the owner approves it.

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
    /** Input role (step, stl, 3mf, glb) to the sha256 of its bytes. */
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

  - The STEP input hash is an open choice (Q6).
- **ADR.** None. The cache follows the protocol's reproducibility rule and the plan's cache stage.
- **Measurement.** On lamp-arm, after the report's one-part edit (the LMP-0002 pocket widened from 8 to 10 mm):
  - **Changed-only check.** The prototype took 10.7 s, and its profiled run took 11.3 s (V). Of this, 2.61 s was the code digest, 2.45 s the output read-back, 2.28 s the definition reload and 1.78 s the STEP volume read-back, against 0.15 s of pair geometry (V). The target is 1 to 2 s (E).
  - **Identical re-check.** The prototype took 7.5 s with every pair a cache hit (V). The target is 11 fact hits for 11 parts and no STEP read (E).
  - **Code digest.** It is computed once per provider process. A test counts the calls.
  - **New session.** The first check of a second session gets its facts from disk. A test checks the hit count.

### 2. Resident kernels, with a worker forked per job

- **What changes.**
  - The kernel providers declare `resident = true`.
  - The provider imports OCP and the kernel once. Before any boolean runs, it forks a fresh worker for each job, because a fork after OCP's TBB thread pool starts deadlocks (agentcad's `commands/run.py`, U).
  - The provider kills the worker's process group when the job ends.
  - Each result says whether it ran warm. When the warm path is unavailable, the result says `warm: false` with the reason, such as no fork on the platform, a zygote crash or a forced cold run. agentcad falls back without saying so: on macOS its daemon fails when the socket path is longer than 104 characters, and no result reports it (V).
- **Where it lives.** The resident kernel provider. The workers are the provider's children, inside its process group.
- **Already in the plan.**
  - Residency exists: viewer and renderer providers stay resident ([plan](../design-plan.md), line 194, and [provider protocol §2](../contract/provider-protocol.md), line 52).
  - No provider outlives the host ([plan](../design-plan.md), line 183). The host's kill reaches the workers too, so this gain keeps that rule.
  - The kernels aren't listed as resident, and the manifest example says `resident = false` ([provider protocol §7](../contract/provider-protocol.md), line 118).
- **Phase.** 4, with the provider runtime and the kernel providers. The ADR comes before Phase 4 starts.
- **Contract.**
  - `HookResultBase` in `contracts/provider/protocol.tsp` gains `warm: {warm: boolean, reason?: string}`, with `reason` required when `warm` is false, as `Coverage` does.
  - The envelope gains the same field for every tool whose work ran in a provider.
  - The manifest's `resident` field exists already (`contracts/provider/manifest.tsp`, line 50).
- **ADR.** Yes: a new ADR, "Kernel providers stay resident and fork a worker per job", and an amendment to provider protocol §2 (residency and crashes) and to the §7 example. An amendment alone isn't enough, for three reasons:
  - A worker crash isn't a provider crash, so §2's restart-once rule needs a worker rule.
  - `fork` is POSIX-only, and the plan ships a Claude Desktop bundle for macOS and Windows ([plan](../design-plan.md), line 459). Windows needs a cold path, and a result there reports `warm: false` (Q1).
  - `maxInFlight` (§8) then counts workers.
- **Measurement.**
  - The prototype pays 3.26 s of cadquery import per build (V), and agentcad's warm daemon saves 2 to 3 s per command (V).
  - The target saves about 3 s per build, check, diff, inspect or render call (E).
  - The comparison is one call's wall time, warm and forced cold, on the same inputs, over 3 runs each. The report's runs were single, with about ±10 % noise.
  - A conformance case runs a boolean in a forked worker, which must finish within the hook deadline. Another case forces the cold path and checks for `warm: false` with a reason.

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
  2. **A dropped call.** A build that a dropped tool call started keeps running as a job, and `jobs.status` and `jobs.result` fetch it (ADR-0018).
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
- **ADR.** None, if jobs stay inside the session. A build that outlives the server, as agentcad's daemon did when its client was killed (V), contradicts D4 and the job service's owner rule (Q2).
- **Measurement.**
  - A test kills a build mid-run and checks that the next start collects its staging folder.
  - A test drops a call and checks that `jobs.status` still reports the job.
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

This is RULE-39 in the register.

- **The rule.**
  - Interference that the record declares is allowed and never blocks. A declaration is one of these:
    - an interference press fit or locating fit in `interfaces.yaml`, such as `press_fit` 5 H7/p6;
    - a heat-set insert on exactly that occurrence pair;
    - an explicit allow of the pair (the prototype's `--allow-interference REF:REF`).
  - The check reports each declared overlap as allowed, with its declared fit, its interface id and the measured mm³.
  - Of the measured overlaps, only an undeclared one above 0.001 mm³ blocks. An unknown measurement still fails (RULE-05).
- **The prototype at the pin** (V, `skills/cad-model/scripts/cadmodel/check.py`, lines 429-485; the threshold is `INTERFERENCE_MM3 = 1e-3` in `skills/cad-motion/scripts/pose.py`, line 114).
  - In the product test, LMP-0002/LMP-0005 overlapped by 1.50 mm³ under IF-001's declared 5 H7/p6 press fit and gave `allowed: true, ok: true`.
  - The clevis slot narrowed from 10.4 to 9.6 mm against a 10 mm tongue made an undeclared 117.1 mm³ LMP-0002/LMP-0003 overlap, which blocked (V).
  - Three more behaviours at the pin keep unknown from passing (RULE-05), and the port keeps them:
    - an allowed pair measured only inexactly fails;
    - an allow that names no pair of the version fails;
    - a failed measurement counts as unknown, and it fails.
- **Existing rules.**
  - RULE-07 says designed interference never blocks, but not how it is reported.
  - RULE-28 makes an overlap below the measurement tolerance a non-blocking finding.
  - RULE-16 treats a fit modelled at basic size as realised when its overlap is zero. No existing rule states the report fields or the blocking threshold, so RULE-39 is new. Its conflicts with RULE-28, RULE-16 and IR-115 are open (Q3).
- **The mixed test.** Phase 4 ports it, with the interference check (catalogue `model-inspect`, and the collision provider that the reference map names). The register tracks it as IR-212.
  - One assembly has a declared press-fit overlap and an undeclared overlap.
  - The verdict is `fail`. Exactly one finding blocks, and it names the undeclared pair and its mm³.
  - The declared pair's row is allowed and doesn't block. It names the fit, the interface id and the mm³.
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

## Open questions for the owner

- **Q1. A fork per job, and Windows.** `fork` is POSIX-only, and the plan ships a Windows Claude Desktop bundle. Is a cold path with `warm: false` acceptable on Windows, or should kernels use a spawn-based worker pool there? Recommendation: a cold path that reports `warm: false`, recorded in the new ADR.
- **Q2. Jobs and the session.** The report's gain 5 asks that a build job survive a client disconnect. Inside a session, job handles already cover a dropped call. A job that outlives the server contradicts D4 ([plan](../design-plan.md), line 12), the rule that no provider outlives the host ([plan](../design-plan.md), line 183) and the job contract's owner rule (`contracts/jobs/job.tsp`, line 103). Recommendation: jobs end with the session. Collect the staging folder, and let the store's reuse of built parts make a retry cheap (8.3 s in the test, V).
- **Q3. The interference threshold and the fit limits.**
  - RULE-39 blocks an undeclared overlap above a fixed 0.001 mm³. RULE-28 uses the collision provider's stated tolerance (IR-021), and that tolerance may be larger.
  - IR-115 bounds a declared pair's allowed overlap by the fit's limits, while the prototype allows any overlap on a declared pair.
  - The prototype fails a declared interference fit that measures no overlap (`declared_fit_not_realized`), and RULE-16 counts that fit as realised.
  - The owner needs to decide which threshold binds, and whether a declared pair that overlaps beyond its fit's limits is allowed or gets a finding.
- **Q4. The fact cache's phase.** The middleware chain, and so its cache stage, has no phase (catalogue `no-phase`). Is Phase 4 right for the fact cache?
- **Q5. `warm` in the envelope.** Should `warm` sit at the top of the envelope or in each tool's payload? Recommendation: the top level, set only by tools whose work ran in a provider.
- **Q6. The STEP hash in the fact key.** The whole-file sha256 changes with the STEP header's timestamp, and the study saw build123d write different bytes for the same shape. Its synthesis records the prototype's `step_data_hash` (`skills/cad-motion/scripts/pose.py`, line 736, at the pin), which ignores the header. Recommendation: key facts by the hash of the data section, and keep the whole-file sha256 for artifacts.

## Proposed beads

Not created. Each bead is for the owner's review.

| # | Title | Phase | Depends on | Acceptance |
|---|---|---|---|---|
| B1 | Fact cache contract and host LRU | 4 | owner on Q4 and Q6 | `cache/fact` published. On lamp-arm after the one-part edit, a changed-only check gets 10 of 11 parts' facts from the cache. An identical re-check reads no STEP. A second session hits the disk store. |
| B2 | Code digest once per provider | 4 | B1, provider runtime | `codeDigest` in `initialize`. A test counts one digest per provider process. |
| B3 | ADR: resident kernels fork a worker per job | before 4 | owner on Q1 | The ADR is accepted, and provider protocol §2 and §7 are amended. |
| B4 | Resident kernel providers with a forked worker per job and `warm` in results | 4 | B3, provider runtime, kernel providers | The conformance cases for a boolean in a forked worker and for the forced cold path pass. Warm calls are about 3 s faster than cold ones over 3 runs. |
| B5 | The `model.edit_loop` job | 4 | B1, B4, `model.build`, the check, `model.diff` | One call returns the changed parts, the shared, A-only and B-only volumes, and the blocking findings. The lamp-arm edit loop takes about 15 s, against 41.5 s. |
| B6 | The envelope's first actionable finding | 3 (envelope), 4 (kernel) | the owner's answer on `bounded-results` | `Finding.line` and `KernelBuildPartResult.errorLocation` are published. The summaries of the interference and fillet cases name the pair and its mm³, and the PN with its `file:line`. |
| B7 | Staging collection by job id | 2 | version snapshots, job service | A killed build's staging folder is collected on the next start. `store gc` isn't blocked. |
| B8 | Idempotency keys on `jobs.start` | 3 | owner on Q2, `jobs.*` tools | A replay starts no second build. A conflict returns `refused` with a reason. |
| B9 | Parallel environment warm-up and quiet OCCT logs | 4 | provider environments, kernel providers | A cold first start takes about the longest single environment build. A STEP write leaves no banner on stderr, and OCCT messages arrive as `$/log` lines. |
| B10 | Render profile, then a resident Chromium and a render cache | 4 | render-chromium, B1 | A profile attributes the 17.9 s. A warm 4-view render is measured again, and a repeated render is a cache hit. |
| B11 | Port IR-198: assembly drawing paths under a relative output folder | 4 | drawings provider | Every artifact path exists, as the host's check under `outDir` requires. |
| B12 | Port IR-199: the iso camera keeps +Z up | 4 | render-chromium | The iso view's camera `up` has a positive Z component, and an engraving test reads the right way up. |
| B13 | Port IR-200: the short result names the blocking detail | 3 | B6 | Covered by B6's tests. |
| B14 | Port IR-201: a diff is `ok` without a verdict | 4 | `model.diff` | A diff that finds changes returns `status: ok` with no `verdict`. |
| B15 | Port IR-202: interrupted staging folders are collected | 2 | B7 | Covered by B7's tests. |
| B16 | Port IR-203: no OCCT banners on stderr | 4 | B9 | Covered by B9's tests. |
| B17 | Port IR-204: the assembly drawing returns the bounded envelope | 4 | B6, drawings provider | The drawing tool's result stays under the envelope bound, and the full report is an artifact. |
| B18 | Port IR-205: a changed-only check reuses unchanged parts' facts | 4 | B1 | Covered by B1's tests. |
| B19 | The mixed interference test (RULE-39, IR-212) | 4 | owner on Q3, the interference check | The mixed test passes as specified above. |

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
  - IR-212 is the mixed interference test.
  - RULE-39 is the interference rule.
  - The register's source pattern now accepts "agentcad product test 2026-11-27, REPORT §section".
- **Catalogue** (`docs/architecture/capabilities.yaml`), all `proposed`:
  - the capabilities `fact-cache`, `resident-kernels` and `edit-loop`;
  - the tool `model.edit_loop`;
  - a note on `jobs.start` about the key semantics;
  - the open questions `resident-kernel-fork` (Q1) and `job-outlives-session` (Q2);
  - a new source kind, `design`, for a name a design note proposes, checked as a path:line pointer like `plan`.
