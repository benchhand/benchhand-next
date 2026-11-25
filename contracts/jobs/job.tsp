import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/jobs/job/")
namespace Jobs.Job;

/** A long-running job of the job service. JobRecord is the run record kept at <project>/.benchhand/runs/<jobId>.json; JobHandle is what jobs.start, jobs.status and jobs.result return to the agent. */
@summary("benchhand job")
@id("https://benchhand.github.io/benchhand/contracts/jobs/job.schema.json")
@oneOf
@extension("x-version", "1.0.0")
union Job {
  JobRecord,
  JobHandle,
}

@pattern("^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
scalar JobId extends string;

/** What the job does, named by whoever starts it, for example collision/sweep. */
@pattern("^[a-z][a-z0-9./-]{0,63}$")
scalar JobKind extends string;

/** queued: recorded, process not started. running. succeeded: the process exited 0. failed: it exited otherwise. cancelled: cancellation stopped it. */
union JobStatus {
  "queued",
  "running",
  "succeeded",
  "failed",
  "cancelled",
}

/** The last progress the job reported: the same fraction and message as a provider $/progress notification. Both are null until the first report. */
model JobProgress {
  @minValue(0)
  @maxValue(1)
  fraction: float64 | null;

  @maxLength(500)
  message: string | null;
}

/** UTC, RFC 3339, with an uppercase T and Z: the validators of each language disagree on a lowercase t or z, so the pattern refuses them. */
@format("date-time")
@pattern("^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\\.[0-9]+)?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])$")
scalar Timestamp extends string;

@oneOf
union OptionalTimestamp {
  Timestamp,
  null,
}

/** A process id with its start identity. The kernel reuses ids, so a pid proves nothing once its process is gone: the process runs only while some process has that pid and that identity. On Linux the identity is the boot id and the start time, elsewhere ps lstart. */
model ProcessIdentity {
  @minValue(1)
  pid: integer;

  @minLength(1)
  identity: string;
}

/** The job's exit status. A negative value is the signal that ended it. Null until it ends. */
union ExitCode {
  integer,
  null,
}

model JobRecord {
  jobId: JobId;
  kind: JobKind;
  status: JobStatus;
  progress: JobProgress;

  @minItems(1)
  argv: string[];

  cwd: string;

  /** The host the job runs on. A record of another host cannot be checked. */
  host: string;

  /** The process of the job service that started the job. It reaps the job and writes its final status. */
  owner: ProcessIdentity;

  /** The job's supervisor: it starts the command in a process group of its own, ends that group when the command ends or its owner does, and exits with the command's status. Null while queued. */
  @oneOf
  process: ProcessIdentity | null;

  /** Where the job is to write its result. Absolute. */
  resultPath: string;

  /** The job's standard output and error. Absolute. */
  logPath: string;

  exitCode: ExitCode;
  error: string | null;
  createdAt: Timestamp;
  startedAt: OptionalTimestamp;
  finishedAt: OptionalTimestamp;
}

model JobHandle {
  jobId: JobId;
  kind: JobKind;
  status: JobStatus;
  progress: JobProgress;

  /** The job's result file. Set only once the job succeeded and wrote it; null otherwise. */
  resultPath: string | null;

  logPath: string;
  exitCode: ExitCode;
  error: string | null;
  createdAt: Timestamp;
  startedAt: OptionalTimestamp;
  finishedAt: OptionalTimestamp;
}

@@extension(
  Job,
  "examples",
  #[
    #{
      jobId: "3f9c1a7b02de",
      kind: "collision/sweep",
      status: "running",
      progress: #{ fraction: 0.4, message: "pair 12 of 30" },
      argv: #["python3", "-m", "sweep", "--version", "LMP-0003"],
      cwd: "/work/lamp",
      host: "workstation",
      owner: #{
        pid: 4121,
        identity: "6f3a0c1e-9d1b-4a52-8d0e-0b7d2f5f1c11:48213377",
      },
      process: #{
        pid: 4188,
        identity: "6f3a0c1e-9d1b-4a52-8d0e-0b7d2f5f1c11:48213391",
      },
      resultPath: "/work/lamp/.benchhand/runs/3f9c1a7b02de.result",
      logPath: "/work/lamp/.benchhand/runs/3f9c1a7b02de.log",
      exitCode: null,
      error: null,
      createdAt: "2026-03-02T09:14:07+00:00",
      startedAt: "2026-03-02T09:14:07+00:00",
      finishedAt: null,
    },
    #{
      jobId: "3f9c1a7b02de",
      kind: "collision/sweep",
      status: "succeeded",
      progress: #{ fraction: 1, message: "30 of 30 pairs" },
      resultPath: "/work/lamp/.benchhand/runs/3f9c1a7b02de.result",
      logPath: "/work/lamp/.benchhand/runs/3f9c1a7b02de.log",
      exitCode: 0,
      error: null,
      createdAt: "2026-03-02T09:14:07+00:00",
      startedAt: "2026-03-02T09:14:07+00:00",
      finishedAt: "2026-03-02T09:16:41+00:00",
    },
    #{
      jobId: "a81e5c0d77b4",
      kind: "fem/solve",
      status: "failed",
      progress: #{ fraction: null, message: null },
      resultPath: null,
      logPath: "/work/lamp/.benchhand/runs/a81e5c0d77b4.log",
      exitCode: 3,
      error: "the job exited with status 3",
      createdAt: "2026-03-02T09:20:00+00:00",
      startedAt: "2026-03-02T09:20:00+00:00",
      finishedAt: "2026-03-02T09:20:12+00:00",
    }
  ]
);
