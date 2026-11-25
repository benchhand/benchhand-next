import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/manufacturing-evidence/")
namespace Records.ManufacturingEvidence;

/** Accepted evidence per requirement, part, component, interface or operation, one entry per evidence level: CAD-valid, geometrically manufacturable, process planned, simulation-supported and physically validated are independent facets. A pass or fail cites its artifacts or sealed bundle and the configuration, material, process and conditions it applies to; physically validated evidence also records the specimen, protocol, instrument calibration, results, date, approver and scope. Planned and unknown are never a pass, and waived stays waived */
@summary("benchhand evidence ledger (hw/manufacturing/evidence.yaml)")
@id("https://benchhand.github.io/benchhand/contracts/record/manufacturing-evidence.schema.json")
@extension("x-version", "1.0.0")
model ManufacturingEvidence {
  entries: entry[];
}

union fingerprint_domain {
  "material",
  "lot",
  "condition",
  "process",
  "route",
  "orientation",
  "setup",
  "capability",
  "finish",
  "load",
  "environment",
  "interface",
  "occurrences",
  "criterion",
  "source",
  "geometry",
  "use_case",
  "appearance",
}

@extension(
  "anyOf",
  #[#{ required: #["requirement"] }, #{ required: #["obligation"] }]
)
@extension(
  "allOf",
  #[
    #{
      `if`: #{ properties: #{ result: #{ `enum`: #["pass", "fail"] } } },
      then: #{
        required: #["configuration", "criterion"],
        anyOf: #[#{ required: #["artifacts"] }, #{ required: #["bundle"] }],
      },
    },
    #{
      `if`: #{
        properties: #{
          result: #{ `enum`: #["pass", "fail"] },
          level: #{ `const`: "physically_validated" },
        },
      },
      then: #{ required: #["physical"] },
    },
    #{
      `if`: #{ properties: #{ result: #{ `const`: "waived" } } },
      then: #{ required: #["waiver"] },
      `else`: #{ not: #{ required: #["waiver"] } },
    }
  ]
)
model entry {
  id: Common.evidence_id;
  requirement?: Common.requirement_id;
  obligation?: Common.obligation_id;
  subject: Common.subject;
  level: Common.evidence_level;
  result: "unknown" | "planned" | "pass" | "fail" | "waived";
  method: Common.text;
  criterion?: Common.criterion;
  source?: Common.source;
  configuration?: {
    version: Common.version;
    manifest_sha256: Common.sha256;
    rev?: Common.revision;
    geometry_sha256?: Common.sha256;
  };

  /** sha256 of each normalized dependency the evidence relied on, by domain; a changed fingerprint makes the evidence stale until an impact assessment carries it forward */
  @minProperties(1)
  @extension("propertyNames", #{ $ref: "#/$defs/fingerprint_domain" })
  fingerprints?: Record<Common.sha256>;

  @minItems(1)
  artifacts?: Common.file_hash[];

  bundle?: {
    path: Common.project_path;
    manifest_sha256: Common.sha256;
  };
  tool?: Common.text;
  producer?: Common.text;
  uncertainty?: Common.text;
  coverage?: Common.text;
  physical?: {
    /** the actual item tested: coupon, part or assembly, with its identity */
    specimen: Common.text;

    /** the as-built configuration and revision */
    configuration: Common.text;

    /** the material and lot as used */
    material: Common.text;

    /** the route and settings as used */
    process: Common.text;

    protocol: Common.text;
    setup?: Common.text;

    /** the instrument and its calibration */
    instrument: Common.text;

    results: Common.text;
    date: Common.date;
    approver: Common.text;

    /** what the result covers: a coupon covers its coupon scope, not assembly or end-use life */
    scope: Common.text;
  };
  waiver?: Common.waiver;

  @minItems(1)
  @uniqueItems
  decisions?: Common.decision[];

  note?: Common.text;
}

@@extension(
  ManufacturingEvidence,
  "examples",
  #[
    #{
      entries: #[
        #{
          id: "EV-001",
          requirement: "REQ-001",
          subject: #{ PN: "TST-0001" },
          level: "physically_validated",
          result: "pass",
          method: "coupon load test",
          criterion: #{
            property: "load",
            operator: ">=",
            value: 11,
            units: "N",
            source: #{
              kind: "user",
              reference: "bench test request",
              origin: "the user",
            },
          },
          configuration: #{
            version: "v1",
            manifest_sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            rev: "X1",
          },
          artifacts: #[
            #{
              path: "hw/manufacturing/sources/test.csv",
              sha256: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            }
          ],
          physical: #{
            specimen: "coupon 1",
            configuration: "v1",
            material: "TST lot 1",
            process: "print",
            protocol: "TST protocol",
            instrument: "TST scale, calibrated",
            results: "12 N",
            date: "2026-01-02",
            approver: "lead",
            scope: "coupon only",
          },
        },
        #{
          id: "EV-002",
          requirement: "REQ-002",
          subject: #{ PN: "TST-0001" },
          level: "process_planned",
          result: "planned",
          method: "print trial",
        }
      ],
    }
  ]
);
