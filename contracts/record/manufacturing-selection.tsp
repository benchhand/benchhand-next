// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/manufacturing-selection/")
namespace Records.ManufacturingSelection;

/** Whole candidate routes compared together: architecture, per-part material profile and complete route with capabilities, an evaluation of every mandatory requirement, the changes each introduces, cost and lead time at quantity, maintenance, evidence confidence, pros, cons and tradeoffs. A mandatory fail eliminates a candidate and an unknown keeps it conditional; preferences rank only feasible candidates. A final recommendation needs the confirming decision; the selection never writes product records */
@summary("benchhand material, process and architecture selection (hw/manufacturing/selection.yaml)")
@id("https://benchhand.github.io/benchhand/contracts/record/manufacturing-selection.schema.json")
@extension("x-version", "1.0.0")
@extension(
  "allOf",
  #[
    #{
      `if`: #{ properties: #{ status: #{ `const`: "not_assessed" } } },
      then: #{
        properties: #{ candidates: #{ maxItems: 0 } },
        not: #{
          anyOf: #[
            #{ required: #["assessment"] },
            #{ required: #["recommendation"] }
          ],
        },
      },
    },
    #{
      `if`: #{
        properties: #{ status: #{ `enum`: #["assessed", "confirmed"] } },
      },
      then: #{
        required: #["assessment"],
        properties: #{ candidates: #{ minItems: 1 } },
      },
    },
    #{
      `if`: #{ properties: #{ status: #{ `const`: "confirmed" } } },
      then: #{
        required: #["recommendation"],
        properties: #{
          assessment: #{ required: #["decision"] },
          recommendation: #{ properties: #{ status: #{ `const`: "final" } } },
        },
      },
    }
  ]
)
model ManufacturingSelection {
  status: "not_assessed" | "assessed" | "confirmed";
  assessment?: {
    /** The selection input digest of the record inputs the assessment read (its DIGEST_SCOPE); a different current digest makes the assessment stale */
    input_sha256: Common.sha256;

    method: Common.text;
    date: Common.date;
    decision?: Common.decision;
  };
  candidates: candidate[];
  recommendation?: recommendation;
}

model candidate {
  id: Common.semantic_id;
  title: Common.text;
  architecture: Common.text;

  @minItems(1)
  parts: candidate_part[];

  @minItems(1)
  @uniqueItems
  interfaces?: Common.interface_id[];

  evaluations: ManufacturingSelectionCandidateEvaluationsItem[];

  @minProperties(1)
  changes?: {
    design?: Common.texts;
    equipment?: Common.texts;
    finishing?: Common.texts;
    inspection?: Common.texts;
    interfaces?: Common.texts;
    assembly?: Common.texts;
  };

  /** the quantity cost and lead time are stated at */
  quantity?: Common.quantity_fact;

  cost?: Common.money_fact;
  lead_time?: Common.quantity_fact;
  maintenance?: Common.text_fact;
  evidence_confidence?: Common.text;

  /** validation still outstanding */
  obligations?: Common.texts;

  pros: Common.texts;
  cons: Common.texts;
  tradeoffs: Common.texts;

  @minItems(1)
  preference_scores?: {
    preference: Common.preference_id;
    score: float64;
    note?: Common.text;
  }[];
}

@extension("x-inline", true)
@extension(
  "allOf",
  #[
    #{
      `if`: #{ properties: #{ outcome: #{ `enum`: #["pass", "fail"] } } },
      then: #{ required: #["criterion", "source"] },
    },
    #{ $ref: "common.schema.json#/$defs/not_assessed_rule" }
  ]
)
model ManufacturingSelectionCandidateEvaluationsItem {
  requirement: Common.requirement_id;
  outcome: Common.outcome;
  reason?: Common.not_assessed_reason;
  method: Common.text;
  criterion?: Common.criterion;

  @oneOf
  value?: Common.quantity | Common.text;

  uncertainty?: Common.text;
  source?: Common.source;
  note?: Common.text;
}

/** One part of a candidate: a declared part (hw/parts/<PN>/part.yaml) or, with `proposed`, a part the candidate introduces that the record does not hold yet */
@extension(
  "allOf",
  #[
    #{
      `if`: #{
        required: #["proposed"],
        properties: #{
          proposed: #{ properties: #{ sourcing: #{ `const`: "catalogue" } } },
        },
      },
      then: #{
        properties: #{
          route: #{
            items: #{
              properties: #{ kind: #{ `enum`: #["purchased", "inspection"] } },
            },
            contains: #{
              required: #["purchase"],
              properties: #{ kind: #{ `const`: "purchased" } },
            },
          },
        },
      },
    },
    #{
      `if`: #{
        required: #["proposed"],
        properties: #{
          proposed: #{
            properties: #{
              sourcing: #{ `enum`: #["make", "made_to_drawing"] },
            },
          },
        },
      },
      then: #{
        properties: #{
          route: #{
            items: #{
              properties: #{ kind: #{ not: #{ `const`: "purchased" } } },
            },
          },
        },
      },
    }
  ]
)
model candidate_part {
  PN: Common.pn;

  @oneOf
  material_profile: Common.profile_id | Common.fact_open;

  @minItems(1)
  route: step[];

  proposed?: proposed_part;
  note?: Common.text;
}

/** One route step of a candidate part. A purchased step may carry the purchase criteria of the bought item, so a purchased alternative to a made part can be assessed before any part record holds them */
@extension("if", #{ required: #["purchase"] })
@extension("then", #{ properties: #{ kind: #{ `const`: "purchased" } } })
model step {
  kind: Common.route_kind;

  @oneOf
  capability: Common.profile_id | Common.fact_open;

  provider?: "local" | "outsourced";
  purchase?: Part.purchase;
}

/** Marks a candidate part as proposed: a new purchased or made part the candidate's architecture introduces. Its PN must not be declared under hw/parts; it is never an existing record, gets no check obligations, and becomes a part only when the approved change creates its part.yaml. A catalogue proposal is bought (its route is the purchase, whose criteria identify the item); a made or made-to-drawing proposal lists the operations that make it */
model proposed_part {
  title: Common.text;

  /** make, made_to_drawing (bought to this drawing) or catalogue (bought as listed) */
  sourcing: "make" | "made_to_drawing" | "catalogue";

  /** why the candidate needs the new part */
  reason: Common.text;

  /** what the new part does, so function-driven constraints (optical, structural) apply to it */
  @minItems(1)
  functions?: Common.function_entry[];

  transparency?: Part.PartTransparency;
}

model recommendation {
  /** conditional while material-to-choice or safety inputs are missing */
  status: "conditional" | "final";

  primary: Common.semantic_id;
  prototype?: Common.semantic_id;
  end_use?: Common.semantic_id;
  fallback?: Common.semantic_id;
  governing_requirements?: Common.requirement_ids;
  reasons: Common.texts;
  limits: Common.texts;

  /** what the prototype route can and cannot validate */
  prototype_validates?: Common.texts;

  what_would_change: Common.texts;
  proposed_changes?: Common.texts;
}

@@example(ManufacturingSelection, #{ status: "not_assessed", candidates: #[] });
@@example(
  ManufacturingSelection,
  #{
    status: "assessed",
    assessment: #{
      input_sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      method: "selection 1",
      date: "2026-01-01",
    },
    candidates: #[
      #{
        id: "printed",
        title: "Printed bracket",
        architecture: "one printed part",
        parts: #[
          #{
            PN: "TST-0001",
            material_profile: "tst_polymer_printed",
            route: #[#{ kind: "fdm", capability: "tst_printer" }],
          }
        ],
        evaluations: #[
          #{
            requirement: "REQ-001",
            outcome: "unknown",
            method: "no creep data",
          }
        ],
        pros: #["cheap"],
        cons: #["creep unknown"],
        tradeoffs: #["speed against evidence"],
      }
    ],
    recommendation: #{
      status: "conditional",
      primary: "printed",
      reasons: #["only candidate"],
      limits: #["no creep evidence"],
      what_would_change: #["higher temperature"],
    },
  }
);
