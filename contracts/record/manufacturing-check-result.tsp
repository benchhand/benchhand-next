// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/manufacturing-check-result/")
namespace Records.ManufacturingCheckResult;

/** One producer's required-check packet for one version: the obligations it was asked to cover (enumerated from the record before it ran), one outcome per obligation, its findings, the dependency fingerprints it read and whether it covered every expected obligation. A producer cannot shrink its scope by omission: an expected obligation without an outcome makes the packet incomplete, and unknown never counts as pass. Ported to v3 from the prototype's manufacturing-check-result schema at reference_commit 412b5d9: its record_version is the v3 record_version */
@summary("benchhand manufacturing-intent check result (result.json of a hw/checks/<V>/<S> bundle)")
@id("https://benchhand.github.io/benchhand/contracts/record/manufacturing-check-result.schema.json")
@extension("x-version", "1.0.0")
model ManufacturingCheckResult {
  schema_version: 1;
  record_version: Common.record_version;

  /** the writing tool and its version */
  producer: Common.text;

  @minItems(1)
  scope: Common.subject[];

  expected: Common.obligation[];
  outcomes: Common.obligation_outcome[];
  findings: Common.finding[];

  /** sha256 of each input the producer read, by name, such as the part record, material and capability profiles and the geometry */
  @extension("propertyNames", Common.semantic_id)
  dependencies: Record<Common.sha256>;

  /** true only when every expected obligation has an outcome */
  complete: boolean;

  /** fail if any outcome fails, else unknown if any is unknown or the packet is incomplete, else not_assessed if any outcome is, else pass (not_applicable outcomes aside) */
  result: Common.outcome;
}

@@example(
  ManufacturingCheckResult,
  #{
    schema_version: 1,
    record_version: 3,
    producer: "TST producer 1.0",
    scope: #[#{ PN: "TST-0001" }],
    expected: #[
      #{
        id: "cad.readback@TST-0001",
        family: "cad.readback",
        subject: #{ PN: "TST-0001" },
        level: "cad_valid",
        stage: Common.stage.layout,
        basis: "TST-0001: B-rep validity and readback",
      }
    ],
    outcomes: #[
      #{
        obligation: "cad.readback@TST-0001",
        outcome: "pass",
        level: "cad_valid",
        method: "TST readback",
        coverage: "the sealed STEP only",
      }
    ],
    findings: #[],
    dependencies: #{
      geometry: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    },
    complete: true,
    result: "pass",
  }
);
