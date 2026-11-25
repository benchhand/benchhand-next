import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/drawing/")
namespace Records.Drawing;

@summary("Drawing intent definitions shared by the product, part and interface records")
@id("https://benchhand.github.io/benchhand/contracts/record/drawing.schema.json")
@extension("x-version", "1.0.0")
union Drawing {
  unknown,
}

@pattern("^[A-HJ-NPR-Z]{1,2}$")
scalar datum_label extends string;

/** A datum label declared in datum_features, or a semantic feature, anchor or view id */
@pattern("^([A-HJ-NPR-Z]{1,2}|[a-z][a-z0-9_]*)$")
scalar reference extends string;

@oneOf
union references {
  reference,
  DrawingReferences1,
}

@extension("x-inline", true)
@minItems(1)
@uniqueItems
model DrawingReferences1 is reference[];

@pattern("^[a-z][a-z0-9_]*$")
scalar policy_name extends string;

enum sheet_size {
  A4,
  A3,
  A2,
  A1,
  A0,
  `ANSI A`,
  `ANSI B`,
  `ANSI C`,
  `ANSI D`,
  `ANSI E`,
}

@oneOf
union scale {
  "auto",
  DrawingScale1,
}

@extension("x-inline", true)
@pattern("^[1-9][0-9]*:[1-9][0-9]*$")
scalar DrawingScale1 extends string;

@extension("minProperties", 1)
model sheet {
  @minItems(1)
  @uniqueItems
  sizes?: sheet_size[];

  orientation?: DrawingSheetOrientation;
  scale?: scale;
  multi_sheet?: boolean;
}

@extension("x-inline", true)
enum DrawingSheetOrientation {
  landscape,
  portrait,
}

/** An axis built from resolved datums or features: normal_to or parallel_to fixes the line, toward or toward_axis its sense */
@extension("minProperties", 1)
@extension(
  "not",
  #{
    anyOf: #[
      #{ required: #["normal_to", "parallel_to"] },
      #{ required: #["toward", "toward_axis"] }
    ],
  }
)
model direction {
  normal_to?: reference;
  parallel_to?: reference;
  toward?: reference;
  toward_axis?: reference;
}

@oneOf
union tolerance {
  {
    policy: policy_name,
  },
  {
    @minItems(2)
    @maxItems(2)
    @extension("x-plausible", #{ min: -1, max: 1 })
    deviation_mm: DrawingTolerance1DeviationMmItem[],
  },
}

@extension("x-inline", true)
@minValue(-10)
@maxValue(10)
scalar DrawingTolerance1DeviationMmItem extends float64;

@oneOf
union tolerance_policy {
  {
    kind: "standard",
    standard: "ISO 2768-1:1989",
    class: DrawingTolerancePolicy0Class,

    @minItems(1)
    @uniqueItems
    applies_to: Common.primary_process[],
  },
  {
    kind: "limits",

    @minValueExclusive(0)
    @maxValue(5)
    @extension("x-plausible", #{ max: 0.5 })
    linear_mm: float64,

    @minValueExclusive(0)
    @maxValue(10)
    @extension("x-plausible", #{ max: 5 })
    angular_deg?: float64,

    @minItems(1)
    @uniqueItems
    applies_to: Common.primary_process[],

    @minLength(1)
    reference: string,
  },
}

@extension("x-inline", true)
enum DrawingTolerancePolicy0Class {
  f,
  m,
  c,
  v,
}

model product_drawing {
  definition: "model_and_drawing";
  `projection`: DrawingProductDrawingProjection;

  @extension("required", #["dimensioning"])
  standards: Record<DrawingProductDrawingStandardsValue>;

  @extension("allOf", #[#{ $ref: "#/$defs/sheet" }, #{ required: #["sizes"] }])
  default_sheet: unknown;

  @minProperties(1)
  @extension("propertyNames", policy_name)
  tolerance_policies: Record<tolerance_policy>;

  general_tolerance_policy: policy_name;
}

@extension("x-inline", true)
enum DrawingProductDrawingProjection {
  first_angle,
  third_angle,
}

@extension("x-inline", true)
@minLength(1)
scalar DrawingProductDrawingStandardsValue extends string;

@extension(
  "allOf",
  #[
    #{
      `if`: #{ properties: #{ kind: #{ `const`: "section" } } },
      then: #{ required: #["through"] },
    },
    #{
      `if`: #{ properties: #{ kind: #{ `const`: "detail" } } },
      then: #{ required: #["feature"] },
    },
    #{
      `if`: #{
        properties: #{ kind: #{ `enum`: #["orthographic", "auxiliary"] } },
      },
      then: #{
        anyOf: #[
          #{ required: #["normal_to"] },
          #{ required: #["along_axis"] },
          #{ required: #["parallel_to"] },
          #{ required: #["perpendicular_to"] },
          #{ required: #["opposite"] }
        ],
      },
    }
  ]
)
model view {
  id: Common.semantic_id;
  kind: DrawingViewKind;
  normal_to?: reference;
  along_axis?: reference;
  parallel_to?: reference;
  perpendicular_to?: reference;
  opposite?: Common.semantic_id;
  through?: references;

  /** section: the cutting plane is normal to this frame axis and passes through the centre of the one through reference */
  normal_axis?: "x" | "y" | "z";

  /** the sheet the view is drawn on; the principal view is on sheet 1 */
  @minValue(1)
  sheet?: integer;

  toward?: reference;
  feature?: Common.semantic_id;
  scale?: scale;
}

@extension("x-inline", true)
enum DrawingViewKind {
  orthographic,
  auxiliary,
  section,
  detail,
}

@extension("minProperties", 1)
model feature_intent {
  size?: DrawingFeatureIntentSize;
  location?: "datum_coordinates";
  profile?: "controlled_model";

  @minValueExclusive(0)
  @maxValue(5)
  @extension("x-plausible", #{ max: 0.5 })
  profile_tolerance_mm?: float64;

  /** general_note: a round's or chamfer's size goes in the sheet's general note of undimensioned edge fillets and edge breaks */
  presentation?: DrawingFeatureIntentPresentation;

  axial_location_from?: reference;
  tolerance_policy?: policy_name;
  thread?: thread;
  surface_texture?: texture_requirement;
  edges?: edges;
}

@extension("x-inline", true)
enum DrawingFeatureIntentSize {
  general,
  `interface`,
}

@extension("x-inline", true)
enum DrawingFeatureIntentPresentation {
  auto,
  visible,
  section,
  detail,
  general_note,
}

/** A thread on a bore or shaft feature, drawn conventionally (ISO 6410-1, ASME Y14.6); the full-thread depth is the measured distance from the feature's entry to its locator anchor */
model thread {
  @pattern("^M[0-9]+(\\.[0-9]+)?x[0-9]+(\\.[0-9]+)?-[0-9][a-hA-H]([0-9][a-hA-H])?$")
  designation: string;

  @minLength(1)
  standard: string;

  operation: DrawingThreadOperation;
  full_depth_anchor?: Common.semantic_id;
}

@extension("x-inline", true)
enum DrawingThreadOperation {
  tap,
  thread_form,
  roll,
  cut,
  vendor,
}

/** ISO 13715:2017 edge size limits [lower, upper] in mm: + permits excess material (burr, passing), - requires removal (edge break, undercut); a single limit pairs with 0 */
@minItems(2)
@maxItems(2)
@extension("x-plausible", #{ min: -0.5, max: 0.5 })
model edge_limits is DrawingEdgeLimitsItem[];

@extension("x-inline", true)
@minValue(-5)
@maxValue(5)
scalar DrawingEdgeLimitsItem extends float64;

/** Edges of undefined shape: the external and internal edge size limits; on a feature, exceptions to the drawing's general indication */
@extension("minProperties", 1)
model edges {
  external?: edge_limits;
  internal?: edge_limits;
}

/** An ISO 21920-1 (ASME Y14.36) surface texture requirement: the parameter's upper limit in micrometres and whether material shall be removed */
model texture_requirement {
  parameter: DrawingTextureRequirementParameter;

  @minValue(0.01)
  @maxValue(500)
  @extension("x-plausible", #{ max: 100 })
  limit_um: float64;

  process: DrawingTextureRequirementProcess;
}

@extension("x-inline", true)
enum DrawingTextureRequirementParameter {
  Ra,
  Rz,
}

@extension("x-inline", true)
enum DrawingTextureRequirementProcess {
  any,
  removal_required,
  removal_prohibited,
}

/** A geometrical tolerance of ISO 1101 or ASME Y14.5 on resolved features; the zone is design intent, never a measured value */
model geometric_tolerance {
  id: Common.semantic_id;
  characteristic: DrawingGeometricToleranceCharacteristic;

  @minItems(1)
  @uniqueItems
  features: Common.semantic_id[];

  @minValueExclusive(0)
  @maxValue(10)
  @extension("x-plausible", #{ min: 0.01, max: 1 })
  zone_mm: float64;

  diameter_zone?: boolean;

  @minItems(1)
  @maxItems(3)
  @uniqueItems
  datum_frame?: datum_label[];
}

@extension("x-inline", true)
enum DrawingGeometricToleranceCharacteristic {
  position,
  coaxiality,
  perpendicularity,
  parallelism,
  flatness,
  cylindricity,
  circular_runout,
  total_runout,
  profile_surface,
}

/** An additional measured dimension; its value always comes from the model, so there is no value field */
model dimension_request {
  id: Common.semantic_id;
  operation: DrawingDimensionRequestOperation;

  @minItems(1)
  @uniqueItems
  features: Common.semantic_id[];

  /** A plane feature a width, thickness or separation is stated at: between two planes that are not parallel (a drafted wall, inclined flanks), the distance between the lines where they meet this plane */
  at?: Common.semantic_id;

  /** A distance from a plane_face to a bore's or shaft's centres: which of their distances from that plane it states, 1 the nearest; centres at one distance share the dimension. Required when the centres lie at several distances */
  @minValue(1)
  instance?: integer;

  @minItems(1)
  @maxItems(3)
  @uniqueItems
  datum_frame?: datum_label[];

  tolerance?: tolerance;
  presentation?: DrawingDimensionRequestPresentation;
  reference?: boolean;
}

@extension("x-inline", true)
enum DrawingDimensionRequestOperation {
  diameter,
  radius,
  distance,
  plane_separation,
  axis_distance,
  location,
  axis_location,
  angle,
  depth,
  width,
  length,
  thickness,
  chamfer,
}

@extension("x-inline", true)
enum DrawingDimensionRequestPresentation {
  auto,
  visible,
  section,
  detail,
}

model part_drawing {
  type: DrawingPartDrawingType;
  tolerance_policy?: policy_name;

  @minProperties(1)
  @extension("propertyNames", datum_label)
  datum_features?: Record<{
    feature: Common.semantic_id;
    role: DrawingPartDrawingDatumFeaturesValueRole;
  }>;

  @extension(
    "anyOf",
    #[#{ required: #["x"] }, #{ required: #["y"] }, #{ required: #["z"] }]
  )
  coordinate_frame?: {
    @oneOf
    origin:
      | {
          @minItems(2)
          @maxItems(3)
          @uniqueItems
          intersection: reference[];
        }
      | {
          at: reference;
        };

    x?: direction;
    y?: direction;
    z?: direction;
  };

  @minItems(1)
  views?: view[];

  @minProperties(1)
  @extension("propertyNames", Common.semantic_id)
  features?: Record<feature_intent>;

  @minItems(1)
  dimensions?: dimension_request[];

  @minItems(1)
  geometric_tolerances?: geometric_tolerance[];

  /** the general indication of the edges of undefined shape (ISO 13715:2017 §4.5.4); a detail drawing needs it */
  @extension(
    "allOf",
    #[#{ $ref: "#/$defs/edges" }, #{ required: #["external", "internal"] }]
  )
  edges?: unknown;

  /** the general surface texture of the surfaces with no texture of their own (ISO 21920-1 §9.1.2), or open with the reason no value has a basis yet; a detail drawing needs it */
  @oneOf
  surface_texture?:
    | texture_requirement
    | {
        @minLength(1)
        open: string;
      };

  @minItems(1)
  notes?: {
    kind: DrawingPartDrawingNotesItemKind;

    @minLength(1)
    text: string;

    @minLength(1)
    reference?: string;
  }[];

  @minProperties(1)
  manufacturing?: {
    build_direction?: direction;
    interface_condition?: DrawingPartDrawingManufacturingInterfaceCondition;
    dimensions_apply?: DrawingPartDrawingManufacturingDimensionsApply;

    @minItems(1)
    post_processing?: DrawingPartDrawingManufacturingPostProcessingItem[];

    @minLength(1)
    inspection_stage?: string;
  };

  sheet?: sheet;
}

@extension("x-inline", true)
enum DrawingPartDrawingType {
  detail,
  vendor_specification,
  source_control,
}

@extension("x-inline", true)
enum DrawingPartDrawingDatumFeaturesValueRole {
  plane,
  axis,
  point,
  center_plane,
  clocking_feature,
}

@extension("x-inline", true)
enum DrawingPartDrawingNotesItemKind {
  process,
  finish,
  material,
  inspection,
  general,
}

@extension("x-inline", true)
enum DrawingPartDrawingManufacturingInterfaceCondition {
  as_printed,
  post_processed,
  finish_machined,
}

@extension("x-inline", true)
enum DrawingPartDrawingManufacturingDimensionsApply {
  before_finish,
  after_finish,
}

@extension("x-inline", true)
@minLength(1)
scalar DrawingPartDrawingManufacturingPostProcessingItem extends string;

model procurement {
  mode: DrawingProcurementMode;

  @minLength(1)
  manufacturer?: string;

  @minLength(1)
  manufacturer_part_number?: string;

  @minLength(1)
  supplier_part_number?: string;

  @minLength(1)
  designation?: string;

  /** the product standard of a standard part, such as DIN 471 or ISO 4762; its designation states the standard with its designation items (DIN 471 - 5x0.6) and identifies the item without a manufacturer or manufacturer part number */
  @pattern("^(ISO|IEC|EN|DIN|BS|JIS|ANSI|ASME|SAE|NAS|MS)( (EN|ISO|IEC))* [A-Z]?[0-9]+(\\.[0-9]+)*(-[0-9]+)*$")
  standard?: string;

  /** the datasheet or standard that defines the item, identified by its sha256; with only a url the frozen copy is a sourcing input kept outside the record */
  @extension("anyOf", #[#{ required: #["artifact"] }, #{ required: #["url"] }])
  specification?: {
    @minLength(1)
    reference: string;

    @minLength(1)
    revision: string;

    /** frozen copy of the specification, relative to hw/ */
    @pattern("^[^/\\n\\r\\u2028\\u2029][^\\n\\r\\u2028\\u2029]*$")
    @extension("not", #{ pattern: "(^|/)\\.\\.(/|$)" })
    artifact?: string;

    /** where the publisher serves the specification */
    @pattern("^https://[^\\t\\n\\v\\f\\r \\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff]+$")
    url?: string;

    sha256: Common.sha256;
  };

  /** orderable identity fields deliberately left open, each with the reason; every one blocks release */
  @minProperties(1)
  open?: {
    @minLength(1)
    manufacturer?: string;

    @minLength(1)
    manufacturer_part_number?: string;

    @minLength(1)
    supplier_part_number?: string;
  };

  @minItems(1)
  approved_sources?: {
    @minLength(1)
    name: string;

    @minLength(1)
    part_number?: string;
  }[];

  @minLength(1)
  qualification_evidence?: string;

  @minItems(1)
  @uniqueItems
  certificates?: DrawingProcurementCertificatesItem[];
}

@extension("x-inline", true)
enum DrawingProcurementMode {
  catalog,
  made_to_drawing,
}

@extension("x-inline", true)
@minLength(1)
scalar DrawingProcurementCertificatesItem extends string;

model fit_endpoint {
  PN: Common.pn;
  occurrence?: Common.occurrence_ref;
  feature: Common.semantic_id;
  region?: Common.semantic_id;
}

/** An ISO 286 fit between two parts: a part pair, or a hole and a shaft feature endpoint */
@extension(
  "oneOf",
  #[
    #{
      required: #["pair"],
      not: #{ anyOf: #[#{ required: #["hole"] }, #{ required: #["shaft"] }] },
    },
    #{ required: #["hole", "shaft"], not: #{ required: #["pair"] } }
  ]
)
model fit {
  @minLength(1)
  fit: string;

  @minItems(2)
  @maxItems(2)
  @uniqueItems
  pair?: Assembly.part_ref[];

  hole?: fit_endpoint;
  shaft?: fit_endpoint;

  /** engagement_length_mm: positive number, in mm. The travel along the insertion axis, back from the installed pose, over which the interfering surface of the inserted part still overlaps its partner. For a press fit seated on a bore floor, use the bore depth (an entry chamfer or counterbore may be ignored); not the press-band length and not the overlap at the installed pose. For a heat-set insert, use its embedded length. For a press fit or a heat-set insert, assembly access exempts interference up to this length plus one minimum sampling step. A running or locating fit records the length but gets no exemption. Optional; never derived. */
  @minValueExclusive(0)
  engagement_length_mm?: float64;

  @minLength(1)
  note?: string;

  axial_retainer?: axial_retainer;
}

/** What keeps a press_fit or locating_fit from walking along its axis; the record validator requires one from stage parts on. Hardware types (circlip, set_screw, nut, pin, cap) name their modelled occurrences in parts */
model axial_retainer {
  type: DrawingAxialRetainerType;

  @minItems(1)
  @uniqueItems
  parts?: Assembly.part_ref[];

  decision?: Common.decision;
}

@extension("x-inline", true)
enum DrawingAxialRetainerType {
  shoulder,
  circlip,
  set_screw,
  nut,
  pin,
  cap,
  captured,
  press_fit,
  adhesive,
}

@doc("A heat-set insert installed in its host part's bore; the pair is [host, insert], each a PN or an @occurrence reference")
model heat_set {
  @minItems(2)
  @maxItems(2)
  @uniqueItems
  pair: Assembly.part_ref[];

  /** The bore diameter, in mm */
  @minValueExclusive(0)
  @maxValue(100)
  @extension("x-plausible", #{ min: 1.5, max: 25 })
  hole_diameter_mm: float64;

  /** The bore's [lower, upper] deviation from hole_diameter_mm, in mm */
  @minItems(2)
  @maxItems(2)
  hole_deviation_mm?: float64[];

  /** The minimum bore depth, in mm */
  @minValueExclusive(0)
  @maxValue(100)
  @extension("x-plausible", #{ min: 1.5, max: 25 })
  min_depth_mm?: float64;

  /** engagement_length_mm: positive number, in mm. The travel along the insertion axis, back from the installed pose, over which the interfering surface of the inserted part still overlaps its partner. For a press fit seated on a bore floor, use the bore depth (an entry chamfer or counterbore may be ignored); not the press-band length and not the overlap at the installed pose. For a heat-set insert, use its embedded length. For a press fit or a heat-set insert, assembly access exempts interference up to this length plus one minimum sampling step. A running or locating fit records the length but gets no exemption. Optional; never derived. */
  @minValueExclusive(0)
  engagement_length_mm?: float64;

  @minLength(1)
  insert: string;

  @pattern("^https?://[^\\t\\n\\v\\f\\r \\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff]+$")
  source: string;

  @minLength(1)
  note?: string;

  /** the host part's bore feature that takes the insert */
  feature?: Common.semantic_id;
}

@@example(
  Drawing,
  #{
    fit: "5 H7/p6",
    hole: #{ PN: "LMP-0002", feature: "hub_bore" },
    shaft: #{ PN: "LMP-0005", feature: "press_band" },
  }
);
