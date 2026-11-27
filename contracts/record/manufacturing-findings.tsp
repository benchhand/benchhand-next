// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/manufacturing-findings/")
namespace Records.ManufacturingFindings;

/** The lead's dispositions of immutable producer findings. Each names the finding id and the exact producer bundle manifest it lives in; producer rows are never copied or edited here. Declining or waiving a finding never turns a mandatory fail or unknown into a pass: the original outcome is evaluated together with the permitted, scoped disposition */
@summary("benchhand finding dispositions (hw/manufacturing/findings.yaml)")
@id("https://benchhand.github.io/benchhand/contracts/record/manufacturing-findings.schema.json")
@extension("x-version", "1.0.0")
model ManufacturingFindings {
  dispositions: disposition[];
}

@extension(
  "allOf",
  #[
    #{
      `if`: #{ properties: #{ status: #{ `const`: "accepted_waiver" } } },
      then: #{ required: #["waiver", "decision"] },
      `else`: #{ not: #{ required: #["waiver"] } },
    },
    #{
      `if`: #{ properties: #{ status: #{ `const`: "declined" } } },
      then: #{ required: #["decision"] },
    },
    #{
      `if`: #{ properties: #{ status: #{ `const`: "resolved" } } },
      then: #{
        anyOf: #[
          #{ required: #["replacement_evidence"] },
          #{ required: #["decision"] }
        ],
      },
    }
  ]
)
model disposition {
  finding: Common.semantic_id;
  code?: Common.finding_code;
  producer: {
    /** the producer bundle directory, project-relative */
    bundle: Common.project_path;

    manifest_sha256: Common.sha256;
  };
  status: "open" | "resolved" | "accepted_waiver" | "declined";
  reason: Common.text;
  decision?: Common.decision;

  @minItems(1)
  @uniqueItems
  replacement_evidence?: Common.evidence_id[];

  waiver?: Common.waiver;
}

@@example(
  ManufacturingFindings,
  #{
    dispositions: #[
      #{
        finding: "overhang_1",
        producer: #{
          bundle: "hw/checks/v1/TST-0001",
          manifest_sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        },
        status: "accepted_waiver",
        reason: "trial print",
        decision: "DR-001",
        waiver: #{
          decision: "DR-001",
          subject: #{ PN: "TST-0001" },
          criterion: "creep",
          operating_envelope: "below 30 deg_C",
          until_change: "any load change",
          reason: "trial",
          consequence: "sag",
          authority: "lead",
        },
      }
    ],
  }
);
