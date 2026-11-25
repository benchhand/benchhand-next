import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/product/")
namespace Records.Product;

@summary("benchhand product record (hw/product.yaml)")
@id("https://benchhand.github.io/benchhand/contracts/record/product.schema.json")
@extension("x-version", "1.0.0")
model Product {
  record_version: Common.record_version;

  @minLength(1)
  @pattern("^[a-z0-9][a-z0-9-]*$")
  id: string;

  units: "mm";
  regime: ProductRegime;

  /** The general tolerance a drawing states for dimensions without their own: a linear value in mm or a standard label such as ISO 2768-m. A tunable, so it defaults to ISO 2768-m and the user changes it. Unknown, with the open question that would settle it, is also valid; validation refuses a drawing while it is unknown */
  @oneOf
  general_tolerance:
    |
        /** a linear value in mm */
        @minValueExclusive(0)
        @maxValue(5)
        @extension("x-plausible", #{ min: 0.01, max: 0.5 })
        scalar extends float64
    | ProductGeneralTolerance1
    | Common.fact_unknown = ProductGeneralTolerance1("ISO 2768-m");

  /** Explicit SPDX license expressions approved for the product's hardware and documentation, such as CERN-OHL-S-2.0 or (MIT OR Apache-2.0); omitted means not recorded. The expression's shape is meant to be checked (identifiers, LicenseRef-, +, WITH, AND, OR, parentheses) but bundles no SPDX license list, so an unlisted identifier such as CERN-OHL-S passes */
  @minProperties(1)
  license?: {
    @minLength(1)
    hardware?: string;

    @minLength(1)
    documentation?: string;
  };

  @extension("dependentRequired", #{ change: #["frozen"] })
  flow: {
    stage: Common.stage;
    recheck_from: Common.stage;
    frozen?: frozen;
    change?: change;
    profile?: product_profile;
  };

  /** A printer envelope for the legacy build-volume diagnostic. The sizes are facts about the machine, not tunables, so they have no default: they come from the active capability profile's envelope. Margin is a tunable. Fitting it is not printability; a capability profile's envelope and an approved orientation govern manufacturability */
  build_volume?: {
    @minValueExclusive(0)
    @maxValue(2000)
    @extension("x-plausible", #{ min: 20, max: 500 })
    x_mm: float64;

    @minValueExclusive(0)
    @maxValue(2000)
    @extension("x-plausible", #{ min: 20, max: 500 })
    y_mm: float64;

    @minValueExclusive(0)
    @maxValue(2000)
    @extension("x-plausible", #{ min: 20, max: 500 })
    z_mm: float64;

    @minItems(1)
    @uniqueItems
    orientations?: ProductBuildVolumeOrientationsItem[];

    /** Unusable rim on each side, in mm; at most half the smallest side, which the config loader checks */
    @minValue(0)
    @maxValue(1000)
    @extension("x-plausible", #{ max: 20 })
    margin_mm?: float64 = 0;
  };

  /** Product-wide design rules */
  design?: {
    /** Margin above each clearance requirement's minimum (default 0.1); a distance at or above the minimum but below minimum + margin is a margin warning, never a failure. A clearance interface's margin_mm overrides it */
    @minValue(0)
    @maxValue(1)
    @extension("x-plausible", #{ max: 0.5 })
    clearance_margin_mm?: float64 = 0.1;
  };

  /** Product-wide manufacturing plan and rules */
  manufacturing?: {
    /** The processes planned at INTENT, before any part record exists */
    @minItems(1)
    @uniqueItems
    processes?: Common.primary_process[];

    /** Minimum wall per made-part process, overriding the form check's built-in defaults. A diagnostic heuristic, never a calibrated capability */
    @minProperties(1)
    min_wall_mm?: {
      @minValue(0.2)
      @maxValue(25)
      @extension("x-plausible", #{ min: 0.4, max: 3 })
      fdm?: float64 = 1.2;

      /** A fact of the shop, not a tunable, so it has no default: it comes from the CNC capability profile and stays UNKNOWN until one exists */
      @minValue(0.2)
      @maxValue(25)
      @extension("x-plausible", #{ min: 0.4, max: 3 })
      cnc?: float64;
    };
  };

  /** Repository storage choices the user made */
  storage?: {
    /** Whether generated results (STEP, GLB, renders, check bundles) are tracked in git; absent means the user has not been asked */
    results_in_git?: boolean;
  };

  drawing?: Drawing.product_drawing;
  use_case: use_case;
}

@extension("x-inline", true)
enum ProductRegime {
  iso,
  asme,
}

@extension("x-inline", true)
@minLength(1)
scalar ProductGeneralTolerance1 extends string;

@extension("x-inline", true)
enum ProductBuildVolumeOrientationsItem {
  xyz,
  xzy,
  yxz,
  yzx,
  zxy,
  zyx,
}

/** The ISO/ASTM 52900 additive process category of a flow.profile process, null for a subtractive or forming process */
union iso_52900_category {
  "mex",
  "pbf",
  "vpp",
  "bjt",
  "ded",
  "mjt",
  "shl",
  null,
}

@id("https://benchhand.github.io/benchhand/contracts/record/product/limit.json")
@oneOf
union product_limit {
  ProductProductLimit0,
  ProductProductLimit1,
}

@extension("x-inline", true)
@minValueExclusive(0)
scalar ProductProductLimit0 extends float64;

@extension("x-inline", true)
enum ProductProductLimit1 {
  calibrated,
  off,
}

@oneOf
union clearance {
  ProductClearance0,
  ProductClearance1,
}

@extension("x-inline", true)
@minValueExclusive(0)
scalar ProductClearance0 extends float64;

@extension("x-inline", true)
enum ProductClearance1 {
  calibrated,
}

/** Whether and how FEA runs, the shape agreed with package A. mode is required when enabled. fast escalates a case to accurate when the fast result lies within fast_band_pct of its criterion limit, |limit - result| / limit x 100 <= fast_band_pct; without fast_band_pct, the analysis uses its measured default band, twice the worst-case bias. */
@extension(
  "allOf",
  #[
    #{
      `if`: #{ properties: #{ enabled: #{ `const`: true } } },
      then: #{ required: #["mode"] },
      `else`: #{
        not: #{
          anyOf: #[#{ required: #["mode"] }, #{ required: #["fast_band_pct"] }],
        },
      },
    },
    #{
      `if`: #{ required: #["fast_band_pct"] },
      then: #{
        required: #["mode"],
        properties: #{ mode: #{ `const`: "fast" } },
      },
    }
  ]
)
model fea {
  enabled: boolean = true;
  mode?: ProductFeaMode = ProductFeaMode.accurate;

  @minValueExclusive(0)
  @maxValue(50)
  fast_band_pct?: float64;
}

@extension("x-inline", true)
enum ProductFeaMode {
  fast,
  accurate,
}

/** The user's answers to the project-start questions , recorded at INTENT with the decision that holds them. Each question has a default the user is shown; asked records, per question, whether the user answered (user) or accepted the default (asked-accepted-default). A number is the user's design limit; calibrated stays unknown until a calibration exists; off means not assessed. A two-state answer is a boolean; a word answer is a string, written quoted, since YAML reads a bare on, off, yes or no as a boolean */
@id("https://benchhand.github.io/benchhand/contracts/record/product/profile.json")
model product_profile {
  decision?: Common.decision;
  fea: fea;

  /** auto turns on when SPECIFY names a critical interface or a stack case */
  stack_up: ProductProductProfileStackUp = ProductProductProfileStackUp.auto;

  /** light: both reviewers at the L2 light-review scope, rerun on the analysed version */
  critique: ProductProductProfileCritique = ProductProductProfileCritique.full;

  /** auto: on once a joint moves; stated to the user, never asked */
  motion: ProductProductProfileMotion = ProductProductProfileMotion.auto;

  storage_results_in_git: boolean = false;

  /** How each project-start question was settled, keyed by its field path below flow.profile (fea, stack_up, processes/fdm/orientation, processes/fdm/pip_clearance_mm/xy, ...) */
  asked?: Record<"user" | "asked-accepted-default">;

  processes: {
    fdm?: fdm_profile;
  };
}

@extension("x-inline", true)
enum ProductProductProfileStackUp {
  auto,
  on,
  off,
}

@extension("x-inline", true)
enum ProductProductProfileCritique {
  full,
  light,
  off,
}

@extension("x-inline", true)
enum ProductProductProfileMotion {
  auto,
}

model fdm_profile {
  orientation: ProductFdmProfileOrientation = ProductFdmProfileOrientation.user;
  supports: ProductFdmProfileSupports = ProductFdmProfileSupports.allowed;

  @oneOf
  overhang_deg:
    | @minValueExclusive(0) @maxValueExclusive(90) scalar extends float64
    | ProductFdmProfileOverhangDeg1 = ProductFdmProfileOverhangDeg1.calibrated;

  bridge_mm: product_limit = ProductProductLimit1.calibrated;
  min_wall_mm: product_limit = ProductProductLimit1.calibrated;
  min_feature_mm: product_limit = ProductProductLimit1.calibrated;
  warp: ProductFdmProfileWarp = ProductFdmProfileWarp.calibrated;

  /** true adds the critical-surface role cosmetic, which supports may not touch */
  cosmetic_faces: boolean = false;

  /** true: offer to print hinges and joints already assembled where that fits; false: assemble them */
  print_in_place: boolean = false;

  /** The smallest print-in-place gap that separates, across the layers (xy) and between layers (z) */
  pip_clearance_mm: {
    xy: clearance = ProductClearance1.calibrated;
    z: clearance = ProductClearance1.calibrated;
  };
}

@extension("x-inline", true)
enum ProductFdmProfileOrientation {
  user,
  propose,
}

@extension("x-inline", true)
enum ProductFdmProfileSupports {
  allowed,
  free,
  off,
}

@extension("x-inline", true)
enum ProductFdmProfileOverhangDeg1 {
  calibrated,
  off,
}

@extension("x-inline", true)
enum ProductFdmProfileWarp {
  calibrated,
  off,
}

/** The frozen configuration: the built version the design_freeze gate approved, its manifest sha256 and the approving decision. Once set, layout findings stay blocking at every stage. A freeze also anchors evidence_sha256, the canonical digest of its acceptance inventory (verification, evidence and finding dispositions, relied-on bundle manifests and source bytes); a freeze without it is refused by a release until a new freeze records one. */
model frozen {
  version: Common.version;
  manifest_sha256: Common.sha256;
  decision: Common.decision;
  evidence_sha256?: Common.sha256;
}

/** An approved engineering change against the frozen baseline, while it is open */
model change {
  decision: Common.decision;
  baseline_version: Common.version;

  @minItems(1)
  @uniqueItems
  affected_parts: Common.pn[];
}

/** What the product must actually do, recorded before any process or material is chosen. Every field is a fact: known with its sources, unknown with the open question that would answer it, or not applicable. confirmed needs the approving decision; a service class never replaces governing safety or regulatory policy */
@extension("if", #{ properties: #{ status: #{ `const`: "confirmed" } } })
@extension("then", #{ required: #["decision"] })
model use_case {
  status: "unknown" | "draft" | "confirmed";
  decision?: Common.decision;

  @extension(
    "oneOf",
    #[
      #{
        allOf: #[
          #{ $ref: "common.schema.json#/$defs/fact_known" },
          #{
            properties: #{
              value: #{ $ref: "common.schema.json#/$defs/service_class" },
            },
          }
        ],
      },
      #{ $ref: "common.schema.json#/$defs/fact_unknown" }
    ]
  )
  service_class: unknown;

  purpose: Common.text_fact;
  users: Common.text_fact;
  environment: {
    /** the operating temperature range, deg_C */
    temperature: Common.quantity_fact;

    heat_sources: Common.text_fact;
    moisture: Common.text_fact;
    chemicals: Common.text_fact;
    uv: Common.text_fact;
    corrosion: Common.text_fact;
  };

  @oneOf
  loads: ProductUseCaseLoads0 | Common.fact_open;

  motion: {
    speed: Common.quantity_fact;
    range: Common.quantity_fact;
    duty_cycle: Common.text_fact;
    friction: Common.text_fact;
    wear: Common.text_fact;
    service_life: Common.quantity_fact;
  };

  /** Required accuracy: these are requirements, never manufacturing capability */
  accuracy: {
    tolerance: Common.text_fact;
    repeatability: Common.text_fact;
    surface_finish: Common.text_fact;
    dimensional_stability: Common.text_fact;
  };

  consequences: {
    failure: Common.text_fact;

    @extension(
      "oneOf",
      #[
        #{
          allOf: #[
            #{ $ref: "common.schema.json#/$defs/fact_known" },
            #{
              properties: #{
                value: #{
                  $ref: "common.schema.json#/$defs/consequence_severity",
                },
              },
            }
          ],
        },
        #{ $ref: "common.schema.json#/$defs/fact_unknown" }
      ]
    )
    severity: unknown;

    forbidden_outcomes: Common.texts_fact;
    standards: Common.texts_fact;
    supervision: Common.text_fact;
    approval_authority: Common.text_fact;
  };
  logistics: {
    /** how many, in count */
    quantity: Common.quantity_fact;

    budget: Common.money_fact;
    lead_time: Common.quantity_fact;
    maintenance: Common.text_fact;
    repair: Common.text_fact;
  };

  /** What is available to make it. Availability is not a requirement */
  capability: {
    @oneOf
    equipment: ProductUseCaseCapabilityEquipment0 | Common.fact_open;

    operator: Common.text_fact;
    outsourcing: Common.text_fact;
  };

  release_scope: {
    purpose: Common.text_fact;
    operating_limits: Common.texts_fact;
    exclusions: Common.texts_fact;
  };

  @oneOf
  evidence_policy:
    | Common.fact_unknown
    | {
        @minItems(1)
        obligations: ProductUseCaseEvidencePolicy1ObligationsItem[];

        decision: Common.decision;
      };
}

@extension("x-inline", true)
@minItems(1)
model ProductUseCaseLoads0 is Common.load[];

@extension("x-inline", true)
@minItems(1)
@uniqueItems
model ProductUseCaseCapabilityEquipment0 is Common.profile_id[];

@extension("x-inline", true)
@extension(
  "anyOf",
  #[#{ required: #["requirement"] }, #{ required: #["subject"] }]
)
model ProductUseCaseEvidencePolicy1ObligationsItem {
  requirement?: Common.requirement_id;
  subject?: Common.subject;
  level: Common.evidence_level;
  note?: Common.text;
}

@@example(
  Product,
  #{
    record_version: 3,
    id: "example-product",
    units: "mm",
    regime: ProductRegime.iso,
    general_tolerance: #{
      status: "unknown",
      reason: "not recorded yet",
      question: "Q-013",
    },
    flow: #{ stage: Common.stage.ground, recheck_from: Common.stage.ground },
    use_case: #{
      status: "unknown",
      service_class: #{
        status: "unknown",
        reason: "not recorded yet",
        question: "Q-001",
      },
      purpose: #{
        status: "unknown",
        reason: "not recorded yet",
        question: "Q-002",
      },
      users: #{
        status: "unknown",
        reason: "not recorded yet",
        question: "Q-002",
      },
      environment: #{
        temperature: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-003",
        },
        heat_sources: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-003",
        },
        moisture: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-004",
        },
        chemicals: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-004",
        },
        uv: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-004",
        },
        corrosion: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-004",
        },
      },
      loads: #{
        status: "unknown",
        reason: "not recorded yet",
        question: "Q-005",
      },
      motion: #{
        speed: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-006",
        },
        range: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-006",
        },
        duty_cycle: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-006",
        },
        friction: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-006",
        },
        wear: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-006",
        },
        service_life: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-006",
        },
      },
      accuracy: #{
        tolerance: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-007",
        },
        repeatability: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-007",
        },
        surface_finish: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-007",
        },
        dimensional_stability: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-007",
        },
      },
      consequences: #{
        failure: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-008",
        },
        severity: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-008",
        },
        forbidden_outcomes: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-008",
        },
        standards: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-008",
        },
        supervision: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-008",
        },
        approval_authority: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-008",
        },
      },
      logistics: #{
        quantity: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-009",
        },
        budget: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-009",
        },
        lead_time: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-009",
        },
        maintenance: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-009",
        },
        repair: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-009",
        },
      },
      capability: #{
        equipment: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-010",
        },
        operator: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-010",
        },
        outsourcing: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-010",
        },
      },
      release_scope: #{
        purpose: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-011",
        },
        operating_limits: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-011",
        },
        exclusions: #{
          status: "unknown",
          reason: "not recorded yet",
          question: "Q-011",
        },
      },
      evidence_policy: #{
        status: "unknown",
        reason: "not recorded yet",
        question: "Q-011",
      },
    },
  }
);
@@example(
  Product,
  #{
    id: "lamp-arm",
    units: "mm",
    regime: ProductRegime.iso,
    general_tolerance: "ISO 2768-m",
    build_volume: #{
      x_mm: 256,
      y_mm: 256,
      z_mm: 256,
      margin_mm: 5,
      orientations: #[
        ProductBuildVolumeOrientationsItem.xyz,
        ProductBuildVolumeOrientationsItem.xzy,
        ProductBuildVolumeOrientationsItem.yxz,
        ProductBuildVolumeOrientationsItem.yzx,
        ProductBuildVolumeOrientationsItem.zxy,
        ProductBuildVolumeOrientationsItem.zyx
      ],
    },
    flow: #{
      stage: Common.stage.layout,
      recheck_from: Common.stage.layout,
      profile: #{
        decision: "DR-010",
        fea: #{ enabled: false },
        stack_up: ProductProductProfileStackUp.auto,
        critique: ProductProductProfileCritique.light,
        motion: ProductProductProfileMotion.auto,
        storage_results_in_git: false,
        processes: #{
          fdm: #{
            orientation: ProductFdmProfileOrientation.propose,
            supports: ProductFdmProfileSupports.allowed,
            overhang_deg: ProductFdmProfileOverhangDeg1.calibrated,
            bridge_mm: ProductProductLimit1.calibrated,
            min_wall_mm: ProductProductLimit1.calibrated,
            min_feature_mm: ProductProductLimit1.calibrated,
            warp: ProductFdmProfileWarp.calibrated,
            cosmetic_faces: false,
            print_in_place: false,
            pip_clearance_mm: #{
              xy: ProductClearance1.calibrated,
              z: ProductClearance1.calibrated,
            },
          },
        },
        asked: #{
          fea: "user",
          stack_up: "user",
          critique: "user",
          storage_results_in_git: "user",
          `processes/fdm/orientation`: "user",
          `processes/fdm/supports`: "user",
          `processes/fdm/overhang_deg`: "user",
          `processes/fdm/bridge_mm`: "user",
          `processes/fdm/min_wall_mm`: "user",
          `processes/fdm/min_feature_mm`: "user",
          `processes/fdm/warp`: "user",
          `processes/fdm/cosmetic_faces`: "user",
          `processes/fdm/print_in_place`: "user",
          `processes/fdm/pip_clearance_mm/xy`: "asked-accepted-default",
          `processes/fdm/pip_clearance_mm/z`: "asked-accepted-default",
        },
      },
    },
    drawing: #{
      definition: "model_and_drawing",
      `projection`: Drawing.DrawingProductDrawingProjection.first_angle,
      standards: #{
        dimensioning: "ISO 129-1:2018",
        geometrical_tolerancing: "ISO 1101:2017",
        datums: "ISO 5459:2024",
        gps_fundamentals: "ISO 8015:2011",
        general_tolerances: "ISO 2768-1:1989",
        fits: "ISO 286-1:2010",
        edges: "ISO 13715:2017",
        surface_texture: "ISO 21920-1:2021",
        threads: "ISO 6410-1:1993",
        sheets: "ISO 5457:1999",
      },
      default_sheet: #{
        sizes: #["A4", "A3", "A2"],
        orientation: "landscape",
        scale: "auto",
      },
      tolerance_policies: #{
        machining: #{
          kind: "standard",
          standard: "ISO 2768-1:1989",
          class: Drawing.DrawingTolerancePolicy0Class.m,
          applies_to: #["cnc"],
        },
        fdm_bureau: #{
          kind: "limits",
          linear_mm: 0.2,
          angular_deg: 1,
          applies_to: #["fdm"],
          reference: "FDM bureau capability +/-0.2 mm, +/-1 deg (DR-004)",
        },
      },
      general_tolerance_policy: "machining",
    },
    record_version: 3,
    use_case: #{
      status: "unknown",
      service_class: #{
        status: "unknown",
        reason: "not recorded before record version 2",
        question: "Q-001",
      },
      purpose: #{
        status: "unknown",
        reason: "not recorded before record version 2",
        question: "Q-002",
      },
      users: #{
        status: "unknown",
        reason: "not recorded before record version 2",
        question: "Q-002",
      },
      environment: #{
        temperature: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-003",
        },
        heat_sources: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-003",
        },
        moisture: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-004",
        },
        chemicals: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-004",
        },
        uv: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-004",
        },
        corrosion: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-004",
        },
      },
      loads: #{
        status: "unknown",
        reason: "not recorded before record version 2",
        question: "Q-005",
      },
      motion: #{
        speed: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-006",
        },
        range: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-006",
        },
        duty_cycle: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-006",
        },
        friction: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-006",
        },
        wear: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-006",
        },
        service_life: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-006",
        },
      },
      accuracy: #{
        tolerance: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-007",
        },
        repeatability: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-007",
        },
        surface_finish: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-007",
        },
        dimensional_stability: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-007",
        },
      },
      consequences: #{
        failure: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-008",
        },
        severity: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-008",
        },
        forbidden_outcomes: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-008",
        },
        standards: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-008",
        },
        supervision: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-008",
        },
        approval_authority: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-008",
        },
      },
      logistics: #{
        quantity: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-009",
        },
        budget: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-009",
        },
        lead_time: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-009",
        },
        maintenance: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-009",
        },
        repair: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-009",
        },
      },
      capability: #{
        equipment: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-010",
        },
        operator: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-010",
        },
        outsourcing: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-010",
        },
      },
      release_scope: #{
        purpose: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-011",
        },
        operating_limits: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-011",
        },
        exclusions: #{
          status: "unknown",
          reason: "not recorded before record version 2",
          question: "Q-011",
        },
      },
      evidence_policy: #{
        status: "unknown",
        reason: "not recorded before record version 2",
        question: "Q-011",
      },
    },
  }
);
