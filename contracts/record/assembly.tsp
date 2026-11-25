import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/assembly/")
namespace Records.Assembly;

@summary("benchhand assembly record (hw/assembly.yaml)")
@id("https://benchhand.github.io/benchhand/contracts/record/assembly.schema.json")
@extension("x-version", "1.0.0")
model Assembly {
  /** Record version 2 installation, closure, fastening, adjustment, inspection and service operations, independent of drawings; unknown until recorded */
  @oneOf
  operations?: assembly_operation[] | Common.fact_unknown;

  /** Explicit placements of part definitions; a PN listed in a subassembly's parts is one implicit occurrence at the identity placement instead */
  @minItems(1)
  occurrences?: {
    id: occurrence_id;
    PN: Common.pn;
    placement?: placement;
  }[];

  /** Reusable periodic tables a periodic_table coupling evaluates, by name */
  @minProperties(1)
  @extension("propertyNames", #{ pattern: "^[a-z][a-z0-9_-]*$" })
  profiles?: Record<assembly_profile>;

  /** Shared mechanism parameters whose outputs several slider_crank couplings follow */
  @minItems(1)
  mechanisms?: mechanism[];

  @minItems(1)
  subassemblies: AssemblySubassembliesItem[];

  joints: AssemblyJointsItem[];
  drawing?: assembly_drawing;
}

@extension("x-inline", true)
@extension(
  "anyOf",
  #[#{ required: #["parts"] }, #{ required: #["occurrences"] }]
)
model AssemblySubassembliesItem {
  @pattern("^[a-z][a-z0-9_-]*$")
  id: string;

  @minLength(1)
  title: string;

  @minItems(1)
  parts?: Common.pn[];

  @minItems(1)
  @uniqueItems
  occurrences?: Common.occurrence_ref[];
}

@extension("x-inline", true)
enum AssemblyAssemblyJointsItemType {
  revolute,
  prismatic,
  fixed,
}

@extension("x-inline", true)
enum AssemblyAssemblyJointsItemTorque {
  transmitted,
  none,
}

@extension("x-inline", true)
@extension(
  "oneOf",
  #[#{ required: #["nominal"] }, #{ required: #["coupling"] }]
)
@extension(
  "allOf",
  #[
    #{
      `if`: #{ properties: #{ type: #{ `const`: "fixed" } } },
      then: #{ required: #["nominal"] },
    },
    #{
      `if`: #{ properties: #{ type: #{ `const`: "prismatic" } } },
      then: #{
        not: #{
          anyOf: #[#{ required: #["torque"] }, #{ required: #["torque_path"] }],
        },
      },
    },
    #{
      `if`: #{ required: #["torque_path"] },
      then: #{
        required: #["torque"],
        properties: #{ torque: #{ `const`: "transmitted" } },
      },
    }
  ]
)
@extension("x-keyword-order", #["oneOf", "allOf"])
model AssemblyJointsItem {
  id: joint_id;
  type: AssemblyAssemblyJointsItemType;
  parent: part_ref;
  child: part_ref;
  axis: Common.vector;
  origin: Common.vector;
  min: float64;
  max: float64;

  /** The value of an independent joint; a coupled joint has none */
  nominal?: float64;

  coupling?: coupling;

  /** Whether the child carries drive torque. From stage parts on, every revolute declares it (none for a hand-positioned or free-running joint), and so does every fixed joint inside the drive train that a revolute not declared none starts; a fixed joint declared transmitted names its torque_path */
  torque?: AssemblyAssemblyJointsItemTorque;

  torque_path?: torque_path;
}

@pattern("^J-[0-9]{3}$")
scalar joint_id extends string;

/** What carries the drive torque across a torque: transmitted joint; required on a fixed joint, optional on a revolute driven through an unmodelled shaft. Hardware types (key, set_screw, pin) name their modelled occurrences in parts */
model torque_path {
  type: enum {
    key,
    set_screw,
    d_flat,
    press_fit,
    spline,
    clamp,
    pin,
    adhesive,
  };

  @minItems(1)
  @uniqueItems
  parts?: part_ref[];

  decision?: Common.decision;
}

/** A dependent joint's law: its value derives from a driver joint */
@oneOf
union coupling {
  AssemblyCoupling0,
  AssemblyCoupling1,
  AssemblyCoupling2,
}

/** q = ratio * q_driver + offset; ratio in dependent units per driver unit */
@extension("x-inline", true)
model AssemblyCoupling0 {
  type: "linear";
  driver: joint_id;
  ratio: float64;
  offset?: float64;
}

/** q = profile((q_driver + phase_deg) mod period_deg); the driver is revolute */
@extension("x-inline", true)
model AssemblyCoupling1 {
  type: "periodic_table";
  driver: joint_id;

  @pattern("^[a-z][a-z0-9_-]*$")
  profile: string;

  phase_deg?: float64;
}

/** One output of a slider_crank mechanism: piston displacement (prismatic) or rod angle (revolute) */
@extension("x-inline", true)
model AssemblyCoupling2 {
  type: "slider_crank";

  @pattern("^[a-z][a-z0-9_-]*$")
  mechanism: string;

  output: "displacement" | "rod_angle";
}

/** Piecewise-linear periodic table: samples from 0 to period_deg with matching end values */
@id("https://benchhand.github.io/benchhand/contracts/record/assembly/profile.json")
model assembly_profile {
  input_unit: "deg";
  output_unit: "mm" | "deg";

  @minValueExclusive(0)
  @maxValue(360)
  period_deg: float64;

  interpolation: "linear";

  @minItems(2)
  samples: AssemblyAssemblyProfileSamplesItem[];
}

@extension("x-inline", true)
@prefixItems([float64, float64])
@minItems(2)
@maxItems(2)
model AssemblyAssemblyProfileSamplesItem is unknown[];

/** A centred slider-crank: the driver turns the crank about crank_axis through origin_mm; the piston slides along bank_axis */
model mechanism {
  @pattern("^[a-z][a-z0-9_-]*$")
  id: string;

  type: "slider_crank";
  driver: joint_id;
  origin_mm: Common.vector;
  crank_axis: Common.vector;
  bank_axis: Common.vector;

  @minValueExclusive(0)
  @maxValue(1000)
  @extension("x-plausible", #{ max: 200 })
  crank_radius_mm: float64;

  @minValueExclusive(0)
  @maxValue(1000)
  @extension("x-plausible", #{ max: 500 })
  rod_length_mm: float64;

  phase_deg?: float64;
}

@pattern("^[a-z][a-z0-9_-]*$")
scalar occurrence_id extends string;

/** An occurrence reference, or a PN that has exactly one occurrence */
union part_ref {
  Common.pn,
  Common.occurrence_ref,
}

/** Rest placement x -> R x + t: rotation about the definition's local origin, then translation (mm) */
model placement {
  translation_mm?: Common.vector;
  rotation?: {
    axis: Common.vector;
    angle_deg: float64;
  };
}

/** One assembly-drawing item row: a PN and, when it is placed more than once, the occurrences it stands for */
model drawing_item {
  @minValue(1)
  item: integer;

  PN: Common.pn;

  @minItems(1)
  @uniqueItems
  occurrences?: Common.occurrence_ref[];
}

/** Assembly drawing intent: identity, views, presentation-only explode offsets, parts-list items, subassembly sheets and installation operations */
model assembly_drawing {
  @minLength(1)
  number: string;

  @minLength(1)
  rev: string;

  @minLength(1)
  title: string;

  scope?: "modeled_mechanical_assembly" | "complete_assembly";

  /** What a modelled scope leaves out, named on the drawing */
  excludes?: @minLength(1) scalar extends string[];

  @minItems(1)
  views: {
    @pattern("^[a-z][a-z0-9_-]*$")
    id: string;

    kind: "assembled" | "exploded";
    direction: "front" | "back" | "left" | "right" | "top" | "bottom" | "iso";
  }[];

  /** Exploded-view offsets in mm, assembly frame; each occurrence also moves by its kinematic ancestors' offsets */
  explode?: {
    ref: part_ref;
    offset_mm: Common.vector;
  }[];

  @minItems(1)
  items: drawing_item[];

  @uniqueItems
  subassembly_sheets?: @pattern("^[a-z][a-z0-9_-]*$") scalar extends string[];
}

/** One assembly operation. An installation step puts `part` into `into` along `direction` (in the receiving part's model frame) until the acceptance holds; the fit, insert or ring comes from the interface limit of the same kind. predecessors name the operations that must come first, closes the parts it encloses, and tool_access the tools that must reach. A tool name alone is display text: its reach stays unknown. path, when given, is the part's insertion path; without it the part travels in a straight line along direction, and checks report that default. edge_distance is a fastener, insert or heat-set joint's distance from its hole to the nearest edge against its sourced criterion */
@extension(
  "allOf",
  #[
    #{
      `if`: #{
        properties: #{
          kind: #{ `enum`: #["press_fit", "heat_set", "retaining_ring"] },
        },
      },
      then: #{ required: #["into", "interface", "direction", "acceptance"] },
    },
    #{
      `if`: #{
        properties: #{ kind: #{ `enum`: #["insert", "fasten", "join"] } },
      },
      then: #{ required: #["into", "direction", "acceptance"] },
    },
    #{
      `if`: #{ properties: #{ kind: #{ `const`: "close" } } },
      then: #{ required: #["into", "closes"] },
    },
    #{
      `if`: #{ properties: #{ kind: #{ `enum`: #["adjust", "inspect"] } } },
      then: #{ required: #["acceptance"] },
    },
    #{
      `if`: #{ properties: #{ kind: #{ `const`: "disassemble" } } },
      then: #{ required: #["into", "direction"] },
    },
    #{
      `if`: #{
        properties: #{
          kind: #{ `enum`: #["close", "adjust", "inspect", "disassemble"] },
        },
      },
      then: #{ not: #{ required: #["edge_distance"] } },
    },
    #{
      `if`: #{ required: #["path"] },
      then: #{
        required: #["direction"],
        properties: #{
          kind: #{
            `enum`: #[
              "press_fit",
              "heat_set",
              "retaining_ring",
              "insert",
              "fasten",
              "join",
              "close"
            ],
          },
        },
      },
    }
  ]
)
model assembly_operation {
  @pattern("^[a-z][a-z0-9_-]*$")
  id: string;

  kind:
    | "press_fit"
    | "heat_set"
    | "retaining_ring"
    | "insert"
    | "fasten"
    | "join"
    | "close"
    | "adjust"
    | "inspect"
    | "disassemble";
  part: part_ref;
  into?: part_ref;
  `interface`?: Common.interface_id;
  direction?: Common.vector;
  acceptance?: {
    kind:
      | "seated"
      | "standoff"
      | "flush"
      | "engaged"
      | "torqued"
      | "adjusted"
      | "inspected";

    @minItems(1)
    @maxItems(2)
    features: @pattern("^[a-z][a-z0-9_]*$") scalar extends string[];
  };
  tools?: @minLength(1) scalar extends string[];
  consumables?: @minLength(1) scalar extends string[];

  @pattern("^J-[0-9]{3}$")
  verify_joint?: string;

  @minItems(1)
  @uniqueItems
  predecessors?: @pattern("^[a-z][a-z0-9_-]*$") scalar extends string[];

  /** parts this operation encloses: no later operation reaches them */
  @minItems(1)
  @uniqueItems
  closes?: part_ref[];

  @minItems(1)
  tool_access?: {
    @minLength(1)
    tool: string;

    capability?: Common.profile_id;
    approach?: Common.vector;
    reach?: Common.quantity_fact;
    envelope?: Common.text_fact;
  }[];

  engagement?: Common.quantity_fact;
  torque?: Common.quantity_fact;
  retention?: Common.text_fact;
  service_access?: Common.text_fact;

  /** The joint's edge distance: the criterion it must meet (property edge_distance, a length bound with its source) and the distance the design gives, a known length (an interval's lower end governs) or an unknown with its reason */
  edge_distance?: {
    @extension(
      "allOf",
      #[
        #{ $ref: "common.schema.json#/$defs/criterion" },
        #{
          required: #["units"],
          properties: #{
            property: #{ `const`: "edge_distance" },
            operator: #{ `enum`: #[">=", "between"] },
            units: #{ `enum`: #["mm", "um", "m"] },
          },
        }
      ]
    )
    criterion: unknown;

    distance: Common.quantity_fact;
  };

  /** The insertion path of `part`: its offsets in mm from the installed pose, in the receiving part's model frame, keeping the installed orientation. The part starts at start, passes via in order and arrives installed; the last leg runs along direction */
  path?: {
    start: Common.vector;

    @minItems(1)
    via?: Common.vector[];
  };

  @minLength(1)
  inspection?: string;
}

@@example(
  Assembly,
  #{
    occurrences: #[
      #{
        id: "ring-base",
        PN: "LMP-0011",
        placement: #{
          translation_mm: #[0, 0, 21.495],
          rotation: #{ axis: #[1, 0, 0], angle_deg: 180 },
        },
      },
      #{
        id: "ring-elbow",
        PN: "LMP-0011",
        placement: #{
          translation_mm: #[160, -11.005, 40],
          rotation: #{ axis: #[1, 0, 0], angle_deg: 90 },
        },
      },
      #{
        id: "ring-head",
        PN: "LMP-0011",
        placement: #{
          translation_mm: #[360, -8.505, 40],
          rotation: #{ axis: #[1, 0, 0], angle_deg: 90 },
        },
      }
    ],
    subassemblies: #[
      #{
        id: "base_sub",
        title: "Base subassembly (base plate and pivot boss, its bushing)",
        parts: #["LMP-0001", "LMP-0008"],
      },
      #{
        id: "arm_sub",
        title: "Arm subassembly (lower link, upper link, and head, with pins, bushing, insert, and rings)",
        parts: #[
          "LMP-0002",
          "LMP-0003",
          "LMP-0004",
          "LMP-0005",
          "LMP-0006",
          "LMP-0007",
          "LMP-0009",
          "LMP-0010"
        ],
        occurrences: #["@ring-base", "@ring-elbow", "@ring-head"],
      }
    ],
    joints: #[
      #{
        id: "J-001",
        type: AssemblyAssemblyJointsItemType.revolute,
        parent: "LMP-0001",
        child: "LMP-0002",
        axis: #[0, 0, 1],
        origin: #[0, 0, 40],
        min: -10,
        max: 80,
        nominal: 0,
        torque: AssemblyAssemblyJointsItemTorque.none,
      },
      #{
        id: "J-002",
        type: AssemblyAssemblyJointsItemType.revolute,
        parent: "LMP-0002",
        child: "LMP-0003",
        axis: #[0, 1, 0],
        origin: #[160, 0, 40],
        min: -120,
        max: 0,
        nominal: -30,
        torque: AssemblyAssemblyJointsItemTorque.none,
      },
      #{
        id: "J-003",
        type: AssemblyAssemblyJointsItemType.revolute,
        parent: "LMP-0003",
        child: "LMP-0004",
        axis: #[0, 1, 0],
        origin: #[360, 0, 40],
        min: -45,
        max: 45,
        nominal: 0,
        torque: AssemblyAssemblyJointsItemTorque.none,
      },
      #{
        id: "J-004",
        type: AssemblyAssemblyJointsItemType.fixed,
        parent: "LMP-0002",
        child: "LMP-0005",
        axis: #[0, 0, 1],
        origin: #[0, 0, 40],
        min: 0,
        max: 0,
        nominal: 0,
      },
      #{
        id: "J-005",
        type: AssemblyAssemblyJointsItemType.fixed,
        parent: "LMP-0002",
        child: "LMP-0006",
        axis: #[0, 1, 0],
        origin: #[160, 0, 40],
        min: 0,
        max: 0,
        nominal: 0,
      },
      #{
        id: "J-006",
        type: AssemblyAssemblyJointsItemType.fixed,
        parent: "LMP-0003",
        child: "LMP-0007",
        axis: #[0, 1, 0],
        origin: #[360, 0, 40],
        min: 0,
        max: 0,
        nominal: 0,
      },
      #{
        id: "J-007",
        type: AssemblyAssemblyJointsItemType.fixed,
        parent: "LMP-0001",
        child: "LMP-0008",
        axis: #[0, 0, 1],
        origin: #[0, 0, 40],
        min: 0,
        max: 0,
        nominal: 0,
      },
      #{
        id: "J-008",
        type: AssemblyAssemblyJointsItemType.fixed,
        parent: "LMP-0004",
        child: "LMP-0009",
        axis: #[0, 1, 0],
        origin: #[360, 0, 40],
        min: 0,
        max: 0,
        nominal: 0,
      },
      #{
        id: "J-009",
        type: AssemblyAssemblyJointsItemType.fixed,
        parent: "LMP-0004",
        child: "LMP-0010",
        axis: #[0, 0, 1],
        origin: #[430, 0, 50],
        min: 0,
        max: 0,
        nominal: 0,
      },
      #{
        id: "J-010",
        type: AssemblyAssemblyJointsItemType.fixed,
        parent: "LMP-0005",
        child: "@ring-base",
        axis: #[0, 0, 1],
        origin: #[0, 0, 40],
        min: 0,
        max: 0,
        nominal: 0,
      },
      #{
        id: "J-011",
        type: AssemblyAssemblyJointsItemType.fixed,
        parent: "LMP-0006",
        child: "@ring-elbow",
        axis: #[0, 1, 0],
        origin: #[160, 0, 40],
        min: 0,
        max: 0,
        nominal: 0,
      },
      #{
        id: "J-012",
        type: AssemblyAssemblyJointsItemType.fixed,
        parent: "LMP-0007",
        child: "@ring-head",
        axis: #[0, 1, 0],
        origin: #[360, 0, 40],
        min: 0,
        max: 0,
        nominal: 0,
      }
    ],
    drawing: #{
      number: "LMP-ASM",
      rev: "X1",
      title: "Lamp arm assembly",
      scope: "modeled_mechanical_assembly",
      excludes: #[
        "lampholder and wiring (IF-005)",
        "M6 mounting fasteners and feet (IF-004)"
      ],
      views: #[
        #{ id: "assembled_front", kind: "assembled", direction: "front" },
        #{ id: "exploded_iso", kind: "exploded", direction: "iso" }
      ],
      explode: #[
        #{ ref: "LMP-0008", offset_mm: #[0, 0, 40] },
        #{ ref: "LMP-0002", offset_mm: #[0, 0, 75] },
        #{ ref: "LMP-0005", offset_mm: #[0, 0, 45] },
        #{ ref: "@ring-base", offset_mm: #[0, 0, -96] },
        #{ ref: "LMP-0006", offset_mm: #[0, 40, 0] },
        #{ ref: "@ring-elbow", offset_mm: #[0, -70, 0] },
        #{ ref: "LMP-0003", offset_mm: #[0, 0, 45] },
        #{ ref: "LMP-0007", offset_mm: #[0, 40, 0] },
        #{ ref: "@ring-head", offset_mm: #[0, -70, 0] },
        #{ ref: "LMP-0004", offset_mm: #[60, 0, 0] },
        #{ ref: "LMP-0009", offset_mm: #[0, 35, 50] },
        #{ ref: "LMP-0010", offset_mm: #[50, 0, -86.6] }
      ],
      items: #[
        #{ item: 1, PN: "LMP-0001" },
        #{ item: 2, PN: "LMP-0002" },
        #{ item: 3, PN: "LMP-0003" },
        #{ item: 4, PN: "LMP-0004" },
        #{ item: 5, PN: "LMP-0005" },
        #{ item: 6, PN: "LMP-0006" },
        #{ item: 7, PN: "LMP-0007" },
        #{ item: 8, PN: "LMP-0008" },
        #{ item: 9, PN: "LMP-0009" },
        #{ item: 10, PN: "LMP-0010" },
        #{
          item: 11,
          PN: "LMP-0011",
          occurrences: #["@ring-base", "@ring-elbow", "@ring-head"],
        }
      ],
      subassembly_sheets: #["base_sub", "arm_sub"],
    },
    operations: #[
      #{
        id: "heat_set_base_bushing",
        kind: "heat_set",
        part: "LMP-0008",
        into: "LMP-0001",
        `interface`: "IF-001",
        direction: #[0, 0, -1],
        acceptance: #{ kind: "flush", features: #["top_end", "boss_top_face"] },
      },
      #{
        id: "heat_set_head_bushing",
        kind: "heat_set",
        part: "LMP-0009",
        into: "LMP-0004",
        `interface`: "IF-003",
        direction: #[0, -1, 0],
        acceptance: #{
          kind: "seated",
          features: #["head_underside", "counterbore_floor"],
        },
      },
      #{
        id: "heat_set_socket_insert",
        kind: "heat_set",
        part: "LMP-0010",
        into: "LMP-0004",
        `interface`: "IF-005",
        direction: #[0, 0, 1],
        acceptance: #{
          kind: "flush",
          features: #["installed_end", "socket_boss_face"],
        },
      },
      #{
        id: "press_base_pin",
        kind: "press_fit",
        part: "LMP-0005",
        into: "LMP-0002",
        `interface`: "IF-001",
        direction: #[0, 0, -1],
        tools: #["Arbor press or pin punch"],
        acceptance: #{
          kind: "standoff",
          features: #["head_underside", "hub_top_face"],
        },
      },
      #{
        id: "ring_base",
        kind: "retaining_ring",
        part: "@ring-base",
        into: "LMP-0005",
        `interface`: "IF-001",
        direction: #[0, 0, 1],
        tools: #["External circlip pliers"],
        acceptance: #{ kind: "engaged", features: #["ring_groove"] },
        verify_joint: "J-001",
      },
      #{
        id: "press_elbow_pin",
        kind: "press_fit",
        part: "LMP-0006",
        into: "LMP-0002",
        `interface`: "IF-002",
        direction: #[0, -1, 0],
        tools: #["Arbor press or pin punch"],
        acceptance: #{
          kind: "standoff",
          features: #["head_underside", "cheek_face"],
        },
      },
      #{
        id: "ring_elbow",
        kind: "retaining_ring",
        part: "@ring-elbow",
        into: "LMP-0006",
        `interface`: "IF-002",
        direction: #[0, 1, 0],
        tools: #["External circlip pliers"],
        acceptance: #{ kind: "engaged", features: #["ring_groove"] },
        verify_joint: "J-002",
      },
      #{
        id: "press_head_pin",
        kind: "press_fit",
        part: "LMP-0007",
        into: "LMP-0003",
        `interface`: "IF-003",
        direction: #[0, -1, 0],
        tools: #["Arbor press or pin punch"],
        acceptance: #{
          kind: "standoff",
          features: #["head_underside", "cheek_face"],
        },
      },
      #{
        id: "ring_head",
        kind: "retaining_ring",
        part: "@ring-head",
        into: "LMP-0007",
        `interface`: "IF-003",
        direction: #[0, 1, 0],
        tools: #["External circlip pliers"],
        acceptance: #{ kind: "engaged", features: #["ring_groove"] },
        verify_joint: "J-003",
      }
    ],
  }
);
