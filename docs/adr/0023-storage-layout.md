# ADR-0023: The project storage layout

Status: accepted 2026-11-27, owner-decided. Source: the owner's answers of 2026-11-27 to the storage-layout study (bead `bhn-7pg`), which decide D-37 of the [CAD-libraries decision record](../design/cad-libraries-2026-11-27.md). It adds to sections 12a and Steps of [the plan](../design-plan.md), and to gain 5 of [the edit-loop design note](../design/edit-loop-performance.md). The code still uses `hw/` until bead `bhn-aef` renames it, and the per-job JSON store until bead `bhn-5qa` replaces it.

## Context

The prototype keeps the authored record and everything the machine writes in one `hw/` tree: versions, checks, drawings, renders, releases and the `hw/.cad/` caches. benchhand-next on `main` adds `.benchhand/runs/` and `.benchhand/migrate-backups/`. The study measured the prototype's `examples/lamp-arm` after 3 builds, 3 check runs, 1 drawing and 1 work unit:

- **The authored record is small.** It is 36 files and 184 KB of the project's 28 MB of unique bytes. The machine wrote 421 files.
- **Agents pay for the mix.** A listing of the whole tree is 25.6 KB of paths, against 0.9 KB for the authored files. `grep -r LMP-0002` returns 364 KB over the tree and 5 KB over the authored files.
- **Sealed evidence stays out of git in the prototype.** Its project template ignores `versions/`, `checks/` and `releases/`, so a fresh clone can't verify a freeze. Tracking the sealed text grew the git pack by 56, 23 and 6 KiB for v1, v2 and v3.
- **Plain git packs the binaries well.** With the binaries tracked too, the pack grew by 2,947, 24 and 31 KiB after `git gc --aggressive`. Git LFS stores every version whole, about 4.4 MB per one-part edit (estimate).
- **A rebuilt STEP differs only in its header.** A clean rebuild of v3 gave identical `DATA;` sections in all 19 STEP files. Each file differed in its `FILE_NAME` timestamp, and so did every file that embeds a STEP sha256. STL, GLB and the record snapshot were byte-identical.
- **A sealed path is part of the seal.** The acceptance digest maps `hw/<path>` to sha256 (`record/evidence/digest.py`), and a bundle manifest names its own path. Moving a sealed bundle breaks its seal.
- **SQLite beats one file per entry for small derived data.** With 10,000 facts, a fresh process opened the store and read 55 facts in 3.1 to 4.7 ms with SQLite in WAL mode, against 36 to 51 ms with one JSON file per fact. A durable write took 56 to 66 µs, against 1,844 to 2,712 µs. Four writer processes made 10,000 commits in 972 ms with no busy retries, and a SIGKILL during a write left the file intact. Python and Node both read it with their built-in modules. A check takes 5 to 6 s, so the speed gain of the fact cache comes from the cache itself, not from its backend.

The measurements were on one Apple M4 Pro with APFS. STEP byte equality across platforms, WAL on container bind mounts and the file timings on Linux weren't measured.

## Decision

1. **Three top-level zones.**
   - **`design/`** holds only what a person or the agent writes and the user reviews, as text in git, including each part's `rev`. It replaces `hw/` for the authored record: the product, requirements, interfaces, assembly, policy, the ledgers, `parts/<PN>/`, manufacturing, decisions, the document templates and the human notes.
   - **`.benchhand/`** holds the machine data, which nobody edits by hand:
     - `sealed/{versions,checks,analysis,motion,drawings,renders,captures,concept,docsets}/`, the immutable bundles that a freeze and a digest name;
     - `objects/sha256/`, the content-addressed binaries (STEP, STL, 3MF, GLB, PNG, PDF, SVG, FCStd), hard-linked into the sealed bundles;
     - `state.sqlite`, the state database;
     - `work/<unit>/`, the scratch copy of a parallel work unit (the prototype's `.cad-work/`);
     - `logs/`;
     - `migrate-backups/`.
   - **`releases/<REV>/`** is a visible top-level folder for the deliverables a user hands over. Its `manifest.json` seals it and names its source version `vN`.
2. **Versions, revisions and releases.** A version `vN` is a sealed snapshot of the whole record and its build outputs, under `.benchhand/sealed/versions/<V>/`. A part's `rev` is authored in `design/`. A release `<REV>` packages one frozen version into `releases/<REV>/`, and its manifest names that version.
3. **Managed ignores.** benchhand writes and manages `.benchhand/.gitignore` and `.benchhand/.gitattributes`:
   - everything under `.benchhand/` is ignored by default, so a new machine-local file needs no new rule;
   - the sealed text (`*.json`, `*.yaml`, `*.csv` and `*.md` under `sealed/`) is un-ignored, so it is tracked in git;
   - the sealed binaries follow the project's storage choice (decision 4);
   - the sealed folders are marked `linguist-generated -diff`, so they collapse in review;
   - no rule matches anything in `design/`;
   - benchhand writes only these two files: the user's top-level `.gitignore` stays as the user wrote it.
4. **Sealed text is tracked in git by default.** The sealed binaries have three storage choices:
   - ignored, the default: the text manifest in git carries the seal, and the bytes stay in the object store;
   - git LFS;
   - plain git, which is new, for small projects.
5. **The state database is `.benchhand/state.sqlite`.** It is one SQLite file in WAL mode. `BENCHHAND_STATE_DIR` moves it out of the project, for example off a sync folder or a container bind mount. LMDB isn't used.
   - **Rule: nothing in it is the only copy of anything that matters.** Every table is either derivable, rebuilt by re-running, or disposable, where losing it costs only convenience. Deleting the file costs time, never correctness.
   - **Its tables:**

     | Table | Holds | Kind |
     |---|---|---|
     | `facts` | per-part facts keyed by their input hashes and the producing code digest (edit-loop gain 1); the fingerprint memo; the interference pair cache; the checkpoints of long jobs | derivable |
     | `jobs` | each job's start, finish and failure, with its arguments, their digest and its idempotency key, under a UNIQUE constraint on the key | disposable |
     | `search` | the FTS5 indexes for `standards.search`, `parts.search` and `docs.get` | derivable |
     | `renders` | the render cache index: GLB sha256, camera, pose, size and renderer digest to an object sha256 | derivable |
     | `objects_index` | each object's sha256, size, media type, the versions that use it and its last use, for the object store's garbage collection | derivable |
     | `preview` | each project's preview-host port and token, for stable viewer URLs | disposable |
     | `work_units` | the active parallel work units and their reserved record-ID blocks (RULE-37) | derivable |
     | `leases` | the run guard: which process holds which version or build, with a heartbeat, in place of lock and PID files | disposable |

   - The fingerprint memo maps a file's path, size, modification time and inode to its sha256, to save rehashing within a session. Such a key can miss a same-size rewrite (IR-191), so a seal, a freeze and a release always hash the bytes.
6. **What stays files:**
   - the object store's bytes;
   - the logs, which stream and can be read with `tail`;
   - everything sealed or reviewed: the manifests, the check bundles, the decisions and `design/`.
7. **Jobs and their recovery.** This replaces the per-job JSON files under `.benchhand/runs/` on `main`.
   - A job's state lives in memory while the server runs, and jobs end with the session (edit-loop Q2).
   - The `jobs` table journals each job. The same idempotency key with the same inputs replays the job; the same key with different inputs is refused as a conflict.
   - After a restart, `jobs.status` reads the `jobs` table. A job that started and has no finish or failure answers `interrupted`, with the exact re-run call as its next action.
   - Long jobs such as sweeps and FEA checkpoint their finished pairs, samples and cases into `facts`, so a re-run resumes cheaply.
   - On start, a stale `.partial-<PID>` staging folder whose process is gone is removed.
   - A job's log is a file under `.benchhand/logs/`.
8. **The object store stays per project.** A per-user store shared across projects isn't adopted at this decision. The object store sits inside the project, so copying the project folder copies everything and hard links work.
9. **D-37: generated documents.** A docset goes to `.benchhand/sealed/docsets/<V>/<S>/`.
   - Its manifest, recipe, UNKNOWN list and input JSON are sealed text in git. Its PDFs and PNGs go into the object store.
   - A docset stays outside the acceptance digest. The release manifest covers it.
   - `design/docs/` holds human notes only. Generated output never goes there.
10. **Prototype history is read where it lies.** The prototype's sealed history under `hw/` (`hw/versions/`, `hw/checks/` and the other bundle folders) is never moved, because a move breaks its seal ([record migration](../contract/record-migration.md), "Sealed history"). This applies only with the `record-migration` feature flag on (bead `bhn-ayi`).
11. **Versions are sealed on the main line only.** A work unit builds in `.benchhand/work/<unit>/` and delivers its parts back. A version-label collision at a merge, two branches that each sealed the same `vN`, is refused.
12. **The STEP `FILE_NAME` timestamp is fixed in kernel export, in Phase 4.** A rebuilt file then matches its seal byte for byte. The fact keys still hash only the STEP data section (edit-loop Q6).

## Consequences

- **The layout lands in Phase 2,** before the `version-snapshots` spec and the first v3 seal. Afterwards every sealed path would have to stay readable at two places. Bead `bhn-aef` renames `hw/` to `design/` across code, contracts, tests, fixtures and docs; until it lands, the code and the specs write `hw/`.
- **Phase 2 work:**
  - version snapshots write `.benchhand/sealed/versions/<V>/` and their binaries into the object store;
  - the evidence reader accepts `.benchhand/sealed/**` and treats the rest of `.benchhand/` as scratch. On `main`, a bundle path must start with `hw/` (`record/evidence/reader.py`, line 150);
  - the bundle manifest's `path` becomes the project-relative sealed path, a contract change under ADR-0017;
  - the managed ignores replace the prototype's `hw/.gitignore` storage block, which settles the managed-block part of IR-012;
  - `state.sqlite` with its `jobs`, `objects_index` and `leases` tables, and the job journal of bead `bhn-5qa`, which updates `contracts/jobs/`.
- **Later tables land with the capability that fills them.** `facts` comes with the fact cache in Phase 4, and `renders` with render output in Phase 4. `search` comes with the tools it serves, `preview` with the preview host in Phase 5, and `work_units` with the scratch workspaces.
- **Each work unit's folder records its reserved ID block,** so that the `work_units` table stays derivable.
- **A clone without the binaries** can check the record's internal consistency, but not the geometry, until it fetches or rebuilds the bytes. A freeze or a release needs the bytes present, because the acceptance digest hashes every cited artifact on disk.
- **User-supplied sources** such as vendor STEP and datasheet PDFs are authored, in the digest and not rebuildable. They stay in `design/`, in git.
- **`releases/` sits outside `.benchhand/`,** so the managed ignores don't cover it, and the user's own git rules decide whether it is committed.
- **A SQLite file on a sync folder** can be torn by the sync client. `BENCHHAND_STATE_DIR` is the remedy. Because nothing in the file matters alone, a torn or deleted database costs a rebuild only. How one directory holds the databases of several projects is settled when the override is built.
- **Version snapshots must know the main line,** and validation must detect a label collision after a merge. The `version-snapshots` spec designs both.
- **Two open items stay open:** which component moves a provider's verified artifacts into the object store (the catalogue's `artifact-placement`), and where a finished job's result is kept once the per-job files go (bead `bhn-5qa`, with its contract change).
- **No accepted ADR needs an amendment.** ADR-0019 fingerprints items the way the evidence service fingerprints its inputs, and this layout keeps that.
