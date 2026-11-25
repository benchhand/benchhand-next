import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/provider/protocol/")
@extension("x-keyword-order", #["required", "additionalProperties"])
namespace Provider.Protocol;

/** Message shapes of the benchhand provider protocol. Prose rules: docs/contract/provider-protocol.md. */
@summary("benchhand provider protocol")
@id("https://benchhand.github.io/benchhand/contracts/provider/protocol.schema.json")
@oneOf
@extension("x-version", "1.0.0")
@extension("x-protocol-version", 1)
union Protocol {
  Request,
  Notification,
  SuccessResponse,
  ErrorResponse,
}

@minValue(1)
@maxValue(9007199254740991)
scalar RequestId extends integer;

@minValue(1)
scalar ProtocolVersion extends integer;

union HookKind {
  "kernel",
  "cad-app",
  "solver",
  "collision",
  "renderer",
  "viewer",
  "process-check",
  "store",
  "policy",
  "cli",
}

@pattern("^[a-z][a-z0-9-]{0,63}$")
scalar HookId extends string;

@pattern("^([a-z][a-z0-9-]*|x-[a-z0-9-]+)$")
scalar FeatureName extends string;

/** Absolute POSIX path. */
@pattern("^/")
@minLength(2)
@extension("x-keyword-order", #["pattern", "minLength"])
scalar AbsPath extends string;

@pattern("^[0-9a-f]{64}$")
scalar Sha256 extends string;

model HookDecl {
  kind: HookKind;
  id: HookId;
}

model ErrorObject {
  code: integer;
  message: string;
  data: {
    code:
      | "parse-error"
      | "invalid-request"
      | "method-not-found"
      | "invalid-params"
      | "internal-error"
      | "protocol-version-unsupported"
      | "required-feature-missing"
      | "not-initialized"
      | "message-too-large"
      | "request-cancelled"
      | "input-unsupported"
      | "external-missing";
    supported?: {
      min: ProtocolVersion;
      max: ProtocolVersion;
    };
    fix?: string;
    detail?: unknown;
  };
}

model Limits {
  @minValue(65536)
  @maxValue(16777216)
  maxMessageBytes?: integer;

  @minValue(1)
  @maxValue(16)
  maxInFlight?: integer;
}

model InitializeParams {
  protocolVersion: ProtocolVersion;
  minProtocolVersion?: ProtocolVersion;
  host: {
    name: "benchhand";
    version: string;
  };
  capabilities: {
    @uniqueItems
    hooks: HookKind[];

    @uniqueItems
    features: FeatureName[];
  };
  limits: Limits;
  projectRoot?: AbsPath;
}

model InitializeResult {
  protocolVersion: ProtocolVersion;
  provider: {
    name: string;
    version: string;
  };

  @minItems(1)
  hooks: HookDecl[];

  features: {
    required: FeatureName[];
    optional: FeatureName[];
  };
  limits: Limits;
  needs: Needs;
}

model Needs {
  freecad: boolean;
  chromium: boolean;
  network: boolean;
}

model CancelParams {
  id: RequestId;
}

model ProgressParams {
  id: RequestId;

  @minValue(0)
  @maxValue(1)
  fraction?: float64;

  @maxLength(500)
  message?: string;

  @maxLength(80)
  stage?: string;
}

model LogParams {
  level: "debug" | "info" | "warning" | "error";

  @maxLength(4000)
  message: string;

  data?: unknown;
}

model Artifact {
  path: AbsPath;
  mediaType: string;

  @pattern("^[a-z][a-z0-9-]*$")
  role: string;

  @minValue(0)
  bytes: integer;

  sha256: Sha256;
}

@extension(
  "allOf",
  #[
    #{
      `if`: #{ properties: #{ status: #{ `const`: "unknown" } } },
      then: #{ required: #["reason"] },
    }
  ]
)
model Coverage {
  status: "pass" | "fail" | "unknown";
  reason?: string;
}

model HookParamsBase {
  projectRoot: AbsPath;
  outDir: AbsPath;
  input: {
    ...Record<unknown>;
  };
}

model HookResultBase {
  coverage: Coverage;
  artifacts: Artifact[];
  nondeterministic?: boolean;
  output?: {
    ...Record<unknown>;
  };
}

model KernelBuildPart {
  @pattern("^[A-Z0-9][A-Z0-9-]{1,31}$")
  pn: string;

  name?: string;
  `model`: AbsPath;
  modelFrame?: string;
  step: AbsPath;
  manufactureStep?: AbsPath;
}

union KernelBuildParams {
  HookParamsBase,
}

model KernelBuildPartResult {
  @pattern("^[A-Z0-9][A-Z0-9-]{1,31}$")
  pn: string;

  status: "pass" | "fail";
  error?: string;

  @minValue(0)
  seconds?: float64;
}

union KernelBuildResult {
  HookResultBase,
}

union KernelExportParams {
  HookParamsBase,
}

union KernelExportResult {
  HookResultBase,
}

union KernelInspectParams {
  HookParamsBase,
}

union KernelInspectResult {
  HookResultBase,
}

union CadAppDrawingParams {
  HookParamsBase,
}

union CadAppDrawingResult {
  HookResultBase,
}

union CadAppAssemblyParams {
  HookParamsBase,
}

union CadAppAssemblyResult {
  HookResultBase,
}

union CadAppFemParams {
  HookParamsBase,
}

union CadAppFemResult {
  HookResultBase,
}

union SolverSolveParams {
  HookParamsBase,
}

union SolverSolveResult {
  HookResultBase,
}

union CollisionCheckParams {
  HookParamsBase,
}

union CollisionCheckResult {
  HookResultBase,
}

union CollisionSweepParams {
  HookParamsBase,
}

union CollisionSweepResult {
  HookResultBase,
}

union RendererRenderParams {
  HookParamsBase,
}

union RendererRenderResult {
  HookResultBase,
}

union RendererSnapshotParams {
  HookParamsBase,
}

union RendererSnapshotResult {
  HookResultBase,
}

union ViewerShowParams {
  HookParamsBase,
}

union ViewerShowResult {
  HookResultBase,
}

union ViewerCompareParams {
  HookParamsBase,
}

union ViewerCompareResult {
  HookResultBase,
}

union ViewerCaptureParams {
  HookParamsBase,
}

union ViewerCaptureResult {
  HookResultBase,
}

union ProcessCheckCheckParams {
  HookParamsBase,
}

union ProcessCheckCheckResult {
  HookResultBase,
}

union StorePutParams {
  HookParamsBase,
}

union StorePutResult {
  HookResultBase,
}

union StoreGetParams {
  HookParamsBase,
}

union StoreGetResult {
  HookResultBase,
}

union StoreListParams {
  HookParamsBase,
}

union StoreListResult {
  HookResultBase,
}

union PolicyEvaluateParams {
  HookParamsBase,
}

union PolicyEvaluateResult {
  HookResultBase,
}

union CliRunParams {
  HookParamsBase,
}

union CliRunResult {
  HookResultBase,
}

union Method {
  "initialize",
  "initialized",
  "shutdown",
  "exit",
  "$/cancelRequest",
  "$/progress",
  "$/log",
  "kernel/build",
  "kernel/export",
  "kernel/inspect",
  "cad-app/drawing",
  "cad-app/assembly",
  "cad-app/fem",
  "solver/solve",
  "collision/check",
  "collision/sweep",
  "renderer/render",
  "renderer/snapshot",
  "viewer/show",
  "viewer/compare",
  "viewer/capture",
  "process-check/check",
  "store/put",
  "store/get",
  "store/list",
  "policy/evaluate",
  "cli/run",
}

model Request {
  jsonrpc: "2.0";
  id: RequestId;
  method: Method;
  params?: unknown;
}

model Notification {
  jsonrpc: "2.0";
  method: Method;
  params?: unknown;
}

model SuccessResponse {
  jsonrpc: "2.0";
  id: RequestId;
  result: unknown;
}

model ErrorResponse {
  jsonrpc: "2.0";

  @oneOf
  id: RequestId | null;

  error: ErrorObject;
}

/** Numeric code for each data.code. */
@extension(
  "const",
  #{
    `parse-error`: -32700,
    `invalid-request`: -32600,
    `method-not-found`: -32601,
    `invalid-params`: -32602,
    `internal-error`: -32603,
    `protocol-version-unsupported`: -32001,
    `required-feature-missing`: -32002,
    `not-initialized`: -32003,
    `message-too-large`: -32004,
    `request-cancelled`: -32005,
    `input-unsupported`: -32006,
    `external-missing`: -32007,
  }
)
union ErrorCodes {
  unknown,
}

@@extension(
  Protocol,
  "examples",
  #[
    #{
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: #{
        protocolVersion: 1,
        minProtocolVersion: 1,
        host: #{ name: "benchhand", version: "0.1.0" },
        capabilities: #{
          hooks: #["kernel"],
          features: #["progress", "artifacts", "cancel"],
        },
        limits: #{ maxMessageBytes: 16777216, maxInFlight: 16 },
        projectRoot: "/work/lamp",
      },
    },
    #{
      jsonrpc: "2.0",
      method: "$/progress",
      params: #{ id: 2, fraction: 0.5, message: "LMP-0003 built" },
    },
    #{
      jsonrpc: "2.0",
      id: 3,
      error: #{
        code: -32007,
        message: "FreeCAD 1.0.2 is not a supported version",
        data: #{
          code: "external-missing",
          fix: "Run `benchhand setup` to install FreeCAD 1.1.4.",
        },
      },
    }
  ]
);

@@extension(HookDecl, "examples", #[#{ kind: "kernel", id: "build123d" }]);

@@extension(
  ErrorObject,
  "examples",
  #[
    #{
      code: -32602,
      message: "params.input.parts is missing",
      data: #{ code: "invalid-params" },
    }
  ]
);

@@extension(
  Limits,
  "examples",
  #[#{ maxMessageBytes: 16777216, maxInFlight: 4 }]
);

@@extension(
  InitializeParams,
  "examples",
  #[
    #{
      protocolVersion: 1,
      host: #{ name: "benchhand", version: "0.1.0" },
      capabilities: #{ hooks: #["kernel"], features: #["progress", "cancel"] },
      limits: #{ maxMessageBytes: 16777216, maxInFlight: 16 },
      projectRoot: "/work/lamp",
    }
  ]
);

@@extension(
  InitializeResult,
  "examples",
  #[
    #{
      protocolVersion: 1,
      provider: #{ name: "benchhand-build123d", version: "0.1.0" },
      hooks: #[#{ kind: "kernel", id: "build123d" }],
      features: #{ required: #[], optional: #["progress"] },
      limits: #{ maxInFlight: 4 },
      needs: #{ freecad: false, chromium: false, network: false },
    }
  ]
);

@@extension(
  Needs,
  "examples",
  #[#{ freecad: true, chromium: false, network: false }]
);

@@extension(CancelParams, "examples", #[#{ id: 7 }]);

@@extension(
  ProgressParams,
  "examples",
  #[#{ id: 7, fraction: 0.25, message: "LMP-0003 built", stage: "build" }]
);

@@extension(
  LogParams,
  "examples",
  #[
    #{
      level: "warning",
      message: "fillet radius clamped to 0.4 mm",
      data: #{ pn: "LMP-0003" },
    }
  ]
);

@@extension(
  Artifact,
  "examples",
  #[
    #{
      path: "/work/lamp/out/LMP-0003.step",
      mediaType: "model/step",
      role: "step",
      bytes: 48213,
      sha256: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    }
  ]
);

@@extension(
  Coverage,
  "examples",
  #[#{ status: "pass" }, #{ status: "unknown", reason: "no mesh for LMP-0004" }]
);

@@extension(
  HookParamsBase,
  "examples",
  #[
    #{
      projectRoot: "/work/lamp",
      outDir: "/work/lamp/out",
      input: #{ parts: #["LMP-0003"] },
    }
  ]
);

@@extension(
  HookResultBase,
  "examples",
  #[
    #{
      coverage: #{ status: "pass" },
      artifacts: #[
        #{
          path: "/work/lamp/out/LMP-0003.step",
          mediaType: "model/step",
          role: "step",
          bytes: 48213,
          sha256: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        }
      ],
      output: #{},
    }
  ]
);

@@extension(
  KernelBuildPart,
  "examples",
  #[
    #{
      pn: "LMP-0003",
      name: "arm link",
      `model`: "/work/lamp/hw/parts/LMP-0003/model.py",
      step: "/work/lamp/out/LMP-0003.step",
    }
  ]
);

@@extension(
  KernelBuildPartResult,
  "examples",
  #[
    #{ pn: "LMP-0003", status: "pass", seconds: 1.8 },
    #{ pn: "LMP-0004", status: "fail", error: "fillet failed" }
  ]
);

@@extension(
  Request,
  "examples",
  #[
    #{
      jsonrpc: "2.0",
      id: 7,
      method: "kernel/build",
      params: #{
        projectRoot: "/work/lamp",
        outDir: "/work/lamp/out",
        input: #{},
      },
    }
  ]
);

@@extension(
  Notification,
  "examples",
  #[#{ jsonrpc: "2.0", method: "$/cancelRequest", params: #{ id: 7 } }]
);

@@extension(
  SuccessResponse,
  "examples",
  #[
    #{
      jsonrpc: "2.0",
      id: 7,
      result: #{ coverage: #{ status: "pass" }, artifacts: #[] },
    }
  ]
);

@@extension(
  ErrorResponse,
  "examples",
  #[
    #{
      jsonrpc: "2.0",
      id: null,
      error: #{
        code: -32700,
        message: "invalid JSON",
        data: #{ code: "parse-error" },
      },
    }
  ]
);
