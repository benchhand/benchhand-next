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
  participant P as Provider host, open phase
  participant K as Provider, e.g. kernel-build123d, Phase 4

  H->>S: tools/call model.build with a version reference
  S->>M: call through validation, policy, audit, provenance, cache, telemetry
  M->>M: validate the input against the tool's inputSchema
  Note over M: Open: the sources put CEL guards on flow transitions only.<br/>Whether a tool call like model.build is checked against flow.stage isn't stated.
  M->>P: run the kernel/build hook
  P->>K: kernel/build with projectRoot and outDir, JSON-RPC 2.0, Content-Length framing
  K--)P: $/progress with id, fraction and message
  K-->>P: result with artifacts: path, mediaType, role, bytes, sha256
  P->>P: check each artifact is under outDir and matches its size and sha256, else provider-output-invalid
  P->>P: move the accepted artifacts into hw/: the host is the only writer of provider output
  Note over P: Open: which component places the artifacts in hw/.<br/>The typed record store reads and writes YAML, CSV and decisions only.
  P-->>M: findings and artifacts
  M-->>S: envelope: status, findings, artifacts, next_actions
  S->>S: validate the output against the tool's outputSchema
  S-->>H: structuredContent holding the envelope
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
    alt the record is already terminal
      J-->>S: JobHandle with its final status, unchanged
    else a live job this service owns
      alt its supervisor still runs
        J->>Sup: stop request
        Sup->>C: TERM to the group, KILL after the grace period
        J->>St: status cancelled
        J-->>S: JobHandle: status cancelled
      else its supervisor exited, not yet reaped
        J->>St: status succeeded for exit 0, else failed
        J-->>S: JobHandle: the status it wrote, succeeded or failed
      end
    else another process owns it, its owner is gone but its supervisor runs, or another host recorded it
      J-->>S: JobError, and nothing is signalled
    else nothing runs it any more
      J->>St: status cancelled
      J-->>S: JobHandle: status cancelled
    end
  else the command ends
    opt the command writes its result
      C->>C: write the result file at BENCHHAND_JOB_RESULT
    end
    C-->>Sup: exit status
    Sup->>Sup: kill the whole group
    H->>S: jobs.result(job_id)
    S->>J: result(job_id)
    J->>J: reap: exit 0 gives succeeded, any other exit failed
    alt succeeded, and the result file exists
      J-->>S: path of the result file
    else failed, cancelled, or succeeded without writing the result
      J-->>S: JobNotSucceeded
    end
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
  S->>V: publish sealed check packets, bound to the manifest sha256 of vN
  Note over S,V: Planned orchestration, Phases 2 and 4: the sources don't specify these calls exactly
  Note over S,E: Open: which tool runs the assessment isn't stated
  rect rgb(232, 245, 233)
    S->>R: load_record(root): the caller reads the current record
    S->>E: read_built_version(root, record, vN, *, shipped_guidelines)
    E->>E: refuse a linked path, then check vN has a manifest, then verify the seal of hw/versions/vN/
    alt vN isn't built, is reached through a link, or fails its seal
      E-->>S: BuiltVersionError, before any packet or snapshot read
    else built and sealed
      E->>E: read its bound packets in hw/checks/vN/, each seal verified on the bytes on disk
      E->>E: upgrade a record_version 2 packet in memory with migrate's rules, nothing written back
      alt a packet still breaks the v3 contract after the upgrade
        E->>E: finding packet.unupgradable, the packet counts as nothing
      end
      E->>R: read the snapshot documents vN was built from, a record_version 2 snapshot upgraded in memory the same way
      alt a snapshot document can't be upgraded
        E->>E: build staleness NotComputed
      end
      E-->>S: BuiltVersion
      S->>E: assess(record, built, today)
      E->>E: expected obligations, sealed packets, evidence ledger, waivers
      alt a path or dependency refusal among the findings
        E->>E: acceptance refused, with a reason
      else the acceptance inventory can't be read, e.g. a linked source file
        E->>E: acceptance refused, with a reason
      else
        E->>E: acceptance formed: the inventory hashes the files on disk, and its acceptance_digest follows
      end
      E-->>S: EvidenceAssessment: statuses, facets, findings, complete, acceptance
    end
  end
  alt BuiltVersionError, or acceptance refused
    Note over S,E: On main this ends here: refused, no evidence_sha256
    Note over S,F: Open: what the freeze does next. product.yaml allows flow.frozen without evidence_sha256, and a release refuses that freeze
  else acceptance formed, with evidence_sha256
    S->>F: design_freeze gate, a single human gate
    F-->>S: gate packet, next action: ask the user
    S-->>H: packet and preview URL
    H->>U: present the packet and ask, in chat
    U-->>H: answer
    H->>S: flow.transition, channel chat, the user's words quoted
    alt empty, declined or cancelled
      F-->>S: no answer, so the gate stays open
    else explicit approval
      F->>R: decision record: kind gate, status approved, approval with channel, by and quote
      F->>R: product.yaml flow.frozen: version, manifest_sha256, decision, evidence_sha256
      F-->>S: envelope with next_actions
    end
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
  H->>S: flow.transition, channel chat
  F->>R: decision record: kind gate, status approved
  H->>S: release tool with REV and the frozen version
  S->>Rel: package REV from vN
  Rel->>R: read flow.frozen and the release decision, and load the current record
  Rel->>Rel: refuse unless flow.frozen names vN and its manifest_sha256
  Rel->>Rel: refuse unless the release decision is approved
  rect rgb(232, 245, 233)
    Rel->>E: read_built_version(root, record, vN, *, shipped_guidelines), then assess
    E-->>Rel: BuiltVersionError, or an EvidenceAssessment
  end
  Rel->>Rel: refuse on BuiltVersionError, or an acceptance refused with no evidence_sha256
  Rel->>Rel: refuse unless the formed evidence_sha256 equals flow.frozen.evidence_sha256
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
  M->>HW: read record_version: refuse a linked hw/ or product.yaml, or record.version_unsupported
  M->>L: an owner file or a held lock refuses the dry run too, migrate.locked
  alt record_version 3
    M->>HW: validate
    M-->>CLI: status current
  else record_version 1 or 2
    M->>M: refuse a frozen record, migrate.frozen_anchor
    M->>M: apply RULES per file, giving FileChange: rules and a unified diff
    M->>T: validate the migrated record in a new temporary directory
    M-->>CLI: Migration with status ready or refused
  end
  CLI-->>A: diffs and findings, nothing written

  A->>CLI: benchhand record migrate --apply HW
  CLI->>M: migrate(root, apply=True)
  M->>HW: read record_version first, as the dry run does
  alt record_version 3, without --resume
    M->>L: an owner file or a held lock refuses, migrate.locked
    M->>HW: validate
    M-->>CLI: status current: no ownership taken, no backup, nothing written
  else record_version 1 or 2
    M->>L: read the lock before ownership: a held lock refuses a fresh apply,<br/>migrate.locked names --resume and --undo
    M->>O: create with O_CREAT and O_EXCL, naming pid, host and start time,<br/>else migrate.locked naming the owner
    M->>L: read it again under ownership, then write it atomically, naming the new backup
    M->>T: plan again and validate the migrated copy
    M->>B: preimages and manifest.json with both sha256 values, synced and read back
    alt the backup can't be written
      M->>L: remove
      M-->>CLI: status refused, migrate.backup_failed, nothing in hw/ changed
    else
      M->>B: publish COMPLETE atomically, holding the manifest sha256
      M->>HW: check no file was added or removed since the plan
      loop each changed file, hw/product.yaml last
        M->>HW: synced temp file, re-hash, rename, sync its directory
      end
      alt a file changed meanwhile, or a write or its rename fails
        M-->>CLI: status failed, migrate.changed_meanwhile or migrate.write_failed,<br/>the loop stops, and the lock stays
      else the directory sync right after one rename fails
        M-->>CLI: status failed, migrate.not_durable for that file,<br/>the loop stops, and the lock stays
      else every file written
        M->>HW: sync the directory of every target again
        alt the sync fails
          M-->>CLI: status failed, migrate.not_durable, and the lock stays
        else synced
          M->>HW: validate the record again
          alt it doesn't validate
            M-->>CLI: status failed, migrate.invalid_result naming --undo, and the lock stays
          else it validates
            M->>L: remove
            M-->>CLI: status applied, with the undo command
          end
        end
      end
    end
    M->>O: remove, whatever the result
  end
  Note over M,O: A killed run leaves its owner file: every later run gets migrate.locked<br/>naming that owner until someone deletes the file by hand

  opt the next run after a stopped apply
    A->>CLI: benchhand record migrate --apply --resume HW
    CLI->>M: migrate(root, apply=True, resume=True)
    M->>L: read the lock before ownership: no lock refuses, migrate.not_interrupted
    M->>O: take ownership, as apply does, and read the lock again
    alt the backup is COMPLETE
      M->>B: sync COMPLETE again and reuse the backup
      M->>HW: each file must hold its preimage or its migrated bytes, else migrate.changed_meanwhile
      M->>HW: write the rest, giving the bytes of a clean run, and end as apply does
    else unfinished, and the record is already record_version 3
      M->>B: mark it ABANDONED and keep it, migrate.backup_abandoned
      M->>L: remove, with no new backup
      M-->>CLI: status current
    else unfinished
      M->>B: mark it ABANDONED and keep it, migrate.backup_abandoned
      M->>B: make a new backup beside it and apply as a fresh run
    end
    M->>O: remove
  end

  A->>CLI: benchhand record migrate --undo BACKUP
  CLI->>M: undo(backup)
  M->>B: refuse a backup outside .benchhand/migrate-backups/ or no directory, migrate.backup_unusable
  M->>L: read the lock before ownership: a lock naming another backup refuses, migrate.locked
  M->>O: take ownership, as apply does
  M->>B: refuse without a valid COMPLETE, migrate.backup_incomplete,<br/>or with files that don't match the manifest, migrate.backup_unusable
  M->>L: read it again, and with no lock, point the lock at this backup
  M->>HW: put each preimage back where the file holds the migrated bytes, hw/product.yaml first
  M->>M: leave a file something else changed, migrate.undo_skipped
  alt a restore write or the directory sync fails
    M-->>CLI: status failed, the lock stays, and the same --undo finishes it
  else restored and synced
    M->>L: remove
    M-->>CLI: status undone
  end
  M->>O: remove, whatever the result
  Note over A,HW: Every backup stays until someone deletes it by hand under .benchhand/migrate-backups/
```

## Legend

- Each participant's name carries its status: "on main", "Phase N" (planned) or "open phase" (named in the plan, with no phase in its Steps). See the [legend](README.md#legend).
- A solid arrow is a call or a message, and a dashed arrow is its reply. An open arrowhead is a notification.
- Green-shaded steps in (c) and (d) are the read-only evidence seam on `main`: the caller supplies the current record, and the evidence service reads the built version and assesses it. The steps around them are planned orchestration, whose exact calls Phases 2 and 4 don't specify.
- **Settled: tool calls and flow.stage.** Plan section 5 puts CEL guards on transitions. The owner decided on 2026-11-28 that building and checking run at any stage, and only a tool that seals, freezes or releases is checked against the stage (`docs/contract/flow.md:73`).
- **Open: artifact placement.** The host verifies a provider's artifacts and moves them into `hw/`. No source says which component writes them; the typed record store handles YAML, CSV and decisions only.
- **Settled: a freeze without a digest.** `read_built_version` or `assess` can refuse, and on `main` that path ends at a refused acceptance with no `evidence_sha256`. The owner decided on 2026-11-28 that a freeze requires `evidence_sha256` and is refused when the assessment refuses (`docs/contract/flow.md:74`).
- **Settled: 30 s.** Work that can run past about 30 s returns a job handle (ADR-0018). Plan section 11 and provider-protocol section 8 said about 50 s until 2026-11-26 and now follow ADR-0018.
- **Open: provider request to job.** The plan says the server manages provider workers and jobs, and that `$/progress` feeds job-handle status. `JobService` runs a command under a supervisor, and no document says how a provider request becomes such a job.
- **Open: the cancel tool.** The plan names `jobs.start`, `jobs.status` and `jobs.result`, and `jobs.*` for Phase 3; no cancel tool name.
- **Open: release refusals.** The plan names refusal checks and the acceptance digest against the freeze, and section 12a names the context and tooling refusal. It doesn't list the rest.
- **Open: migrate entry point.** The plan's CLI list (D1) has no `record migrate`, and no MCP tool for migration is named. `main` has the CLI subcommand.
- None of these are in the plan's [Open questions](../design-plan.md#open-questions).

## Sources

- (a) One tool call:
  - `docs/design-plan.md`: [1. Layered architecture](../design-plan.md#1-layered-architecture) (middleware order), [5. Flow engine and rules (D14)](../design-plan.md#5-flow-engine-and-rules-d14) (CEL guards on the edges and `requires` on the gates, so on transitions), [6a. Contracts](../design-plan.md#6a-contracts-generated-and-enforced-d17) ("Runtime, both directions"; the envelope fields), [9. Guidance from the server](../design-plan.md#9-guidance-from-the-server-minimal-steering-d11) (`next_actions`), [12. Build API (D7)](../design-plan.md#12-build-api-d7) (`model.build`).
  - `docs/contract/provider-protocol.md`: [1. Transport](../contract/provider-protocol.md#1-transport), [5. Notifications from the provider](../contract/provider-protocol.md#5-notifications-from-the-provider), [6. Artifacts and paths](../contract/provider-protocol.md#6-artifacts-and-paths), [8. Requests in flight, cancellation and timeouts](../contract/provider-protocol.md#8-requests-in-flight-cancellation-and-timeouts).
  - ADRs: [0011](../adr/0011-guidance-from-server.md), [0013](../adr/0013-provider-protocol.md), [0014](../adr/0014-flow-rules-cel.md), [0017](../adr/0017-contracts.md), [0018](../adr/0018-baseline-and-no-forms.md), each under "Decision".
  - Code on `main`: `benchhand_core/record/store.py` (`save_document`, `save_decision`: typed YAML, CSV and decision documents only).
- (b) Long job:
  - Code on `main`: `benchhand_core/jobs/service.py` (`JobService`, `JobSpec`; `cancel` and `_cancel_unowned` for the cancellation branches, `result` and `handle_of` for the optional result), `jobs/process.py` (`SupervisedProcess`), `jobs/supervisor.py`, `jobs/store.py` (`RecordStore`), `contracts/jobs/job.tsp` (`JobRecord`, `JobHandle`, `JobStatus`).
  - `docs/design-plan.md`: [11. Adaptive interaction layer (D8)](../design-plan.md#11-adaptive-interaction-layer-d8) (the long-jobs row, the tasks adapter behind a flag), [Steps (phased)](../design-plan.md#steps-phased) (Phases 3 and 5); [Decisions](../design-plan.md#decisions), D4.
  - `docs/contract/provider-protocol.md`: [5. Notifications from the provider](../contract/provider-protocol.md#5-notifications-from-the-provider).
- (c) Evidence and freeze:
  - `docs/design-plan.md`: [Steps (phased)](../design-plan.md#steps-phased), Phase 2 (version snapshots, seal and verify; decision records) and Phase 4 (providers); [11. Adaptive interaction layer (D8)](../design-plan.md#11-adaptive-interaction-layer-d8) (the human-gate row, `flow.record_decision`, "An empty or declined answer means no answer").
  - `contracts/record/product.tsp` (`flow.frozen`) and `contracts/record/decision.tsp` (gate decisions), on `main`.
  - Code on `main`: `packages/benchhand-core/src/benchhand_core/record/evidence/`. `reader.py` `read_built_version` only reads, and its `shipped_guidelines` is keyword-only. `assess.py` `_acceptance` can refuse without a digest. `digest.py` holds `acceptance_digest`, and `record/store.py` holds `load_record` and `read_document`.
  - Prototype `benchhand/benchhand` at `release.toml` `reference_commit` `412b5d9`: [`skills/cad-flow/references/flow.md` "Gate control"](https://github.com/benchhand/benchhand/blob/412b5d9ae2faa420f909c1f50cc98a696651539f/skills/cad-flow/references/flow.md#gate-control) (DESIGN freeze is a single human gate).
- (d) Release:
  - `docs/design-plan.md`: [Steps (phased)](../design-plan.md#steps-phased), Phase 4 ("Release packaging (`hw/releases/<REV>/`, refusal checks and the acceptance digest against the freeze)"); [12a. Documentation set](../design-plan.md#12a-documentation-set-annotations-groups-materials-and-finish) (STEP AP242 as the primary deliverable, `product.step` and `product.glb`, the context and tooling refusal).
  - Prototype `skills/cad-flow/references/flow.md` "Gate control" at `412b5d9`: RELEASE is a single human gate, and a release decision that isn't approved is refused.
- (e) Migrate:
  - `docs/contract/record-migration.md`: [Dry run and apply](../contract/record-migration.md#dry-run-and-apply), on `main`: the ownership and lock order, the backup, the stopped apply, resume, undo, and "if that process was killed, delete the owner file by hand".
  - Code on `main`: `packages/benchhand-core/src/benchhand_core/record/migrate/` (`service.py` `migrate`, `_lock_state`, `_run_for`, `_owned_apply`, `_write_all`, `_stopped`, `_current`, `undo`, `_owned_undo`, `_restore`, `MigrationStatus`; `recovery.py` `acquire_owner`, `release_owner`, `write_lock`, `write_backup`, `abandon`) and `packages/benchhand/src/benchhand/cli.py` (`record migrate`).
  - `docs/design-plan.md`: [Steps (phased)](../design-plan.md#steps-phased), Phase 1 ("typed reads and writes, validate, migrate and evidence").
  - `docs/phases/phase-0-1.md`: [Not built, which the plan puts in Phase 1](../phases/phase-0-1.md#not-built-which-the-plan-puts-in-phase-1).
