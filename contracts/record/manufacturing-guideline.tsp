import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/manufacturing-guideline/")
namespace Records.ManufacturingGuideline;

/** One file of published design-for-manufacturing guidance for a process. A guideline is never a calibration: the grade of a resolved limit is the kind of the source it cites, and a resolved criterion cites a source of kind guideline (id, revision and sha256 of this file), never the inner citations. Scope is declarative selectors, never expressions; which layer a limit sits at follows from how specific its scope is. A machine is reached only through the capability profile's guidelines pin. A guideline may only tighten the limit of a less specific one; a limit that relaxes needs `relaxes` with a reason and a citation. A value a source does not publish is left out, never defaulted. Layer height, shrinkage and Z strength are not guideline limits: they are a capability parameter and material-profile properties */
@summary("benchhand manufacturing guideline set (hw/manufacturing/guidelines/*.yaml)")
@id("https://benchhand.github.io/benchhand/contracts/record/manufacturing-guideline.schema.json")
@extension("x-version", "1.0.0")
model ManufacturingGuideline {
  schema_version: 1;
  id: Common.guideline_id;

  @minValue(1)
  revision: integer;

  title: Common.text;

  /** parent guideline ids, in order; a later parent is read after an earlier one */
  @minItems(1)
  @uniqueItems
  `extends`?: Common.guideline_id[];

  /** an abstract set is reached through extends; it is matched on its own only when the capability profile's pin names it */
  abstract?: boolean;

  scope: scope;
  limits: manufacturing_guideline_limit[];
}

@minItems(1)
@uniqueItems
model names is ManufacturingGuidelineNamesItem[];

@extension("x-inline", true)
@pattern("^[a-z0-9][a-z0-9_.-]*$")
scalar ManufacturingGuidelineNamesItem extends string;

/** What the set applies to. Every selector present must match; a set with more selectors is more specific. nozzle_diameter is the interval of nozzle diameters it covers */
model scope {
  process: Common.route_kind;
  material_family?: names;
  filler?: names;
  shore?: names;

  @extension(
    "allOf",
    #[
      #{ $ref: "common.schema.json#/$defs/quantity" },
      #{
        $ref: "manufacturing-capabilities.schema.json#/$defs/qty_nozzle_diameter",
      }
    ]
  )
  @extension("required", #["lower", "upper"])
  @extension("x-keyword-order", #["allOf", "required"])
  nozzle_diameter?: unknown;

  nozzle_material?: names;
}

@extension("minProperties", 1)
model applies_to {
  orientation?: Common.semantic_id;
  feature?: Common.semantic_id;
}

/** factor times the profile's line width (or nozzle diameter), never below floor */
model relative {
  relative_to: "nozzle_diameter" | "line_width";

  @minValueExclusive(0)
  factor: float64;

  @extension("allOf", #[#{ $ref: "common.schema.json#/$defs/quantity" }])
  @extension("required", #["value"])
  @extension("x-keyword-order", #["allOf", "required"])
  floor: unknown;
}

/** a limit less strict than the less specific one it overrides needs the reason and the source */
model relaxes {
  reason: Common.text;
  citation: Common.source;
}

@id("https://benchhand.github.io/benchhand/contracts/record/manufacturing-guideline/limit.json")
@extension(
  "allOf",
  #[
    #{
      `if`: #{
        properties: #{ operator: #{ `enum`: #[">=", "<=", ">", "<"] } },
      },
      then: #{
        oneOf: #[
          #{
            required: #["quantity"],
            properties: #{ quantity: #{ required: #["value"] } },
            not: #{ required: #["relative"] },
          },
          #{ required: #["relative"], not: #{ required: #["quantity"] } }
        ],
        not: #{ required: #["value"] },
      },
    },
    #{
      `if`: #{ properties: #{ operator: #{ `const`: "between" } } },
      then: #{
        required: #["quantity"],
        properties: #{ quantity: #{ required: #["lower", "upper"] } },
        not: #{
          anyOf: #[#{ required: #["relative"] }, #{ required: #["value"] }],
        },
      },
    },
    #{
      `if`: #{ properties: #{ operator: #{ `enum`: #["equals", "one_of"] } } },
      then: #{
        not: #{
          anyOf: #[#{ required: #["quantity"] }, #{ required: #["relative"] }],
        },
        `if`: #{
          properties: #{ characteristic: #{ `const`: "nozzle_diameter" } },
          required: #["characteristic"],
        },
        then: #{
          properties: #{ operator: #{ `const`: "one_of" } },
          required: #["quantities"],
          not: #{ required: #["value"] },
        },
        `else`: #{
          required: #["value"],
          properties: #{
            characteristic: #{ `enum`: #["enclosure", "nozzle_material"] },
          },
        },
      },
    },
    #{
      `if`: #{ required: #["quantities"] },
      then: #{
        required: #["characteristic"],
        properties: #{
          characteristic: #{ `const`: "nozzle_diameter" },
          operator: #{ `const`: "one_of" },
        },
      },
    },
    #{
      `if`: #{ properties: #{ operator: #{ `const`: "equals" } } },
      then: #{ properties: #{ value: #{ type: #["string", "boolean"] } } },
    },
    #{
      `if`: #{ properties: #{ operator: #{ `const`: "one_of" } } },
      then: #{ properties: #{ value: #{ type: "array" } } },
    },
    #{
      `if`: #{
        properties: #{ characteristic: #{ `const`: "bridge_span" } },
        required: #["characteristic"],
      },
      then: #{
        properties: #{
          quantity: #{
            $ref: "manufacturing-capabilities.schema.json#/$defs/qty_bridge_span",
          },
          relative: #{
            properties: #{
              floor: #{
                $ref: "manufacturing-capabilities.schema.json#/$defs/qty_bridge_span",
              },
            },
          },
        },
      },
    },
    #{
      `if`: #{
        properties: #{ characteristic: #{ `const`: "overhang_angle" } },
        required: #["characteristic"],
      },
      then: #{
        properties: #{
          quantity: #{
            $ref: "manufacturing-capabilities.schema.json#/$defs/qty_overhang_angle",
          },
          relative: #{
            properties: #{
              floor: #{
                $ref: "manufacturing-capabilities.schema.json#/$defs/qty_overhang_angle",
              },
            },
          },
        },
      },
    },
    #{
      `if`: #{
        properties: #{ characteristic: #{ `const`: "min_wall" } },
        required: #["characteristic"],
      },
      then: #{
        properties: #{
          quantity: #{
            $ref: "manufacturing-capabilities.schema.json#/$defs/qty_min_wall",
          },
          relative: #{
            properties: #{
              floor: #{
                $ref: "manufacturing-capabilities.schema.json#/$defs/qty_min_wall",
              },
            },
          },
        },
      },
    },
    #{
      `if`: #{
        properties: #{ characteristic: #{ `const`: "nozzle_diameter" } },
        required: #["characteristic"],
      },
      then: #{
        properties: #{
          quantity: #{
            $ref: "manufacturing-capabilities.schema.json#/$defs/qty_nozzle_diameter",
          },
          relative: #{
            properties: #{
              floor: #{
                $ref: "manufacturing-capabilities.schema.json#/$defs/qty_nozzle_diameter",
              },
            },
          },
        },
      },
    },
    #{
      `if`: #{
        properties: #{ characteristic: #{ `const`: "min_feature" } },
        required: #["characteristic"],
      },
      then: #{
        properties: #{
          quantity: #{
            $ref: "manufacturing-capabilities.schema.json#/$defs/qty_min_feature",
          },
          relative: #{
            properties: #{
              floor: #{
                $ref: "manufacturing-capabilities.schema.json#/$defs/qty_min_feature",
              },
            },
          },
        },
      },
    },
    #{
      `if`: #{
        properties: #{ characteristic: #{ `const`: "min_hole" } },
        required: #["characteristic"],
      },
      then: #{
        properties: #{
          quantity: #{
            $ref: "manufacturing-capabilities.schema.json#/$defs/qty_min_hole",
          },
          relative: #{
            properties: #{
              floor: #{
                $ref: "manufacturing-capabilities.schema.json#/$defs/qty_min_hole",
              },
            },
          },
        },
      },
    },
    #{
      `if`: #{
        properties: #{ characteristic: #{ `const`: "sliding_clearance" } },
        required: #["characteristic"],
      },
      then: #{
        properties: #{
          quantity: #{
            $ref: "manufacturing-capabilities.schema.json#/$defs/qty_clearance_per_side",
          },
          relative: #{
            properties: #{
              floor: #{
                $ref: "manufacturing-capabilities.schema.json#/$defs/qty_clearance_per_side",
              },
            },
          },
        },
      },
    },
    #{
      `if`: #{
        properties: #{
          characteristic: #{
            `enum`: #[
              "hole_diameter_deviation",
              "dimensional_deviation",
              "profile_deviation"
            ],
          },
        },
        required: #["characteristic"],
      },
      then: #{
        properties: #{
          quantity: #{
            $ref: "manufacturing-capabilities.schema.json#/$defs/qty_deviation",
          },
          relative: #{
            properties: #{
              floor: #{
                $ref: "manufacturing-capabilities.schema.json#/$defs/qty_deviation",
              },
            },
          },
        },
      },
    },
    #{
      `if`: #{
        properties: #{
          characteristic: #{ `enum`: #["enclosure", "nozzle_material"] },
        },
        required: #["characteristic"],
      },
      then: #{ properties: #{ operator: #{ `enum`: #["equals", "one_of"] } } },
    },
    #{
      `if`: #{
        properties: #{ characteristic: #{ `const`: "enclosure" } },
        required: #["characteristic"],
      },
      then: #{
        properties: #{
          value: #{
            description: "a boolean fact: the requirement is true or false",
            anyOf: #[
              #{ type: "boolean" },
              #{ type: "array", items: #{ type: "boolean" } }
            ],
          },
        },
      },
    },
    #{
      `if`: #{
        properties: #{ characteristic: #{ `const`: "nozzle_material" } },
        required: #["characteristic"],
      },
      then: #{
        properties: #{
          value: #{
            description: "lowercase, like the scope names and the material facts",
            anyOf: #[
              #{ type: "string", pattern: "^[a-z0-9][a-z0-9_.-]*$" },
              #{
                type: "array",
                items: #{ type: "string", pattern: "^[a-z0-9][a-z0-9_.-]*$" },
              }
            ],
          },
        },
      },
    }
  ]
)
model manufacturing_guideline_limit {
  /** only a characteristic whose quantity the capability schema bounds, so no limit holds an unbounded value */
  characteristic:
    | "bridge_span"
    | "overhang_angle"
    | "min_wall"
    | "min_feature"
    | "min_hole"
    | "nozzle_diameter"
    | "hole_diameter_deviation"
    | "dimensional_deviation"
    | "profile_deviation"
    | "sliding_clearance"
    | "enclosure"
    | "nozzle_material";

  operator: ">=" | "<=" | ">" | "<" | "between" | "equals" | "one_of";

  /** the limit as a value (>=, <=) or an interval (between), in one unit */
  quantity?: Common.quantity;

  relative?: relative;

  /** the discrete nozzle diameters a one_of limit on nozzle_diameter allows, each one value; compared as whole micrometres */
  @minItems(1)
  quantities?: ManufacturingGuidelineManufacturingGuidelineLimitQuantitiesItem[];

  /** the categorical requirement of equals and one_of, such as enclosure true or nozzle_material hardened_steel; no default */
  @minItems(1)
  @uniqueItems
  @extension("items", ManufacturingGuidelineItems)
  value?: string | boolean | unknown[];

  applies_to?: applies_to;

  /** true when the cited sources disagree; the stricter value applies */
  disputed?: boolean;

  relaxes?: relaxes;
  citations: Common.sources;
}

@extension("x-inline", true)
@extension(
  "allOf",
  #[
    #{ $ref: "common.schema.json#/$defs/quantity" },
    #{
      $ref: "manufacturing-capabilities.schema.json#/$defs/qty_nozzle_diameter",
    }
  ]
)
@extension("required", #["value"])
@extension("x-keyword-order", #["allOf", "required"])
union ManufacturingGuidelineManufacturingGuidelineLimitQuantitiesItem {
  unknown,
}

@extension("x-inline", true)
@extension("minLength", 1)
union ManufacturingGuidelineItems {
  string,
  boolean,
}

@@extension(
  ManufacturingGuideline,
  "examples",
  #[
    #{
      schema_version: 1,
      id: "fdm.generic",
      revision: 2,
      title: "FDM generic design-for-manufacturing guidance",
      scope: #{ process: "fdm" },
      limits: #[
        #{
          characteristic: "overhang_angle",
          operator: "<=",
          quantity: #{ value: 45, units: "deg" },
          citations: #[
            #{
              kind: "supplier",
              reference: "Hubs, How to design parts for FDM 3D printing",
              url: "https://www.hubs.com/knowledge-base/how-design-parts-fdm-3d-printing/",
              accessed: "2026-11-18",
              locator: "Overhangs: an overhang can usually be printed up to 45 degrees without compromising quality",
            },
            #{
              kind: "supplier",
              reference: "Hubs, Key design considerations for 3D printing",
              url: "https://www.hubs.com/knowledge-base/key-design-considerations-3d-printing/",
              accessed: "2026-11-18",
              locator: "FAQ on overhangs: try not to design parts with angles over 45 degrees",
            }
          ],
        },
        #{
          characteristic: "bridge_span",
          operator: "<",
          quantity: #{ value: 5, units: "mm" },
          citations: #[
            #{
              kind: "supplier",
              reference: "Hubs, How to design parts for FDM 3D printing",
              url: "https://www.hubs.com/knowledge-base/how-design-parts-fdm-3d-printing/",
              accessed: "2026-11-18",
              locator: "Bridging, key design consideration: sagging or support marks unless the bridge is less than 5 mm",
            }
          ],
        },
        #{
          characteristic: "min_wall",
          operator: ">=",
          quantity: #{ value: 0.8, units: "mm" },
          citations: #[
            #{
              kind: "supplier",
              reference: "Hubs, Key design considerations for 3D printing",
              url: "https://www.hubs.com/knowledge-base/key-design-considerations-3d-printing/",
              accessed: "2026-11-18",
              locator: "FAQ on minimal wall thickness: wall thicknesses of 0.8 mm and over",
            },
            #{
              kind: "supplier",
              reference: "Protolabs, Fused deposition modeling (FDM)",
              url: "https://www.protolabs.com/services/3d-printing/fused-deposition-modeling/",
              accessed: "2026-11-18",
              locator: "FDM specifications table, Unsupported/Supported Walls: minimum 0.8 mm",
            }
          ],
        },
        #{
          characteristic: "min_wall",
          operator: ">=",
          relative: #{
            relative_to: "line_width",
            factor: 3,
            floor: #{ value: 0.8, units: "mm" },
          },
          citations: #[
            #{
              kind: "supplier",
              reference: "Prusa Knowledge Base, Modeling with 3D printing in mind",
              url: "https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135",
              accessed: "2026-11-18",
              locator: "Fine details and wall thickness table, 0.4 mm nozzle: 1, 2, 3 and 4 perimeters are about 0.45, 0.9, 1.35 and 1.8 mm",
            },
            #{
              kind: "supplier",
              reference: "Protolabs, Fused deposition modeling (FDM)",
              url: "https://www.protolabs.com/services/3d-printing/fused-deposition-modeling/",
              accessed: "2026-11-18",
              locator: "FDM specifications table, Unsupported/Supported Walls: minimum 0.8 mm (the floor)",
            }
          ],
        },
        #{
          characteristic: "min_feature",
          operator: ">=",
          quantity: #{ value: 2.0, units: "mm" },
          citations: #[
            #{
              kind: "supplier",
              reference: "Protolabs, Fused deposition modeling (FDM)",
              url: "https://www.protolabs.com/services/3d-printing/fused-deposition-modeling/",
              accessed: "2026-11-18",
              locator: "FDM specifications table, Minimum Feature Size: 2.0 mm",
            }
          ],
        },
        #{
          characteristic: "min_hole",
          operator: ">=",
          quantity: #{ value: 2.0, units: "mm" },
          citations: #[
            #{
              kind: "supplier",
              reference: "Protolabs, Fused deposition modeling (FDM)",
              url: "https://www.protolabs.com/services/3d-printing/fused-deposition-modeling/",
              accessed: "2026-11-18",
              locator: "FDM specifications table, Minimum Hole Diameter: 2.0 mm",
            }
          ],
        },
        #{
          characteristic: "sliding_clearance",
          operator: ">=",
          quantity: #{ value: 0.3, units: "mm" },
          citations: #[
            #{
              kind: "supplier",
              reference: "Prusa Knowledge Base, Modeling with 3D printing in mind",
              url: "https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135",
              accessed: "2026-11-20",
              locator: "Tolerances: an initial good measurement for movable parts is at least 0.3 mm. The source does not say per side or diametral; this set reads it per side, the stricter reading",
            }
          ],
        }
      ],
    }
  ]
);
