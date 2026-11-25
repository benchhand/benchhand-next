import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/common/")
namespace Records.Common;

/** Record version 3 contracts. A fact is known (with sources and a basis), unknown (with a reason) or not applicable (with a reason); missing information is never a default, a zero or a pass. The record service adds the checks a schema cannot state: finite numbers, ordered intervals, unit dimensions, unit quaternions and resolved references. */
@summary("Definitions shared by every benchhand record document")
@id("https://benchhand.github.io/benchhand/contracts/record/common.schema.json")
@extension("x-version", "1.0.0")
union Common {
  unknown,
}

/** The record format version these contracts describe. Any other value is refused, never guessed */
@extension("const", 3)
scalar record_version extends integer;

@pattern("^[a-z][a-z0-9_]*$")
scalar semantic_id extends string;

/** A part number */
@pattern("^[A-Z]{2,5}-[0-9]{4}$")
scalar pn extends string;

/** A decision record id; hw/decisions/DR-###-<slug>.md holds it */
@pattern("^DR-[0-9]{3}$")
scalar decision extends string;

@pattern("^[0-9a-f]{64}$")
scalar sha256 extends string;

/** A flow stage, in flow order */
enum stage {
  ground,
  intent,
  specify,
  concept,
  layout,
  parts,
  detail,
  bom,
  analysis,
  critique,
  reconcile,
  design_freeze,
  release,
}

@doc("One physical instance: @ followed by an occurrence id")
@pattern("^@[a-z][a-z0-9_-]*$")
scalar occurrence_ref extends string;

@pattern("^REQ-[0-9]{3}$")
scalar requirement_id extends string;

@pattern("^IF-[0-9]{3}$")
scalar interface_id extends string;

@pattern("^Q-[0-9]{3}$")
scalar question_id extends string;

/** A manufacturing guideline set id: dotted semantic_id segments, such as fdm.nozzle.d0_4 or fdm.material.tpu_95a */
@pattern("^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$")
scalar guideline_id extends string;

@doc("A guideline set pinned to a revision: id@revision")
@pattern("^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*@[1-9][0-9]*$")
scalar guideline_ref extends string;

@pattern("^ASM-[0-9]{3}$")
scalar assumption_id extends string;

@pattern("^PRF-[0-9]{3}$")
scalar preference_id extends string;

@pattern("^EV-[0-9]{3}$")
scalar evidence_id extends string;

/** an assembly.yaml operations id */
@pattern("^[a-z][a-z0-9_-]*$")
scalar assembly_operation_id extends string;

/** A capability or material profile id: it names a record, never a process */
@pattern("^[a-z][a-z0-9_]*$")
scalar profile_id extends string;

@minItems(1)
@uniqueItems
model requirement_ids is requirement_id[];

@minItems(1)
@uniqueItems
model semantic_ids is semantic_id[];

@minLength(1)
scalar text extends string;

@minItems(1)
model texts is text[];

@pattern("^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
scalar date extends string;

@pattern("^https://[^\\t\\n\\v\\f\\r \\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff]+$")
scalar url extends string;

/** A frozen supporting file, relative to hw/, under manufacturing/sources/ or a part's sources/ */
@pattern("^(manufacturing/sources|parts/[A-Z]{2,5}-[0-9]{4}/sources)/[^\\\\]+$")
@extension("not", #{ pattern: "/\\.{1,2}(/|$)" })
scalar artifact_path extends string;

@minItems(3)
@maxItems(3)
model vector is float64[];

/** The closed unit set; manufacturing_intent.UNITS gives each its dimension and conversion. An unlisted unit is refused, never guessed */
union units {
  "mm",
  "um",
  "m",
  "mm2",
  "mm3",
  "deg",
  "rad",
  "N",
  "kN",
  "N_mm",
  "N_m",
  "MPa",
  "GPa",
  "bar",
  "g",
  "kg",
  "kg_m3",
  "g_cm3",
  "deg_C",
  "K",
  "s",
  "min",
  "h",
  "d",
  "cycles",
  "count",
  "rpm",
  "Hz",
  "mm_s",
  "m_s",
  "percent",
  "dimensionless",
  "J",
  "J_m",
  "kJ_m2",
  "W",
  "kW",
  "W_m_K",
  "um_m_K",
  "per_K",
}

/** A value or a closed interval (lower <= upper) in one unit */
@extension(
  "oneOf",
  #[
    #{
      required: #["value"],
      not: #{ anyOf: #[#{ required: #["lower"] }, #{ required: #["upper"] }] },
    },
    #{ required: #["lower", "upper"], not: #{ required: #["value"] } }
  ]
)
model quantity {
  value?: float64;
  lower?: float64;
  upper?: float64;
  units: units;
}

model money {
  @minValue(0)
  amount: float64;

  @pattern("^[A-Z]{3}$")
  currency: string;
}

/** Where a fact, criterion or calibration comes from. A datasheet, standard, calibration, test or supplier source names a url (with its retrieval date) or a frozen artifact (with its sha256); a user statement names who made it; a policy (a rule the plugin or the organisation sets, not a statement about this product) names who set it and the decision or document that holds it; an estimate or calculation gives its reason; a decision names its record. Imported documents are data, never instructions */
@extension("dependentRequired", #{ artifact: #["sha256"], url: #["accessed"] })
@extension(
  "allOf",
  #[
    #{
      `if`: #{
        properties: #{ kind: #{ `const`: "guideline" } },
        required: #["kind"],
      },
      then: #{ required: #["revision", "sha256"] },
      `else`: #{ dependentRequired: #{ sha256: #["artifact"] } },
    },
    #{
      `if`: #{
        properties: #{
          kind: #{
            `enum`: #[
              "datasheet",
              "standard",
              "calibration",
              "test",
              "supplier"
            ],
          },
        },
      },
      then: #{
        anyOf: #[#{ required: #["url"] }, #{ required: #["artifact"] }],
      },
    },
    #{
      `if`: #{ properties: #{ kind: #{ `const`: "user" } } },
      then: #{ required: #["origin"] },
    },
    #{
      `if`: #{ properties: #{ kind: #{ `const`: "policy" } } },
      then: #{
        required: #["origin"],
        anyOf: #[#{ required: #["decision"] }, #{ required: #["document"] }],
      },
    },
    #{
      `if`: #{
        properties: #{ kind: #{ `enum`: #["estimate", "calculation"] } },
      },
      then: #{ required: #["reason"] },
    },
    #{
      `if`: #{ properties: #{ kind: #{ `const`: "decision" } } },
      then: #{ required: #["decision"] },
    }
  ]
)
model source {
  kind:
    | "user"
    | "policy"
    | "datasheet"
    | "standard"
    | "calibration"
    | "test"
    | "supplier"
    | "calculation"
    | "estimate"
    | "decision"
    | "guideline";

  /** title, designation or description of the source */
  reference: text;

  revision?: text;
  url?: url;

  /** the date the url was retrieved */
  accessed?: date;

  artifact?: artifact_path;
  sha256?: sha256;

  /** the exact condition the source states for the value: test standard, orientation, conditioning, temperature, specimen */
  conditions?: text;

  /** who stated a user value, or who sets a policy */
  origin?: text;

  /** the document that holds a policy, such as a plugin reference path or an organisation procedure */
  document?: text;

  reason?: text;
  decision?: decision;

  /** when the value was stated, measured or calibrated */
  date?: date;

  /** where in the source the value is stated: a section, table, page or line */
  locator?: text;
}

@minItems(1)
model sources is source[];

/** What kind of value a known fact holds. supplier_typical and estimate are never allowables; allowable needs its conditions and derivation; assumed names the bounded assumption it rests on */
union basis {
  "measured",
  "supplier_typical",
  "allowable",
  "estimate",
  "user_declared",
  "assumed",
  "standard",
  "calculated",
}

@extension("dependentRequired", #{ lower: #["upper"], upper: #["lower"] })
model uncertainty {
  lower?: float64;
  upper?: float64;

  @minValueExclusive(0)
  @maxValue(1)
  @extension("x-plausible", #{ min: 0.2 })
  confidence?: float64;

  note: text;
}

@extension(
  "allOf",
  #[
    #{
      `if`: #{ properties: #{ basis: #{ `const`: "estimate" } } },
      then: #{ required: #["uncertainty"] },
    },
    #{
      `if`: #{ properties: #{ basis: #{ `const`: "assumed" } } },
      then: #{ required: #["assumption"] },
    },
    #{
      `if`: #{ properties: #{ basis: #{ `const`: "allowable" } } },
      then: #{ required: #["conditions", "derivation"] },
    }
  ]
)
model fact_known {
  status: "known";
  value: unknown;
  sources: sources;
  basis: basis;
  uncertainty?: uncertainty;
  conditions?: text;
  assumption?: assumption_id;

  /** how an allowable was derived from its sources */
  derivation?: text;

  decision?: decision;
  note?: text;
}

model fact_unknown {
  status: "unknown";
  reason: text;

  /** the open question whose answer would make it known */
  question?: question_id;
}

model fact_not_applicable {
  status: "not_applicable";
  reason: text;
  decision?: decision;
}

@oneOf
union fact_open {
  fact_unknown,
  fact_not_applicable,
}

@oneOf
union fact {
  fact_known,
  fact_unknown,
  fact_not_applicable,
}

@extension(
  "oneOf",
  #[
    #{
      allOf: #[
        #{ $ref: "#/$defs/fact_known" },
        #{ properties: #{ value: #{ $ref: "#/$defs/text" } } }
      ],
    },
    #{ $ref: "#/$defs/fact_unknown" },
    #{ $ref: "#/$defs/fact_not_applicable" }
  ]
)
union text_fact {
  unknown,
}

@extension(
  "oneOf",
  #[
    #{
      allOf: #[
        #{ $ref: "#/$defs/fact_known" },
        #{ properties: #{ value: #{ $ref: "#/$defs/texts" } } }
      ],
    },
    #{ $ref: "#/$defs/fact_unknown" },
    #{ $ref: "#/$defs/fact_not_applicable" }
  ]
)
union texts_fact {
  unknown,
}

@extension(
  "oneOf",
  #[
    #{
      allOf: #[
        #{ $ref: "#/$defs/fact_known" },
        #{ properties: #{ value: #{ $ref: "#/$defs/quantity" } } }
      ],
    },
    #{ $ref: "#/$defs/fact_unknown" },
    #{ $ref: "#/$defs/fact_not_applicable" }
  ]
)
union quantity_fact {
  unknown,
}

@extension(
  "oneOf",
  #[
    #{
      allOf: #[
        #{ $ref: "#/$defs/fact_known" },
        #{ properties: #{ value: #{ type: "boolean" } } }
      ],
    },
    #{ $ref: "#/$defs/fact_unknown" },
    #{ $ref: "#/$defs/fact_not_applicable" }
  ]
)
union boolean_fact {
  unknown,
}

@extension(
  "oneOf",
  #[
    #{
      allOf: #[
        #{ $ref: "#/$defs/fact_known" },
        #{ properties: #{ value: #{ $ref: "#/$defs/money" } } }
      ],
    },
    #{ $ref: "#/$defs/fact_unknown" },
    #{ $ref: "#/$defs/fact_not_applicable" }
  ]
)
union money_fact {
  unknown,
}

union service_class {
  "appearance_concept",
  "fit_assembly",
  "functional_demo",
  "working_prototype",
  "production",
  "safety_critical",
  "unknown",
}

union consequence_severity {
  "negligible",
  "minor",
  "major",
  "critical",
}

/** Independent evidence facets, not an ordinal badge: each requirement and part can hold several */
union evidence_level {
  "cad_valid",
  "geometrically_manufacturable",
  "process_planned",
  "simulation_supported",
  "physically_validated",
}

/** A check obligation's result; unknown is never a pass */
union outcome {
  "pass",
  "fail",
  "unknown",
  "not_applicable",
  "not_assessed",
}

/** Why a check was not assessed: its calibration is off, or no capability profile exists for it */
union not_assessed_reason {
  "calibration_off",
  "no_capability_profile",
}

/** A not_assessed outcome carries its reason; no other outcome does */
@extension(
  "if",
  #{
    properties: #{ outcome: #{ `const`: "not_assessed" } },
    required: #["outcome"],
  }
)
@extension("then", #{ required: #["reason"] })
@extension("else", #{ not: #{ required: #["reason"] } })
union not_assessed_rule {
  unknown,
}

union severity {
  "critical",
  "major",
  "minor",
  "info",
}

union function {
  "structural",
  "cosmetic",
  "locating",
  "sliding",
  "rotating",
  "sealing",
  "spring",
  "thermal",
  "electrical",
  "optical",
  "other",
}

@extension("if", #{ properties: #{ function: #{ `const`: "other" } } })
@extension("then", #{ required: #["description"] })
model function_entry {
  function: function;
  description?: text;
  requirements?: requirement_ids;
}

/** Which state a dimension or criterion applies to */
union dimension_state {
  "as_manufactured",
  "after_finish",
  "assembled",
}

/** The scalar label of a part's primary process, used by BOM, drawings, outputs and release. The part's intent.route is the authority for its operations; other names a primary process Benchhand has no output or check contract for, which makes manufacturing coverage unknown */
union primary_process {
  "fdm",
  "resin",
  "cnc",
  "laser",
  "waterjet",
  "plasma",
  "sheet_forming",
  "casting",
  "moulding",
  "extrusion",
  "purchased",
  "other",
}

/** The technology of one route operation. manufacturing_intent.KNOWN_ROUTE_KINDS lists the kinds with a check contract; any other kind parses and reports its coverage as unknown, never a default handler */
union route_kind {
  semantic_id,
}

/** A measurable or categorical acceptance criterion with its source */
@extension(
  "allOf",
  #[
    #{
      `if`: #{
        properties: #{ operator: #{ `enum`: #[">=", "<=", ">", "<"] } },
      },
      then: #{
        required: #["units"],
        properties: #{ value: #{ type: "number" } },
      },
    },
    #{
      `if`: #{ properties: #{ operator: #{ `const`: "between" } } },
      then: #{
        required: #["units"],
        properties: #{
          value: #{
            type: "array",
            minItems: 2,
            maxItems: 2,
            items: #{ type: "number" },
          },
        },
      },
    },
    #{
      `if`: #{ properties: #{ operator: #{ `const`: "equals" } } },
      then: #{
        properties: #{ value: #{ type: #["number", "string", "boolean"] } },
      },
    },
    #{
      `if`: #{
        properties: #{
          operator: #{ `const`: "equals" },
          value: #{ type: "number" },
        },
      },
      then: #{ required: #["units"] },
    },
    #{
      `if`: #{ properties: #{ operator: #{ `const`: "one_of" } } },
      then: #{
        properties: #{
          value: #{
            type: "array",
            minItems: 1,
            uniqueItems: true,
            items: #{ type: #["string", "number"] },
          },
        },
      },
    }
  ]
)
model criterion {
  id?: semantic_id;

  /** what is measured or judged, such as service_temperature or clearance */
  property: semantic_id;

  /** > and < are strict: a value equal to the limit does not meet them */
  operator: ">=" | "<=" | ">" | "<" | "between" | "equals" | "one_of";

  value: unknown;
  units?: units;
  state?: dimension_state;
  source: source;
  conditions?: text;
  note?: text;
}

@oneOf
union criterion_or_unknown {
  criterion,
  fact_unknown,
}

/** What a statement, finding or evidence is about: the product, a part (with an optional occurrence, component, operation, feature and region), an interface or an assembly operation. Faces and solids are named semantically, never by persistent index */
@extension("minProperties", 1)
@extension(
  "anyOf",
  #[
    #{ required: #["product"] },
    #{ required: #["PN"] },
    #{ required: #["interface"] },
    #{ required: #["assembly_operation"] }
  ]
)
@extension(
  "dependentRequired",
  #{
    occurrence: #["PN"],
    component: #["PN"],
    operation: #["PN"],
    region: #["feature"],
  }
)
@extension("x-keyword-order", #["anyOf", "dependentRequired"])
model subject {
  product?: true;
  PN?: pn;
  occurrence?: occurrence_ref;
  component?: semantic_id;
  operation?: semantic_id;
  feature?: semantic_id;
  region?: semantic_id;
  `interface`?: interface_id;
  assembly_operation?: assembly_operation_id;
  requirements?: requirement_ids;
}

/** A feature of a part, by its semantic drawing-feature id, and optionally a region of it or the component it lies on */
model target {
  feature: semantic_id;
  region?: semantic_id;
  component?: semantic_id;
}

model load {
  id: semantic_id;
  kind: "static" | "sustained" | "cyclic" | "impact" | "vibration";

  /** a force (N, kN) or torque (N_mm, N_m) */
  magnitude: quantity_fact;

  /** The unit vector [x, y, z] along which the load acts (the force direction, or a torque's axis by the right-hand rule), in the model frame of the part that `application` names, or the assembly frame when `application` names the product, an interface or no part. Its norm must be 1 within 1e-6: validation reports load.direction_not_unit otherwise */
  @minItems(3)
  @maxItems(3)
  direction: float64[];

  application?: subject;
  duration?: quantity_fact;
  frequency?: quantity_fact;
  cycles?: quantity_fact;
  requirements?: requirement_ids;
  note?: text;
}

/** A check family, such as process.fdm.support or interface.fit */
@pattern("^[a-z][a-z0-9_]*(\\.[a-z0-9][a-z0-9_]*)*$")
scalar check_family extends string;

/** A stable finding code, such as process.fdm.overhang */
@pattern("^[a-z][a-z0-9_]*(\\.[a-z0-9][a-z0-9_]*)+$")
scalar finding_code extends string;

@doc("family@anchor: anchor is product, a PN with optional .component, /operation and #feature, an IF with optional #feature, a REQ, or op:<assembly operation>")
@pattern("^[a-z][a-z0-9_]*(\\.[a-z0-9][a-z0-9_]*)*@(product|[A-Z]{2,5}-[0-9]{4}(\\.[a-z][a-z0-9_]*)?(/[a-z][a-z0-9_]*)?(#[a-z][a-z0-9_]*)?|IF-[0-9]{3}(#[a-z][a-z0-9_]*)?|REQ-[0-9]{3}|op:[a-z][a-z0-9_-]*)$")
scalar obligation_id extends string;

/** One expected check, enumerated by manufacturing_intent.required_checks before any producer runs */
model obligation {
  id: obligation_id;
  family: check_family;
  subject: subject;
  level: evidence_level;

  /** the earliest workflow stage at which the obligation is due */
  stage: stage;

  /** why it is required: the route kind, function, interface, requirement or service input it derives from */
  basis: text;

  requirement?: requirement_id;
  criterion?: semantic_id;
}

model file_hash {
  /** project-relative, under hw/ */
  path: project_path;

  sha256: sha256;
}

/** One immutable producer finding: subject and severity, the measured value with units or why it is unknown, the criterion and its source, the method and evidence, uncertainty, functional consequence, remedy with alternatives, and the recheck it needs */
@extension(
  "allOf",
  #[
    #{
      `if`: #{ properties: #{ outcome: #{ `enum`: #["fail", "unknown"] } } },
      then: #{ required: #["remedy"] },
    },
    #{ $ref: "#/$defs/not_assessed_rule" }
  ]
)
model finding {
  id: semantic_id;
  code: finding_code;
  obligation?: obligation_id;
  subject: subject;
  severity: severity;
  outcome: outcome;
  reason?: not_assessed_reason;

  @oneOf
  measured:
    | quantity
    | {
        text: text;
      }
    | fact_unknown;

  criterion: criterion_or_unknown;
  requirements?: requirement_ids;
  method: {
    name: text;
    tool?: text;

    @minItems(1)
    evidence?: file_hash[];
  };

  /** the uncertainty or the missing information */
  uncertainty: text;

  assumptions?: texts;
  coverage?: text;

  /** the functional consequence */
  consequence: text;

  remedy?: text;

  @minItems(1)
  alternatives?: {
    text: text;
    tradeoffs: text;
  }[];

  recheck: {
    @minItems(1)
    @uniqueItems
    families: check_family[];

    @minItems(1)
    scope?: subject[];

    inputs?: texts;
    earliest_stage: stage;
  };

  @minItems(1)
  @uniqueItems
  decisions?: decision[];
}

@extension("allOf", #[#{ $ref: "#/$defs/not_assessed_rule" }])
model obligation_outcome {
  obligation: obligation_id;
  outcome: outcome;
  reason?: not_assessed_reason;
  level?: evidence_level;
  method: text;
  source?: source;
  uncertainty?: text;

  /** what the method covered, and what it did not */
  coverage: text;

  findings?: semantic_ids;
}

/** An explicit, scoped, justified and approved waiver: its exact subject, criterion and operating envelope, its expiry or the change that ends it, the reason, the consequence and the approving authority and decision. A waived obligation stays waived, never pass, and no waiver overrides a governing safety or regulatory requirement or a forbidden geometry failure */
@extension(
  "anyOf",
  #[#{ required: #["valid_until"] }, #{ required: #["until_change"] }]
)
model waiver {
  decision: decision;
  subject: subject;
  obligation?: obligation_id;
  criterion: text;
  operating_envelope: text;
  valid_until?: date;
  until_change?: text;
  reason: text;
  consequence: text;
  authority: text;
}

/** A built version label */
@pattern("^v[1-9][0-9]*$")
scalar version extends string;

/** A part revision: X1, X2… while prototype, then a release letter (no I, O, Q, S, X, Z) */
@pattern("^(X[1-9][0-9]*|[A-HJ-NPRTUVWY])$")
scalar revision extends string;

/** A file path relative to the project root, under hw/, with no . or .. segment */
@pattern("^hw/[^\\\\]+$")
@extension("not", #{ pattern: "/\\.{1,2}(/|$)" })
scalar project_path extends string;

/** A flow gate id; flow.yaml names the gates */
@pattern("^[a-z][a-z0-9_]*$")
scalar gate_id extends string;

@@example(
  Common,
  #{ status: "unknown", reason: "not recorded yet", question: "Q-001" }
);
@@example(Common, "LMP-0001");
@@example(Common, "DR-004");
