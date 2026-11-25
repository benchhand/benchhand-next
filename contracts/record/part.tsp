import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/part/")
namespace Records.Part;

/** One part's record, hw/parts/<PN>/part.yaml: identity and revision, material, process and finish, whether it is made or bought, its drawing, how it is manufactured, and its design intent. */
@summary("benchhand part record (hw/parts/<PN>/part.yaml)")
@id("https://benchhand.github.io/benchhand/contracts/record/part.schema.json")
@extension("x-version", "1.0.0")
model Part {
  PN: Common.pn;
  rev: Common.revision;

  @minLength(1)
  title: string;

  /** A declaration of the part's material, kept for BOM and drawings; it is not a sourced grade or property. intent.material_profile names the qualified profile */
  @minLength(1)
  material: string;

  /** The scalar label of the primary process; intent.route is the authority for the operations */
  process: Common.primary_process;

  @minLength(1)
  finish: string;

  /** grams */
  @minValueExclusive(0)
  @maxValue(10000000)
  @extension("x-plausible", #{ max: 50000 })
  mass_target: float64 | null;

  make_buy: PartMakeBuy;

  @minLength(1)
  supplier?: string | null;

  @uniqueItems
  decisions?: Common.decision[];

  /** Frame of model.py's geometry: assembly_zero (default) is assembly coordinates at the zero joint pose, one identity-placed occurrence only; part_local is the definition's own origin and axes, placed by each occurrence */
  model_frame?: PartModelFrame;

  /** The part's form type for the form check; absent means solid, and only a solid part is judged block_like */
  form_class?: enum {
    solid,
    frame,
    plate,
    skeleton,
    shell,
  };

  transparency?: PartTransparency;
  procurement?: Drawing.procurement;
  drawing?: Drawing.part_drawing;

  /** How a custom-made part is manufactured relative to its installed definition. Absent: relationship same, compared to 1e-9 relative volume, default mesh. */
  @extension(
    "if",
    #{ properties: #{ relationship: #{ `const`: "different" } } }
  )
  @extension(
    "then",
    #{
      required: #["state", "reason", "decision"],
      anyOf: #[
        #{ required: #["volume_rel_tolerance"] },
        #{ required: #["volume_abs_tolerance_mm3"] }
      ],
    }
  )
  @extension(
    "else",
    #{
      not: #{
        anyOf: #[
          #{ required: #["state"] },
          #{ required: #["reason"] },
          #{ required: #["decision"] },
          #{ required: #["volume_rel_tolerance"] },
          #{ required: #["volume_abs_tolerance_mm3"] }
        ],
      },
    }
  )
  manufacture?: {
    /** same: made in its installed shape; different: model.py build_manufacture(params) defines the manufacturing state */
    relationship: "same" | "different";

    /** name of the manufacturing state, such as flat */
    @pattern("^[a-z][a-z0-9_]*$")
    state?: string;

    /** why the states differ, such as elastic_bending */
    @pattern("^[a-z][a-z0-9_]*$")
    reason?: string;

    /** the decision record approving the difference */
    decision?: Common.decision;

    /** allowed |V_manufactured - V_installed| / V_installed */
    @minValueExclusive(0)
    @maxValue(0.1)
    @extension("x-plausible", #{ max: 0.01 })
    volume_rel_tolerance?: float64;

    /** absolute floor of the allowed volume difference */
    @minValueExclusive(0)
    @maxValue(1000)
    @extension("x-plausible", #{ max: 10 })
    volume_abs_tolerance_mm3?: float64;

    /** FDM part.stl tessellation, overriding the layout default (0.05 mm, 0.1 rad) */
    @minProperties(1)
    mesh?: {
      @minValue(0.001)
      @maxValue(1)
      @extension("x-plausible", #{ min: 0.01, max: 0.2 })
      linear_deflection_mm?: float64 = 0.05;

      @minValueExclusive(0)
      @maxValue(3.141592653589793)
      @extension("x-plausible", #{ min: 0.05, max: 0.5 })
      angular_deflection_rad?: float64 = 0.1;
    };
  };

  intent?: intent;
}

@extension("x-inline", true)
enum PartMakeBuy {
  make,
  buy,
}

@extension("x-inline", true)
enum PartModelFrame {
  assembly_zero,
  part_local,
}

/** How much light the part passes; absent means opaque. Only a transparent part is see-through to the visibility check. An optical requirement is a hard selection constraint met by a purchased transparent part or identified transparent stock on a suitable route, never by an opaque process */
@extension("x-inline", true)
enum PartTransparency {
  opaque,
  translucent,
  transparent,
}

/** Record version 2 manufacturing intent: what the part does, the qualified material profile, the service it sees, its critical surfaces and its complete ordered route. make_buy and procurement.mode stay the sourcing authority; manufacture stays the manufacturing-state authority. A sole solid is the implicit main component; a part with several solids lists components */
model intent {
  @oneOf
  functions: PartIntentFunctions0 | Common.fact_unknown;

  /** a profile id in manufacturing/materials.yaml */
  @oneOf
  material_profile: Common.profile_id | Common.fact_open;

  /** The part's print colour as an sRGB hex string #RRGGBB (for example #FF8000 for orange). 3MF export uses it as the part's display colour */
  @maxLength(7)
  @pattern("^#[0-9A-Fa-f]{6}$")
  color?: string;

  /** the selection.yaml candidate this intent implements */
  selection?: Common.semantic_id;

  @oneOf
  service: PartIntentService0 | Common.fact_open;

  @minItems(1)
  components?: component[];

  @oneOf
  critical_surfaces: PartIntentCriticalSurfaces0 | Common.fact_open;

  @oneOf
  route: PartIntentRoute0 | Common.fact_unknown;

  @minProperties(1)
  rationale?: {
    decision?: Common.decision;
    selection?: Common.semantic_id;
    alternatives?: Common.texts;
    tradeoffs?: Common.text;
  };
}

@extension("x-inline", true)
@minItems(1)
model PartIntentFunctions0 is Common.function_entry[];

@extension("x-inline", true)
@extension("minProperties", 1)
model PartIntentService0 {
  requirements?: Common.requirement_ids;

  /** product.yaml use_case.loads ids */
  loads?: Common.semantic_ids;

  environment?: Common.text;
  duty?: Common.text;
  life?: Common.quantity_fact;

  /** where this part's service differs from the product use case */
  differences?: Common.text;
}

@extension("x-inline", true)
@minItems(1)
model PartIntentCriticalSurfaces0 is critical_surface[];

@extension("x-inline", true)
@minItems(1)
model PartIntentRoute0 is operation[];

/** One disconnected solid of the part, bound by an interior witness point in the native manufacturing frame (mm) or a semantic locator; every solid binds exactly once. Equivalent members list their multiplicity */
@extension("oneOf", #[#{ required: #["witness"] }, #{ required: #["locator"] }])
@extension("x-keyword-order", #["oneOf", "properties"])
model component {
  id: Common.semantic_id;
  witness?: Common.vector;
  locator?: Common.target;

  @oneOf
  material_profile?: Common.profile_id | Common.fact_open;

  @minItems(1)
  functions?: Common.function_entry[];

  @minValue(1)
  multiplicity?: integer;

  note?: Common.text;
}

model critical_surface {
  id: Common.semantic_id;
  feature: Common.semantic_id;
  region?: Common.semantic_id;
  component?: Common.semantic_id;
  role:
    | "datum"
    | "bore"
    | "seat"
    | "journal"
    | "running"
    | "sliding"
    | "flank"
    | "cam"
    | "seal"
    | "fastener"
    | "locating"
    | "optical"
    | "other";

  @minItems(1)
  @uniqueItems
  interfaces?: Common.interface_id[];

  requirements?: Common.requirement_ids;

  @minItems(1)
  criteria?: Common.criterion[];

  finish?: Common.text;

  /** the route inspection id that verifies it */
  inspection?: Common.semantic_id;

  dimension_state: Common.dimension_state;
}

/** One route operation, in route order: the previous operation is its predecessor unless depends_on names the true dependencies. A made operation names its capability profile or why it is unknown; a purchase names its identity, specification and ratings */
@extension("if", #{ properties: #{ kind: #{ `const`: "purchased" } } })
@extension(
  "then",
  #{
    required: #["purchase"],
    not: #{
      anyOf: #[
        #{ required: #["capability"] },
        #{ required: #["supports"] },
        #{ required: #["orientation"] }
      ],
    },
  }
)
@extension(
  "else",
  #{ required: #["capability"], not: #{ required: #["purchase"] } }
)
model operation {
  id: Common.semantic_id;
  kind: Common.route_kind;
  title?: Common.text;

  @oneOf
  capability?: Common.profile_id | Common.fact_unknown;

  provider?: "local" | "outsourced";
  supplier?: Common.text;
  components?: Common.semantic_ids;
  depends_on?: Common.semantic_ids;

  /** stock, or the output_state of an earlier operation */
  input_state?: Common.semantic_id;

  /** installed, part.yaml manufacture.state, or an intermediate state */
  output_state?: Common.semantic_id;

  material_state_in?: Common.text;
  material_state_out?: Common.text;

  @minItems(1)
  targets?: Common.target[];

  setup?: setup;

  @oneOf
  orientation?: orientation | Common.fact_open;

  @oneOf
  supports?: supports | Common.fact_open;

  @minItems(1)
  allowances?: allowance[];

  post_processing?: Common.texts;

  @minItems(1)
  inspection?: inspection[];

  requirements?: Common.requirement_ids;

  @minItems(1)
  criteria?: Common.criterion[];

  @minItems(1)
  @uniqueItems
  evidence?: Common.evidence_id[];

  purchase?: purchase;
}

/** Traceable purchase criteria: the identity, specification and ratings that make a bought item the right one, never an unidentified description */
model purchase {
  /** manufacturer and part number, or a standard designation */
  identity: Common.text_fact;

  /** material grade, standard or datasheet the item conforms to */
  specification: Common.text_fact;

  /** load, speed, temperature or other ratings */
  ratings: Common.text_fact;

  /** optical grade and transmission, for a transparent item */
  optical?: Common.text_fact;

  thickness?: Common.quantity_fact;
  availability?: Common.text_fact;
  supplier_evidence?: Common.sources;
}

/** Stock, datums, workholding and access of one operation. Nothing here is guessed from a bounding box */
@extension("minProperties", 1)
model setup {
  @minProperties(1)
  stock?: {
    @oneOf
    material_profile?: Common.profile_id | Common.fact_open;

    grade?: Common.text_fact;
    form?: Common.text_fact;
    dimensions?: Common.text_fact;
    thickness?: Common.quantity_fact;
    state?: Common.text;
    supplier?: Common.text;
  };

  datums?: Common.semantic_ids;
  workholding?: {
    method: Common.text_fact;

    @minItems(1)
    contact_regions?: Common.target[];

    fixture?: Common.text;
    clamping_force?: Common.quantity_fact;
    allowable_deformation?: Common.quantity_fact;
  };

  @minProperties(1)
  access?: {
    sides?: Common.texts;

    @minItems(1)
    tools?: {
      description: Common.text;
      capability?: Common.profile_id;
      diameter?: Common.quantity_fact;
      reach?: Common.quantity_fact;
      holder?: Common.text_fact;
    }[];
  };

  inspection_access?: Common.text_fact;
}

/** The fixed manufacturing orientation in the native manufacture frame: a proper rotation, as a unit quaternion [w, x, y, z] or an axis and angle. An approved orientation names its decision; an envelope auto-fit is never approved */
@extension("if", #{ properties: #{ status: #{ `const`: "approved" } } })
@extension("then", #{ required: #["decision"] })
model orientation {
  status: "proposed" | "approved";

  @oneOf
  rotation:
    | {
        @minItems(4)
        @maxItems(4)
        quaternion: float64[];
      }
    | {
        axis: Common.vector;
        angle_deg: float64;
      };

  decision?: Common.decision;
  selection?: Common.semantic_id;
  note?: Common.text;
}

/** Where supports start, touch and come off. reachable_noncritical keeps them on reachable non-critical surfaces; finished_critical names the finishing, allowance and inspection that restore a critical surface. Absent supports are unknown, never none */
@extension(
  "allOf",
  #[
    #{
      `if`: #{
        properties: #{ strategy: #{ `const`: "reachable_noncritical" } },
      },
      then: #{ required: #["contact_regions", "removal"] },
    },
    #{
      `if`: #{ properties: #{ strategy: #{ `const`: "finished_critical" } } },
      then: #{
        required: #[
          "contact_regions",
          "removal",
          "allowance",
          "finish",
          "inspection"
        ],
      },
    }
  ]
)
model supports {
  strategy: "none" | "reachable_noncritical" | "finished_critical";

  @minItems(1)
  start_regions?: Common.target[];

  @minItems(1)
  contact_regions?: Common.target[];

  material?: Common.text;
  removal?: {
    tools: Common.texts;
    access: Common.text;
    path?: Common.text;
  };

  @minItems(1)
  affected_surfaces?: Common.target[];

  allowance?: Common.quantity;
  finish?: Common.text;
  inspection?: Common.semantic_ids;
}

model allowance {
  feature: Common.semantic_id;
  region?: Common.semantic_id;
  dimension?: Common.semantic_id;
  amount: Common.quantity;
  purpose:
    | "stock"
    | "finish"
    | "coating"
    | "support_removal"
    | "shrinkage"
    | "other";
  limits?: Common.text;
  source: Common.source;
}

model inspection {
  id: Common.semantic_id;
  feature?: Common.semantic_id;
  region?: Common.semantic_id;
  requirement?: Common.requirement_id;
  criterion?: Common.criterion;
  method: Common.text;
  instrument?: Common.text;
  capability?: Common.profile_id;
  state: Common.dimension_state;

  /** true when a representative coupon or test piece is the inspected item */
  coupon?: boolean;

  @minItems(1)
  @uniqueItems
  evidence?: Common.evidence_id[];
}

@@example(
  Part,
  #{
    PN: "LMP-0011",
    rev: "X1",
    title: "Retaining ring DIN 471 - 5x0.6",
    material: "Spring steel C60S",
    process: "purchased",
    finish: "Phosphated and oiled",
    mass_target: 0.081,
    make_buy: PartMakeBuy.buy,
    supplier: null,
    decisions: #["DR-004"],
    model_frame: PartModelFrame.part_local,
    procurement: #{
      mode: Drawing.DrawingProcurementMode.catalog,
      manufacturer: "Beneri",
      designation: "Retaining ring DIN 471 - 5x0.6, spring steel C60S, phosphated and oiled",
      standard: "DIN 471",
      specification: #{
        reference: "Beneri DIN 471 datasheet",
        revision: "undated, retrieved 2026-10-27",
        url: "https://www.beneri.com/files/schedetecniche/7f91c971879a15a58dd911afa79f2fba.pdf",
        sha256: "0fe9e28736fde2bd995a269da97c057a612a5ed72fa4c5bdcafd7cf95e0a6baf",
      },
    },
    intent: #{
      functions: #{
        status: "unknown",
        reason: "not recorded before record version 2",
        question: "Q-022",
      },
      material_profile: #{
        status: "unknown",
        reason: "not recorded before record version 2; the legacy material Spring steel C60S is a declaration, not a sourced grade",
        question: "Q-022",
      },
      service: #{
        status: "unknown",
        reason: "not recorded before record version 2",
        question: "Q-022",
      },
      critical_surfaces: #{
        status: "unknown",
        reason: "not recorded before record version 2",
        question: "Q-022",
      },
      route: #[
        #{
          id: "buy",
          kind: "purchased",
          title: "Buy the DIN 471 - 5x0.6 retaining ring",
          output_state: "installed",
          purchase: #{
            identity: #{
              status: "known",
              value: "DIN 471 - 5x0.6",
              basis: "standard",
              sources: #[
                #{
                  kind: "datasheet",
                  reference: "Beneri DIN 471 datasheet",
                  revision: "undated, retrieved 2026-10-27",
                  url: "https://www.beneri.com/files/schedetecniche/7f91c971879a15a58dd911afa79f2fba.pdf",
                  accessed: "2026-10-27",
                }
              ],
            },
            specification: #{
              status: "known",
              value: "DIN 471 - 5x0.6, spring steel C60S, phosphated and oiled, per the Beneri datasheet",
              basis: "user_declared",
              sources: #[
                #{
                  kind: "datasheet",
                  reference: "Beneri DIN 471 datasheet",
                  revision: "undated, retrieved 2026-10-27",
                  url: "https://www.beneri.com/files/schedetecniche/7f91c971879a15a58dd911afa79f2fba.pdf",
                  accessed: "2026-10-27",
                }
              ],
            },
            ratings: #{
              status: "unknown",
              reason: "no load, speed or temperature rating is recorded for this item; DR-004 cites none",
              question: "Q-022",
            },
            availability: #{
              status: "unknown",
              reason: "no supplier is selected (DR-004 open items)",
              question: "Q-022",
            },
            supplier_evidence: #[
              #{
                kind: "datasheet",
                reference: "Beneri DIN 471 datasheet",
                revision: "undated, retrieved 2026-10-27",
                url: "https://www.beneri.com/files/schedetecniche/7f91c971879a15a58dd911afa79f2fba.pdf",
                accessed: "2026-10-27",
              }
            ],
          },
        }
      ],
    },
  }
);
@@example(
  Part,
  #{
    PN: "LMP-0001",
    rev: "X1",
    title: "Base plate and pivot boss",
    material: "PETG",
    process: "fdm",
    finish: "Deburr; no sharp edges",
    mass_target: 313,
    make_buy: PartMakeBuy.make,
    supplier: null,
    decisions: #["DR-002", "DR-004"],
    manufacture: #{
      relationship: "same",
      mesh: #{ linear_deflection_mm: 0.05, angular_deflection_rad: 0.1 },
    },
    drawing: #{
      type: Drawing.DrawingPartDrawingType.detail,
      tolerance_policy: "fdm_bureau",
      datum_features: #{
        A: #{
          feature: "bed_face",
          role: Drawing.DrawingPartDrawingDatumFeaturesValueRole.plane,
        },
        B: #{
          feature: "seat",
          role: Drawing.DrawingPartDrawingDatumFeaturesValueRole.axis,
        },
        C: #{
          feature: "mount_slots",
          role: Drawing.DrawingPartDrawingDatumFeaturesValueRole.clocking_feature,
        },
      },
      coordinate_frame: #{
        origin: #{ intersection: #["A", "B"] },
        z: #{ normal_to: "A", toward: "boss_top" },
        x: #{ toward: "C" },
      },
      views: #[
        #{
          id: "plan",
          kind: Drawing.DrawingViewKind.orthographic,
          normal_to: "top_face",
        },
        #{
          id: "section_profile",
          kind: Drawing.DrawingViewKind.section,
          through: "B",
        },
        #{
          id: "underside",
          kind: Drawing.DrawingViewKind.orthographic,
          opposite: "plan",
        }
      ],
      features: #{
        bed_face: #{ size: Drawing.DrawingFeatureIntentSize.general },
        seat: #{ size: Drawing.DrawingFeatureIntentSize.`interface` },
        seat_chamfer: #{ size: Drawing.DrawingFeatureIntentSize.general },
        boss_top: #{ size: Drawing.DrawingFeatureIntentSize.general },
        boss_chamfer: #{ size: Drawing.DrawingFeatureIntentSize.general },
        boss: #{ size: Drawing.DrawingFeatureIntentSize.general },
        boss_root_round: #{ size: Drawing.DrawingFeatureIntentSize.general },
        top_face: #{ size: Drawing.DrawingFeatureIntentSize.general },
        top_round: #{ size: Drawing.DrawingFeatureIntentSize.general },
        rim: #{ size: Drawing.DrawingFeatureIntentSize.general },
        bed_chamfer: #{ size: Drawing.DrawingFeatureIntentSize.general },
        cavity_outer_wall: #{ size: Drawing.DrawingFeatureIntentSize.general },
        cavity_flanks: #{ size: Drawing.DrawingFeatureIntentSize.general },
        cavity_roof: #{ size: Drawing.DrawingFeatureIntentSize.general },
        cavity_inner_wall: #{ size: Drawing.DrawingFeatureIntentSize.general },
        clip_pocket: #{ size: Drawing.DrawingFeatureIntentSize.general },
        mount_slots: #{ size: Drawing.DrawingFeatureIntentSize.general },
        mount_counterbores: #{ size: Drawing.DrawingFeatureIntentSize.general },
        foot_recesses: #{ size: Drawing.DrawingFeatureIntentSize.general },
        engraving: #{ size: Drawing.DrawingFeatureIntentSize.general },
      },
      dimensions: #[
        #{
          id: "cavity_wall_height",
          operation: Drawing.DrawingDimensionRequestOperation.length,
          features: #["cavity_outer_wall"],
        },
        #{
          id: "plate_thickness",
          operation: Drawing.DrawingDimensionRequestOperation.thickness,
          features: #["bed_face", "top_face"],
        },
        #{
          id: "cavity_roof_thickness",
          operation: Drawing.DrawingDimensionRequestOperation.thickness,
          features: #["top_face", "cavity_roof"],
        }
      ],
      geometric_tolerances: #[
        #{
          id: "seat_perpendicularity",
          characteristic: Drawing.DrawingGeometricToleranceCharacteristic.perpendicularity,
          features: #["seat"],
          zone_mm: 0.2,
          diameter_zone: true,
          datum_frame: #["A"],
        }
      ],
      edges: #{ external: #[-0.2, 0.0], internal: #[0.0, 0.2] },
      surface_texture: #{
        open: "no standard or vendor specification in the record gives an as-printed PETG roughness; the print bureau's surface specification is needed (DR-004)",
      },
      notes: #[
        #{
          kind: Drawing.DrawingPartDrawingNotesItemKind.process,
          text: "FDM, printed boss-up with datum face A on the build plate.",
        },
        #{
          kind: Drawing.DrawingPartDrawingNotesItemKind.finish,
          text: "As printed, burrs and stringing removed; the bushing seat is drilled or reamed to its limits after printing.",
        },
        #{
          kind: Drawing.DrawingPartDrawingNotesItemKind.general,
          text: "Engrave the text LMP in FreeCAD TechDraw Osifont Bold, centred on the stated position.",
          reference: "engraving",
        },
        #{
          kind: Drawing.DrawingPartDrawingNotesItemKind.inspection,
          text: "Heat-set the LMP-0008 bushing flush with the boss top after drilling (DR-004).",
        }
      ],
      manufacturing: #{
        build_direction: #{ normal_to: "A", toward: "boss_top" },
        interface_condition: Drawing.DrawingPartDrawingManufacturingInterfaceCondition.post_processed,
      },
      sheet: #{
        sizes: #[Drawing.sheet_size.A3, Drawing.sheet_size.A2],
        scale: "auto",
      },
    },
    intent: #{
      functions: #{
        status: "unknown",
        reason: "not recorded before record version 2",
        question: "Q-012",
      },
      material_profile: "petg",
      service: #{
        status: "unknown",
        reason: "not recorded before record version 2",
        question: "Q-012",
      },
      critical_surfaces: #{
        status: "unknown",
        reason: "not recorded before record version 2",
        question: "Q-012",
      },
      route: #[
        #{
          id: "print",
          kind: "fdm",
          title: "Print the base plate and pivot boss in PETG, boss up",
          capability: "h2d",
          output_state: "printed",
          orientation: #{
            status: "proposed",
            rotation: #{ quaternion: #[1, 0, 0, 0] },
            note: "Drawing note: printed boss-up with datum face A on the build plate; the manufacture frame equals the model frame, so the pose is the identity. Not yet approved by a decision.",
          },
          supports: #{
            status: "unknown",
            reason: "no support strategy is recorded; the drawing names none",
            question: "Q-012",
          },
          post_processing: #["Remove burrs and stringing"],
        },
        #{
          id: "finish_holes",
          kind: "drilling",
          title: "Drill or ream the bushing seat to its limits after printing (the drawing does not say which)",
          capability: #{
            status: "unknown",
            reason: "no capability profile of the drilling or reaming operator is recorded in manufacturing/capabilities.yaml",
            question: "Q-010",
          },
          input_state: "printed",
          targets: #[#{ feature: "seat" }],
          setup: #{ datums: #["bed_face"] },
        }
      ],
    },
  }
);
