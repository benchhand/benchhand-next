# Data flow

Five sequences: one MCP tool call, a long job, evidence and freeze, release, and record migration.
Names come from the code where it exists on `main`, and from the plan otherwise.

## (a) One MCP tool call

```mermaid
%%{init: {"theme": "neutral"}}%%
sequenceDiagram
  autonumber
  participant H as Agent host
  participant S as MCP server, Phase 3
  participant M as Middleware chain, open phase
  participant F as Flow engine, Phase 2
  participant P as Provider host, open phase
  participant K as Provider, e.g. kernel-build123d, Phase 4
  participant R as Record service, store and validate on main

  H->>S: tools/call model.build with a version reference
  S->>M: call through validation, policy, audit, provenance, cache, telemetry
  M->>M: validate the input against the tool's inputSchema
  M->>F: guard: may this tool run at flow.stage? CEL
  alt out of order
    F-->>M: refused, with a reason and the next action
    M-->>S: envelope: status, findings, next_actions
    S-->>H: result, and nothing ran
  else allowed
    F-->>M: allowed
    M->>P: run the kernel/build hook
    P->>K: kernel/build with projectRoot and outDir, JSON-RPC 2.0, Content-Length framing
    K--)P: $/progress with id, fraction and message
    K-->>P: result with artifacts: path, mediaType, role, bytes, sha256
    P->>P: check each artifact is under outDir and matches its size and sha256, else provider-output-invalid
    P->>R: accept the artifacts into hw/, the host is the only writer
    R->>R: check each write against its contract before touching disk
    R-->>M: findings
    M-->>S: envelope: status, findings, artifacts, next_actions
    S->>S: validate the output against the tool's outputSchema
    S-->>H: structuredContent holding the envelope
  end
  Note over H,P: Work that can run past about 30 s returns a job handle instead, as in (b)
```

## (b) A long-running job

```mermaid
%%{init: {"theme": "neutral"}}%%
sequenceDiagram
  autonumber
  participant H as Agent host
  participant S as MCP server, jobs.* tools, Phase 3
  participant PH as Provider host, open phase
  participant J as JobService, on main
  participant St as RecordStore, .benchhand/runs/, on main
  participant Sup as supervisor.py, on main
  participant C as Job command

  H->>S: a tool whose work can run past about 30 s
  S->>J: start(JobSpec: kind, argv, cwd, env, result_path)
  J->>St: write JobRecord, status queued
  J->>Sup: SupervisedProcess(argv)
  Sup->>C: start in a process group of its own, with BENCHHAND_JOB_ID and BENCHHAND_JOB_RESULT
  Sup-->>J: started, on the status fd
  J->>St: status running, with the process identity
  J-->>S: JobHandle: job_id, status running
  S-->>H: job handle
  opt progress
    PH->>J: report_progress(job_id, fraction, message) for a provider $/progress
    J->>St: progress
  end
  H->>S: jobs.status(job_id)
  S->>J: status(job_id)
  J->>J: reap: an ended job gets its final record
  J-->>S: JobHandle: status, progress
  alt cancel
    H->>S: cancel, through a jobs.* tool the plan doesn't name
    S->>J: cancel(job_id)
    J->>Sup: stop request
    Sup->>C: TERM to the group, KILL after the grace period
    J->>St: status cancelled
    J-->>S: JobHandle: status cancelled
  else the command ends
    C->>C: write the result file at BENCHHAND_JOB_RESULT
    C-->>Sup: exit status
    Sup->>Sup: kill the whole group
    H->>S: jobs.result(job_id)
    S->>J: result(job_id)
    J->>J: reap: final status succeeded or failed
    J-->>S: path of the result file, or JobNotSucceeded
    S-->>H: result
  end
  Note over PH,J: Open: the plan doesn't say how a provider request becomes a JobService job
  Note over H,J: Where a host declares the tasks extension, the tasks adapter carries the job, behind a flag, Phase 5
```

## (c) Evidence and freeze

```mermaid
%%{init: {"theme": "neutral"}}%%
sequenceDiagram
  autonumber
  actor U as Designer
  participant H as Agent host
  participant S as MCP server, Phase 3
  participant K as Kernel and check providers, Phase 4
  participant V as Record versions and bundles, Phase 2
  participant E as Evidence service, on main
  participant F as Flow engine, Phase 2
  participant R as Record store, on main

  H->>S: model.build
  S->>K: kernel/build
  K-->>S: STEP, GLB and the manifest, as artifacts
  S->>V: snapshot hw/ into built version vN, sealed by its manifest
  H->>S: check tools, e.g. interference and process checks
  S->>K: collision/check, process-check/check
  K-->>S: results, as artifacts
  S->>V: sealed check packets, bound to the manifest sha256 of vN
  S->>E: read_built_version(root, record, vN, shipped_guidelines)
  E->>R: current record
  E-->>S: BuiltVersion, or BuiltVersionError when vN isn't built or fails its seal
  S->>E: assess(record, built, today)
  E->>E: expected obligations, sealed packets, evidence ledger, waivers
  E->>E: acceptance inventory, then acceptance_digest gives evidence_sha256
  E-->>S: EvidenceAssessment: statuses, facets, findings, complete, acceptance formed or refused
  Note over S,E: Open: which tool runs the assessment isn't stated
  S->>F: design_freeze gate, a single human gate
  F-->>S: gate packet, next action: ask the user
  S-->>H: packet and preview URL
  H->>U: present the packet and ask, in chat
  U-->>H: answer
  H->>S: flow.record_decision, channel chat, the user's words quoted
  alt empty, declined or cancelled
    F-->>S: no answer, so the gate stays open
  else explicit approval
    F->>R: decision record: kind gate, status approved, approval with channel, by and quote
    F->>R: product.yaml flow.frozen: version, manifest_sha256, decision, evidence_sha256
    F-->>S: envelope with next_actions
  end
```

## (d) Release

```mermaid
%%{init: {"theme": "neutral"}}%%
sequenceDiagram
  autonumber
  actor U as Designer
  participant H as Agent host
  participant S as MCP server, Phase 3
  participant F as Flow engine, Phase 2
  participant Rel as Release packaging, Phase 4
  participant E as Evidence service, on main
  participant R as Record store, on main

  S->>F: RELEASE gate, a single human gate
  F-->>S: packet: frozen version, revision to issue, contents, verification
  S-->>H: packet
  H->>U: ask, in chat
  U-->>H: explicit approval
  H->>S: flow.record_decision, channel chat
  F->>R: decision record: kind gate, status approved
  H->>S: release tool with REV and the frozen version
  S->>Rel: package REV from vN
  Rel->>R: read flow.frozen and the release decision
  Rel->>Rel: refuse unless flow.frozen names vN and its manifest_sha256
  Rel->>Rel: refuse unless the release decision is approved
  Rel->>E: read_built_version and assess on vN
  E-->>Rel: acceptance with evidence_sha256
  Rel->>Rel: refuse unless evidence_sha256 equals flow.frozen.evidence_sha256
  Rel->>Rel: refuse a product export that holds a context or tooling part
  Note over Rel: Open: the plan names no other refusal checks
  alt any refusal
    Rel-->>S: findings, and no package
  else every check passes
    Rel->>R: write the package under hw/releases/REV/: product.step AP242, product.glb, the documentation set
    Rel-->>S: envelope with artifacts and next_actions
  end
  S-->>H: result
```

## (e) Migrate

```mermaid
%%{init: {"theme": "neutral"}}%%
sequenceDiagram
  autonumber
  actor A as Person or agent at a shell
  participant CLI as benchhand record migrate, on main
  participant M as migrate and undo, on main
  participant T as Temporary copy of the migrated record
  participant O as hw/.benchhand-migrate.owner
  participant L as hw/.benchhand-migrate.lock
  participant B as Backup in .benchhand/migrate-backups/
  participant HW as hw/ files

  A->>CLI: benchhand record migrate HW
  CLI->>M: migrate(root)
  M->>HW: read record_version and every file the rules touch
  M->>M: refuse a frozen record, migrate.frozen_anchor, or an unsupported version
  M->>M: apply RULES per file, giving FileChange: rules and a unified diff
  M->>T: validate the migrated record in a new temporary directory
  M-->>CLI: Migration with status ready, refused or current
  CLI-->>A: diffs and findings, nothing written

  A->>CLI: benchhand record migrate --apply HW
  CLI->>M: migrate(root, apply=True)
  M->>L: check the lock
  M->>O: create with O_CREAT and O_EXCL, naming pid, host and start time, else migrate.locked
  M->>L: read it again: a held lock refuses a fresh apply, migrate.locked names --resume and --undo
  M->>L: write atomically, naming the new backup
  M->>T: plan again and validate the migrated copy
  M->>B: preimages and manifest.json with both sha256 values, synced and read back
  M->>B: publish COMPLETE atomically, holding the manifest sha256
  M->>HW: check no file was added or removed since the plan
  M->>HW: write each changed file: synced temp file, re-hash, rename, hw/product.yaml last
  alt every write succeeds
    M->>HW: sync every target directory, validate the record again
    M->>L: remove
    M-->>CLI: status applied, with the undo command
  else stopped after COMPLETE
    M-->>CLI: status failed, the lock stays
  end
  M->>O: remove

  opt the next run after a stopped apply
    A->>CLI: benchhand record migrate --apply --resume HW
    CLI->>M: migrate(root, apply=True, resume=True)
    alt the backup is COMPLETE
      M->>B: sync COMPLETE again and reuse the backup
      M->>HW: each file must hold its preimage or its migrated bytes, else migrate.changed_meanwhile
      M->>HW: write the rest, giving the bytes of a clean run
    else the backup is unfinished
      M->>B: mark it ABANDONED and keep it, migrate.backup_abandoned
      M->>B: make a new backup beside it and apply as a fresh run
    end
  end

  A->>CLI: benchhand record migrate --undo BACKUP
  CLI->>M: undo(backup)
  M->>O: take ownership, as apply does
  M->>B: refuse without a valid COMPLETE, migrate.backup_incomplete, or with files that don't match the manifest, migrate.backup_unusable
  M->>L: refuse a lock that names another backup, else point the lock at this backup
  M->>HW: put each preimage back where the file holds the migrated bytes, hw/product.yaml first
  M->>M: leave a file something else changed, migrate.undo_skipped
  M->>L: remove
  M->>O: remove
  M-->>CLI: status undone
  Note over A,HW: Every backup stays until someone deletes it by hand under .benchhand/migrate-backups/
```

## Legend

- Each participant's name carries its status: "on main", "Phase N" (planned) or "open phase" (named in the plan, with no phase in its Steps). See the [legend](README.md#legend).
- A solid arrow is a call or a message, and a dashed arrow is its reply. An open arrowhead is a notification.
- **Open: 30 s or 50 s.** ADR-0018 sends work over about 30 s to a job handle; plan section 11 and provider-protocol section 8 say about 50 s. The diagrams follow ADR-0018, the later decision.
- **Open: provider request to job.** The plan says the server manages provider workers and jobs, and that `$/progress` feeds job-handle status. `JobService` runs a command under a supervisor, and no document says how a provider request becomes such a job.
- **Open: the cancel tool.** The plan names `jobs.start`, `jobs.status` and `jobs.result`, and `jobs.*` for Phase 3; no cancel tool name.
- **Open: release refusals.** The plan names refusal checks and the acceptance digest against the freeze, and section 12a names the context and tooling refusal. It doesn't list the rest.
- **Open: migrate entry point.** The plan's CLI list (D1) has no `record migrate`, and no MCP tool for migration is named. `main` has the CLI subcommand.
- None of these are in the plan's [Open questions](../design-plan.md#open-questions).

## Sources

- (a) One tool call:
  - `docs/design-plan.md`: [1. Layered architecture](../design-plan.md#1-layered-architecture) (middleware order), [5. Flow engine and rules (D14)](../design-plan.md#5-flow-engine-and-rules-d14) ("The engine refuses out-of-order transitions with a reason and the next action"), [6a. Contracts](../design-plan.md#6a-contracts-generated-and-enforced-d17) ("Runtime, both directions"; the envelope fields), [9. Guidance from the server](../design-plan.md#9-guidance-from-the-server-minimal-steering-d11) (`next_actions`), [12. Build API (D7)](../design-plan.md#12-build-api-d7) (`model.build`).
  - `docs/contract/provider-protocol.md`: [1. Transport](../contract/provider-protocol.md#1-transport), [5. Notifications from the provider](../contract/provider-protocol.md#5-notifications-from-the-provider), [6. Artifacts and paths](../contract/provider-protocol.md#6-artifacts-and-paths), [8. Requests in flight, cancellation and timeouts](../contract/provider-protocol.md#8-requests-in-flight-cancellation-and-timeouts).
  - ADRs: [0011](../adr/0011-guidance-from-server.md), [0013](../adr/0013-provider-protocol.md), [0014](../adr/0014-flow-rules-cel.md), [0017](../adr/0017-contracts.md), [0018](../adr/0018-baseline-and-no-forms.md), each under "Decision".
  - Code on `main`: `benchhand_core/record/store.py` (`save_document`, `check_document`).
- (b) Long job:
  - Code on `main`: `benchhand_core/jobs/service.py` (`JobService`, `JobSpec`), `jobs/process.py` (`SupervisedProcess`), `jobs/supervisor.py`, `jobs/store.py` (`RecordStore`), `contracts/jobs/job.tsp` (`JobRecord`, `JobHandle`, `JobStatus`).
  - `docs/design-plan.md`: [11. Adaptive interaction layer (D8)](../design-plan.md#11-adaptive-interaction-layer-d8) (the long-jobs row, the tasks adapter behind a flag), [Steps (phased)](../design-plan.md#steps-phased) (Phases 3 and 5); [Decisions](../design-plan.md#decisions), D4.
  - `docs/contract/provider-protocol.md`: [5. Notifications from the provider](../contract/provider-protocol.md#5-notifications-from-the-provider).
- (c) Evidence and freeze:
  - `docs/design-plan.md`: [Steps (phased)](../design-plan.md#steps-phased), Phase 2 (version snapshots, seal and verify; decision records) and Phase 4 (providers); [11. Adaptive interaction layer (D8)](../design-plan.md#11-adaptive-interaction-layer-d8) (the human-gate row, `flow.record_decision`, "An empty or declined answer means no answer").
  - `contracts/record/product.tsp` (`flow.frozen`) and `contracts/record/decision.tsp` (gate decisions), on `main`.
  - Code on `main`: `packages/benchhand-core/src/benchhand_core/record/evidence/` (`reader.py` `read_built_version`, `assess.py` `assess`, `digest.py` `acceptance_digest`).
  - Prototype `benchhand/benchhand` at `release.toml` `reference_commit` `412b5d9`: [`skills/cad-flow/references/flow.md` "Gate control"](https://github.com/benchhand/benchhand/blob/412b5d9ae2faa420f909c1f50cc98a696651539f/skills/cad-flow/references/flow.md#gate-control) (DESIGN freeze is a single human gate).
- (d) Release:
  - `docs/design-plan.md`: [Steps (phased)](../design-plan.md#steps-phased), Phase 4 ("Release packaging (`hw/releases/<REV>/`, refusal checks and the acceptance digest against the freeze)"); [12a. Documentation set](../design-plan.md#12a-documentation-set-annotations-groups-materials-and-finish) (STEP AP242 as the primary deliverable, `product.step` and `product.glb`, the context and tooling refusal).
  - Prototype `skills/cad-flow/references/flow.md` "Gate control" at `412b5d9`: RELEASE is a single human gate, and a release decision that isn't approved is refused.
- (e) Migrate:
  - `docs/contract/record-migration.md`: [Dry run and apply](../contract/record-migration.md#dry-run-and-apply), on `main`.
  - Code on `main`: `packages/benchhand-core/src/benchhand_core/record/migrate/` (`service.py` `migrate`, `undo`, `MigrationStatus`; `recovery.py` `acquire_owner`, `write_lock`, `write_backup`, `abandon`) and `packages/benchhand/src/benchhand/cli.py` (`record migrate`).
  - `docs/design-plan.md`: [Steps (phased)](../design-plan.md#steps-phased), Phase 1 ("typed reads and writes, validate, migrate and evidence").
  - `docs/phases/phase-0-1.md`: [Not built, which the plan puts in Phase 1](../phases/phase-0-1.md#not-built-which-the-plan-puts-in-phase-1).
