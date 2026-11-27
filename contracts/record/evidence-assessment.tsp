// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

import "@typespec/json-schema";
import "../common/finding.tsp";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/evidence-assessment/")
namespace Records.EvidenceAssessment;

/** The evidence of one built record version: the status of every obligation the record implies, each from three sources only (the record itself, the sealed required-check packets of the version and the accepted ledger hw/manufacturing/evidence.yaml), the result of each evidence level per requirement, part, interface, assembly operation and the product as independent facets, the findings about the evidence, the unresolved critical producer findings and the acceptance digest a freeze records and a release checks. Unknown, planned and untested never become pass; stale evidence counts as nothing; a waived obligation stays waived */
@summary("benchhand evidence assessment of one built version")
@id("https://benchhand.github.io/benchhand/contracts/record/evidence-assessment.schema.json")
@extension("x-version", "1.0.0")
model EvidenceAssessment {
  version: Common.version;

  /** sha256 of hw/versions/<V>/manifest.json */
  manifest_sha256: Common.sha256;

  /** computed: producer outcomes whose inputs changed since the build are stale. not_computed: the built record could not be compared with the current one, so no producer pass, fail or not_applicable outcome counts, and a finding says why */
  build_staleness: "computed" | "not_computed";

  /** sha256 of the expected obligations, as canonical JSON */
  expected_sha256: Common.sha256;

  /** one status per expected obligation, sorted by obligation id */
  statuses: obligation_status[];

  /** per requirement, part, interface, op:<assembly operation> and product: each evidence level's worst status over its obligations, or not_required where none applies */
  facets: Record<facets>;

  findings: global.Common.Finding.Finding[];

  /** producer findings of severity critical whose outcome is fail or unknown and that no disposition settles */
  critical: critical_finding[];

  /** false when a producer packet was partial or refused */
  complete: boolean;

  acceptance: acceptance_formed | acceptance_refused;
}

union evidence_result {
  "pass",
  "fail",
  "waived",
  "not_applicable",
  "not_assessed",
  "stale",
  "planned",
  "unknown",
}

model obligation_status {
  obligation: Common.obligation;
  result: evidence_result;

  /** the packet bundles, ledger entry ids or `record` that decided it */
  sources: string[];

  reasons: string[];

  /** the approved waiver, when the result is waived */
  waiver?: Common.waiver;
}

union facet_result {
  evidence_result,
  "not_required",
}

model facets {
  cad_valid: facet_result;
  geometrically_manufacturable: facet_result;
  process_planned: facet_result;
  simulation_supported: facet_result;
  physically_validated: facet_result;
}

model critical_finding {
  finding: Common.semantic_id;
  code?: Common.finding_code;
  bundle: Common.project_path;
  obligation?: Common.obligation_id;
  consequence?: Common.text;
}

/** The acceptance inventory (hw/ path to sha256) and its digest: sha256 of {"schema": "cad-acceptance-inventory/1", "files": the sorted [path, sha256] pairs} as canonical JSON */
model acceptance_formed {
  status: "formed";
  evidence_sha256: Common.sha256;
  inventory: Record<Common.sha256>;
}

model acceptance_refused {
  status: "refused";

  /** why the inventory cannot be formed: a missing, linked, escaping or refused path */
  reason: Common.text;
}

@@example(
  EvidenceAssessment,
  #{
    version: "v1",
    manifest_sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    build_staleness: "computed",
    expected_sha256: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    statuses: #[
      #{
        obligation: #{
          id: "cad.readback@TST-0001",
          family: "cad.readback",
          subject: #{ PN: "TST-0001" },
          level: "cad_valid",
          stage: Common.stage.layout,
          basis: "TST-0001: B-rep validity and readback",
        },
        result: "pass",
        sources: #["hw/checks/v1/cad"],
        reasons: #["TST readback"],
      }
    ],
    facets: #{
      `TST-0001`: #{
        cad_valid: "pass",
        geometrically_manufacturable: "not_required",
        process_planned: "not_required",
        simulation_supported: "not_required",
        physically_validated: "not_required",
      },
    },
    findings: #[],
    critical: #[],
    complete: true,
    acceptance: #{
      status: "formed",
      evidence_sha256: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      inventory: #{
        `hw/verification.csv`: "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      },
    },
  }
);
