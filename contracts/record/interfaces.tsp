import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/interfaces/")
namespace Records.Interfaces;

/** The interfaces record, hw/interfaces.yaml: each interface between two parts, from one to the other, with its type and description. */
@summary("benchhand interfaces record (hw/interfaces.yaml)")
@id("https://benchhand.github.io/benchhand/contracts/record/interfaces.schema.json")
@extension("x-version", "1.0.0")
model Interfaces {
  interfaces: InterfacesInterfacesItem[];
}

@extension("x-inline", true)
enum InterfacesInterfacesInterfacesItemType {
  mounting,
  motion,
  electrical,
  thermal,
  clearance,
  other,
}

@extension("x-inline", true)
@extension(
  "dependentRequired",
  #{
    pair: #["min_clearance_mm"],
    min_clearance_mm: #["pair"],
    margin_mm: #["min_clearance_mm"],
  }
)
@extension("if", #{ required: #["pair"] })
@extension("then", #{ properties: #{ type: #{ `const`: "clearance" } } })
model InterfacesInterfacesItem {
  id: Common.interface_id;

  @minLength(1)
  from: string;

  @minLength(1)
  to: string;

  type: InterfacesInterfacesInterfacesItemType;

  @minLength(1)
  description: string;

  @doc("A clearance requirement's two parts, each a PN placed at most once or an @occurrence reference")
  @minItems(2)
  @maxItems(2)
  @uniqueItems
  pair?: Assembly.part_ref[];

  /** The smallest distance the pair may come to, at the nominal pose and at every swept pose */
  @minValueExclusive(0)
  @maxValue(5)
  @extension("x-plausible", #{ max: 1 })
  min_clearance_mm?: float64;

  /** This requirement's margin above min_clearance_mm, overriding product.yaml design.clearance_margin_mm */
  @minValue(0)
  @maxValue(1)
  @extension("x-plausible", #{ max: 0.5 })
  margin_mm?: float64;

  limits?: {
    press_fit?: Drawing.fit;
    running_fit?: Drawing.fit;
    locating_fit?: Drawing.fit;

    @minItems(1)
    heat_set?: Drawing.heat_set[];

    ...Record<unknown>;
  };
  functional?: functional;
}

/** One face of a part, by its semantic feature id */
model face {
  PN: Common.pn;
  occurrence?: Common.occurrence_ref;
  component?: Common.semantic_id;
  feature: Common.semantic_id;
  region?: Common.semantic_id;
}

/** Record version 2 functional contract of an interface. Desired fit limits (limits), calibrated process precision (capability profiles) and inspected finished dimensions (acceptance) stay three distinct things; no tolerance is inferred from a fit name */
model functional {
  critical: Common.boolean_fact;

  @oneOf
  functions: InterfacesFunctionalFunctions0 | Common.fact_unknown;

  requirements?: Common.requirement_ids;
  failure_consequence?: Common.text_fact;

  /** product.yaml use_case.loads ids */
  loads?: Common.semantic_ids;

  environment?: Common.text;

  @minItems(1)
  surfaces?: {
    PN: Common.pn;
    occurrence?: Common.occurrence_ref;
    component?: Common.semantic_id;
    feature: Common.semantic_id;
    region?: Common.semantic_id;
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
    datum?: Drawing.datum_label;
    source?: Common.source;
    dimension_state: Common.dimension_state;
  }[];

  @minItems(1)
  acceptance?: {
    criterion: Common.criterion;
    verification: {
      method: "I" | "A" | "D" | "T";

      @minItems(1)
      @uniqueItems
      evidence_required: Common.evidence_level[];

      stage: Common.stage;
    };
  }[];

  /** The tolerance stack: its managed analysis case, the contributors it includes and the governing method; RSS needs the decision that justifies its statistical assumptions */
  @extension("if", #{ properties: #{ method: #{ `const`: "justified_rss" } } })
  @extension("then", #{ required: #["decision"] })
  variation?: {
    /** an hw/analysis/cases/<ID> case id */
    @pattern("^[a-z][a-z0-9_-]*$")
    stack_case: string;

    @minItems(1)
    @uniqueItems
    contributors: (
      | "manufacture"
      | "assembly"
      | "thermal"
      | "moisture"
      | "wear"
      | "deformation"
      | "coating"
      | "adhesive"
      | "joining")[];

    method: "worst_case" | "justified_rss";
    decision?: Common.decision;
  };

  contact?: {
    @minItems(2)
    @maxItems(2)
    materials: InterfacesFunctionalContactMaterialsItem[];

    finish?: Common.text_fact;
    lubrication?: Common.text_fact;
    load?: Common.quantity_fact;
    speed?: Common.quantity_fact;
    duty?: Common.text_fact;
    life?: Common.quantity_fact;

    @minItems(1)
    @uniqueItems
    evidence?: Common.evidence_id[];
  };

  /** The joint's free movement at this interface: each component the total play about the nominal, centred pose (an interval's upper bound governs the extremes), axial along the joint axis, radial across it, angular as tilt of the axis, backlash along the joint's own coordinate; compliance the elastic displacement under the interface's declared loads (spring preload, operating loads), sourced from a calculation or test, added to the play at the extremes. A component the interface function needs and the record does not declare is unknown, never zero. scenario_cases name the motion cases evaluated under play */
  @minProperties(1)
  play?: {
    axial?: Common.quantity_fact;
    radial?: Common.quantity_fact;
    angular?: Common.quantity_fact;
    backlash?: Common.quantity_fact;

    @minProperties(1)
    compliance?: {
      axial?: Common.quantity_fact;
      radial?: Common.quantity_fact;
      angular?: Common.quantity_fact;
    };

    /** hw/motion/cases/<ID> case ids */
    @minItems(1)
    @uniqueItems
    scenario_cases?: @pattern("^[a-z][a-z0-9_-]*$") scalar extends string[];
  };

  @minItems(1)
  @uniqueItems
  assembly_operations?: Common.assembly_operation_id[];

  /** The joints at this interface that print already assembled: each joint's kind, the joint value it prints at, the face pairs its gap separates and how it breaks free after printing. min_clearance_mm must be at least the governing product.yaml flow.profile processes.fdm.pip_clearance_mm */
  @minItems(1)
  print_in_place?: {
    joint: "hinge" | "pin" | "ball" | "captive" | "living_hinge";

    /** the value each assembly.yaml joint prints at, in that joint's units */
    @minProperties(1)
    @extension("propertyNames", #{ pattern: "^J-[0-9]{3}$" })
    @extension(
      "x-keyword-order",
      #["minProperties", "propertyNames", "additionalProperties"]
    )
    print_pose: Record<float64>;

    @minItems(1)
    gap_features: InterfacesFunctionalPrintInPlaceItemGapFeaturesItem[];

    break_free: {
      method: Common.text;

      @minValueExclusive(0)
      force_n?: float64;
    };
  }[];

  inspections?: Common.semantic_ids;

  @minItems(1)
  @uniqueItems
  decisions?: Common.decision[];
}

@extension("x-inline", true)
@minItems(1)
model InterfacesFunctionalFunctions0 is Common.function_entry[];

@extension("x-inline", true)
@oneOf
union InterfacesFunctionalContactMaterialsItem {
  Common.profile_id,
  Common.fact_open,
}

@extension("x-inline", true)
@minItems(2)
@maxItems(2)
model InterfacesFunctionalPrintInPlaceItemGapFeaturesItem is face[];

@@example(
  Interfaces,
  #{
    interfaces: #[
      #{
        id: "IF-001",
        from: "base_sub",
        to: "lower_link",
        type: InterfacesInterfacesInterfacesItemType.motion,
        description: "Base pivot axis; M5 shoulder pin LMP-0005 pressed into the lower-link hub turns in the LMP-0008 brass bushing heat-set into the base boss, retained by the DIN 471 ring LMP-0011 (occurrence @ring-base) under the bushing's lower end (DR-004).",
        limits: #{
          rotation_deg: #[-10, 80],
          press_fit: #{
            fit: "5 H7/p6",
            engagement_length_mm: 20.0,
            hole: #{ PN: "LMP-0002", feature: "hub_bore" },
            shaft: #{ PN: "LMP-0005", feature: "press_band" },
            axial_retainer: #{
              type: Drawing.DrawingAxialRetainerType.press_fit,
            },
          },
          running_fit: #{
            fit: "5 f7",
            hole: #{ PN: "LMP-0008", feature: "bore" },
            shaft: #{ PN: "LMP-0005", feature: "journal" },
            note: "pin journal 5 f7 in the SPIROL CL8000 bore 5.05/5.15 (vendor limits, not ISO 286): diametral clearance 0.060/0.172 (cad-fits STK-101, DR-004)",
          },
          heat_set: #[
            #{
              pair: #["LMP-0001", "LMP-0008"],
              engagement_length_mm: 8.0,
              hole_diameter_mm: 7.77,
              hole_deviation_mm: #[-0.04, 0.04],
              min_depth_mm: 8.0,
              insert: "SPIROL CMPL 4 X 8 EK CL8000",
              source: "https://www.spirol.com/assets/files/cmpl-cl8000-cl8100-specification-flyer-us.pdf",
              note: "knurl 7.97 nominal in the 7.73/7.81 recommended hole: 0.16/0.24 diametral embedment (STK-102)",
              feature: "seat",
            }
          ],
          retaining_ring: #{
            pair: #["LMP-0005", "@ring-base"],
            ring: "DIN 471 - 5x0.6",
            groove_d: "4.8 h10",
            groove_w: "0.7 H13",
            source: "https://www.beneri.com/en/prodotto/din-471",
            feature: "groove",
          },
        },
        functional: #{
          critical: #{
            status: "unknown",
            reason: "not recorded before record version 2",
            question: "Q-023",
          },
          functions: #{
            status: "unknown",
            reason: "not recorded before record version 2",
            question: "Q-023",
          },
        },
      },
      #{
        id: "IF-002",
        from: "lower_link",
        to: "upper_link",
        type: InterfacesInterfacesInterfacesItemType.motion,
        description: "Elbow hinge axis; M5 shoulder pin LMP-0006 pressed into the lower link's +Y clevis cheek carries the upper-link tongue, retained by the DIN 471 ring LMP-0011 (occurrence @ring-elbow) outside the -Y cheek.",
        limits: #{
          rotation_deg: #[-120, 0],
          press_fit: #{
            fit: "5 H7/p6",
            engagement_length_mm: 5.8,
            hole: #{
              PN: "LMP-0002",
              feature: "elbow_bore",
              region: "head_side_cheek",
            },
            shaft: #{ PN: "LMP-0006", feature: "press_band" },
            axial_retainer: #{
              type: Drawing.DrawingAxialRetainerType.press_fit,
            },
          },
          running_fit: #{
            fit: "5 H8/f7",
            hole: #{ PN: "LMP-0003", feature: "elbow_bore" },
            shaft: #{ PN: "LMP-0006", feature: "journal" },
          },
          locating_fit: #{
            fit: "5 H7/f7",
            hole: #{
              PN: "LMP-0002",
              feature: "elbow_bore",
              region: "far_cheek",
            },
            shaft: #{ PN: "LMP-0006", feature: "journal" },
            note: "far-cheek support of the journal, locating clearance 0.010/0.034 (DR-003, DR-004)",
            axial_retainer: #{
              type: Drawing.DrawingAxialRetainerType.circlip,
              parts: #["@ring-elbow"],
            },
          },
          retaining_ring: #{
            pair: #["LMP-0006", "@ring-elbow"],
            ring: "DIN 471 - 5x0.6",
            groove_d: "4.8 h10",
            groove_w: "0.7 H13",
            source: "https://www.beneri.com/en/prodotto/din-471",
            feature: "groove",
          },
        },
        functional: #{
          critical: #{
            status: "unknown",
            reason: "not recorded before record version 2",
            question: "Q-024",
          },
          functions: #{
            status: "unknown",
            reason: "not recorded before record version 2",
            question: "Q-024",
          },
        },
      }
    ],
  }
);
@@example(Interfaces, #{ interfaces: #[] });
