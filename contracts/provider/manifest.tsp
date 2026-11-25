import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/provider/manifest/")
@extension(
  "x-keyword-order",
  #[
    "properties",
    "required",
    "additionalProperties",
    "items",
    "minItems",
    "uniqueItems"
  ]
)
namespace Provider.Manifest;

/** A provider's manifest, benchhand-provider.toml: its name and version, the protocol version and kinds it serves, its hooks, how to start it (command, environment, timeouts), what it needs, and its CLI. */
@summary("benchhand-provider.toml")
@id("https://benchhand.github.io/benchhand/contracts/provider/manifest.schema.json")
@extension("x-version", "1.0.0")
@extension("x-keyword-order", #["additionalProperties", "required"])
model Manifest {
  @pattern("^[a-z][a-z0-9-]{1,63}$")
  name: string;

  version: string;
  summary?: string;
  protocol: {
    @minValue(1)
    min: integer;

    @minValue(1)
    max: integer;
  };

  @minItems(1)
  @uniqueItems
  kinds: Protocol.HookKind[];

  @minItems(1)
  hooks: Protocol.HookDecl[];

  resident?: boolean = false;

  @minItems(1)
  command: @minLength(1) scalar extends string[];

  @doc("Seconds per hook method, e.g. {\"solver/solve\": 3600}.")
  timeouts?: Record<ManifestTimeoutsValue>;

  @oneOf
  environment:
    | {
        kind: "uv";
        `requires-python`: string;
        dependencies: string[];
      }
    | {
        kind: "freecad";
      }
    | {
        kind: "system";
      };

  needs: Protocol.Needs;
  cli?: {
    @pattern("^[a-z][a-z0-9-]*$")
    name: string;

    summary: string;
  }[];
}

@extension("x-inline", true)
@minValue(1)
scalar ManifestTimeoutsValue extends integer;

@@example(
  Manifest,
  #{
    name: "kernel-build123d",
    version: "1.0.0",
    protocol: #{ min: 1, max: 1 },
    kinds: #["kernel"],
    hooks: #[
      #{ kind: "kernel", id: "build" },
      #{ kind: "kernel", id: "export" },
      #{ kind: "kernel", id: "inspect" }
    ],
    resident: false,
    command: #["python", "-m", "benchhand_kernel_build123d"],
    environment: #{
      kind: "uv",
      `requires-python`: ">=3.12,<3.13",
      dependencies: #[
        "build123d==0.13.0",
        "cadquery-ocp-novtk==8.0.1.1.0",
        "bd_warehouse==0.4.0",
        "benchhand-provider"
      ],
    },
    needs: #{ freecad: false, chromium: false, network: false },
    cli: #[#{ name: "probe", summary: "Check the build123d environment." }],
  }
);
