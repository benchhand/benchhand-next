import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/manufacturing-materials/")
namespace Records.ManufacturingMaterials;

/** Material identity and properties with their conditions. A family profile (PLA+, nylon, PETG, aluminium) is guidance, never a grade specification; a grade profile names the manufacturer's grade. Printed, moulded, bulk, cast and wrought properties are different profiles; every property states its test standard, temperature, conditioning and, for printed forms, orientation. A typical_not_allowable profile holds only typical or estimated values, never design allowables. Density is never strength. Property names and their dimensions are manufacturing_intent.MATERIAL_PROPERTIES */
@summary("benchhand material profiles (hw/manufacturing/materials.yaml)")
@id("https://benchhand.github.io/benchhand/contracts/record/manufacturing-materials.schema.json")
@extension("x-version", "1.0.0")
model ManufacturingMaterials {
  profiles: manufacturing_materials_profile[];
}

/** dry as moulded or dried, moisture-conditioned, as received, or not stated */
union conditioning {
  "dry",
  "conditioned",
  "as_received",
  "unknown",
}

/** Elastic, flexural, shear and creep modulus: above 0 and at most 1200 GPa, diamond's */
@extension(
  "allOf",
  #[
    #{
      `if`: #{
        required: #["units"],
        properties: #{ units: #{ `const`: "GPa" } },
      },
      then: #{
        properties: #{
          value: #{ exclusiveMinimum: 0, maximum: 1200 },
          lower: #{ exclusiveMinimum: 0, maximum: 1200 },
          upper: #{ exclusiveMinimum: 0, maximum: 1200 },
        },
      },
    },
    #{
      `if`: #{
        required: #["units"],
        properties: #{ units: #{ `const`: "MPa" } },
      },
      then: #{
        properties: #{
          value: #{ exclusiveMinimum: 0, maximum: 1200000 },
          lower: #{ exclusiveMinimum: 0, maximum: 1200000 },
          upper: #{ exclusiveMinimum: 0, maximum: 1200000 },
        },
      },
    },
    #{
      `if`: #{
        required: #["units"],
        properties: #{ units: #{ `const`: "bar" } },
      },
      then: #{
        properties: #{
          value: #{ exclusiveMinimum: 0, maximum: 12000000 },
          lower: #{ exclusiveMinimum: 0, maximum: 12000000 },
          upper: #{ exclusiveMinimum: 0, maximum: 12000000 },
        },
      },
    }
  ]
)
union qty_modulus {
  unknown,
}

@extension(
  "if",
  #{ required: #["status"], properties: #{ status: #{ `const`: "known" } } }
)
@extension(
  "then",
  #{ properties: #{ value: #{ $ref: "#/$defs/qty_modulus" } } }
)
union fact_modulus {
  unknown,
}

/** Density: above 0 and at most 25 g/cm3; below 0.5 g/cm3 is unusual for a solid */
@extension("x-plausible", #{ min: 0.5, units: "g_cm3" })
@extension(
  "allOf",
  #[
    #{
      `if`: #{
        required: #["units"],
        properties: #{ units: #{ `const`: "g_cm3" } },
      },
      then: #{
        properties: #{
          value: #{ exclusiveMinimum: 0, maximum: 25 },
          lower: #{ exclusiveMinimum: 0, maximum: 25 },
          upper: #{ exclusiveMinimum: 0, maximum: 25 },
        },
      },
    },
    #{
      `if`: #{
        required: #["units"],
        properties: #{ units: #{ `const`: "kg_m3" } },
      },
      then: #{
        properties: #{
          value: #{ exclusiveMinimum: 0, maximum: 25000 },
          lower: #{ exclusiveMinimum: 0, maximum: 25000 },
          upper: #{ exclusiveMinimum: 0, maximum: 25000 },
        },
      },
    }
  ]
)
union qty_density {
  unknown,
}

@extension(
  "if",
  #{ required: #["status"], properties: #{ status: #{ `const`: "known" } } }
)
@extension(
  "then",
  #{ properties: #{ value: #{ $ref: "#/$defs/qty_density" } } }
)
union fact_density {
  unknown,
}

/** A temperature property: above absolute zero and at most 1000 deg_C; above 300 deg_C is unusual for a printed polymer */
@extension("x-plausible", #{ max: 300, units: "deg_C" })
@extension(
  "allOf",
  #[
    #{
      `if`: #{
        required: #["units"],
        properties: #{ units: #{ `const`: "deg_C" } },
      },
      then: #{
        properties: #{
          value: #{ exclusiveMinimum: -273.15, maximum: 1000 },
          lower: #{ exclusiveMinimum: -273.15, maximum: 1000 },
          upper: #{ exclusiveMinimum: -273.15, maximum: 1000 },
        },
      },
    },
    #{
      `if`: #{
        required: #["units"],
        properties: #{ units: #{ `const`: "K" } },
      },
      then: #{
        properties: #{
          value: #{ exclusiveMinimum: 0, maximum: 1273.15 },
          lower: #{ exclusiveMinimum: 0, maximum: 1273.15 },
          upper: #{ exclusiveMinimum: 0, maximum: 1273.15 },
        },
      },
    }
  ]
)
union qty_temperature {
  unknown,
}

@extension(
  "if",
  #{ required: #["status"], properties: #{ status: #{ `const`: "known" } } }
)
@extension(
  "then",
  #{ properties: #{ value: #{ $ref: "#/$defs/qty_temperature" } } }
)
union fact_temperature {
  unknown,
}

/** Poisson's ratio: 0 up to, not including, 0.5 */
@extension("x-plausible", #{ max: 0.45, units: "dimensionless" })
@extension(
  "allOf",
  #[
    #{
      `if`: #{
        required: #["units"],
        properties: #{ units: #{ `const`: "dimensionless" } },
      },
      then: #{
        properties: #{
          value: #{ minimum: 0, exclusiveMaximum: 0.5 },
          lower: #{ minimum: 0, exclusiveMaximum: 0.5 },
          upper: #{ minimum: 0, exclusiveMaximum: 0.5 },
        },
      },
    },
    #{
      `if`: #{
        required: #["units"],
        properties: #{ units: #{ `const`: "percent" } },
      },
      then: #{
        properties: #{
          value: #{ minimum: 0, exclusiveMaximum: 50 },
          lower: #{ minimum: 0, exclusiveMaximum: 50 },
          upper: #{ minimum: 0, exclusiveMaximum: 50 },
        },
      },
    }
  ]
)
union qty_poisson {
  unknown,
}

@extension(
  "if",
  #{ required: #["status"], properties: #{ status: #{ `const`: "known" } } }
)
@extension(
  "then",
  #{ properties: #{ value: #{ $ref: "#/$defs/qty_poisson" } } }
)
union fact_poisson {
  unknown,
}

/** The ratio of tensile strength fu to yield strength fy: at least 1, since fu is never below fy. EN 1993-1-1 3.2.2 recommends at least 1.10 for structural steel (clause number from a secondary source; the National Annex may change it) */
@extension(
  "allOf",
  #[
    #{
      `if`: #{
        required: #["units"],
        properties: #{ units: #{ `const`: "dimensionless" } },
      },
      then: #{
        properties: #{
          value: #{ minimum: 1 },
          lower: #{ minimum: 1 },
          upper: #{ minimum: 1 },
        },
      },
    },
    #{
      `if`: #{
        required: #["units"],
        properties: #{ units: #{ `const`: "percent" } },
      },
      then: #{
        properties: #{
          value: #{ minimum: 100 },
          lower: #{ minimum: 100 },
          upper: #{ minimum: 100 },
        },
      },
    }
  ]
)
union qty_fu_fy {
  unknown,
}

@extension(
  "if",
  #{ required: #["status"], properties: #{ status: #{ `const`: "known" } } }
)
@extension("then", #{ properties: #{ value: #{ $ref: "#/$defs/qty_fu_fy" } } })
union fact_fu_fy {
  unknown,
}

/** The gauge length the elongation after fracture was measured on. Elongations on different gauges are not comparable: ASME uses k=5, EN uses 5.65*sqrt(S0), ASTM E8 uses 50 mm or 2 in. A missing gauge means the value cannot be compared with a ductility threshold, so a gate treats the material as not shown ductile (unknown). The thresholds are percentages and the value is a ratio, so 14% is 0.14. EN 13445-2:2014 4.1.4 requires at least 14% on 5.65*sqrt(S0) for steels, and EN 1993-1-1 3.2.2 recommends at least 15% with fu/fy of at least 1.10; both clause numbers are from secondary sources and are not checked against the standards */
union gauge {
  "5.65sqrtS0",
  "5d",
  "A50mm",
  "A2in",
  "other",
}

@id("https://benchhand.github.io/benchhand/contracts/record/manufacturing-materials/profile.json")
@extension(
  "allOf",
  #[
    #{
      `if`: #{ properties: #{ level: #{ `const`: "family" } } },
      then: #{
        properties: #{
          grade: #{ $ref: "common.schema.json#/$defs/fact_open" },
        },
      },
    },
    #{
      `if`: #{ properties: #{ level: #{ `const`: "grade" } } },
      then: #{
        properties: #{
          grade: #{ $ref: "common.schema.json#/$defs/fact_known" },
        },
      },
    }
  ]
)
model manufacturing_materials_profile {
  id: Common.profile_id;

  @minValue(1)
  revision: integer;

  title: Common.text;
  level: "family" | "grade";
  family: Common.text;

  /** the structured family a guideline scope matches on, such as pla, petg, pa or tpu; unknown when not stated. It has no default */
  material_family?: scope_fact;

  /** the fill a guideline scope matches on, such as cf or gf; not applicable for an unfilled material. It has no default */
  filler?: scope_fact;

  /** the Shore hardness a guideline scope matches on, such as 95A or 85A. It has no default */
  shore?: scope_fact;

  grade: Common.text_fact;
  manufacturer?: Common.text_fact;

  /** the standard or datasheet designation the grade conforms to */
  specification?: Common.text_fact;

  form:
    | "printed"
    | "bulk"
    | "wrought"
    | "cast"
    | "moulded"
    | "sheet"
    | "rod"
    | "film"
    | "purchased"
    | "unknown";
  process_state: {
    /** the route kind that made the tested material, or unknown */
    @oneOf
    process: Common.route_kind | Common.fact_open;

    orientation?: Common.text;
    layup?: Common.text;
    temper?: Common.text;
    conditioning: conditioning;
    lot?: Common.text;
    notes?: Common.text;
  };
  typical_not_allowable: boolean;
  properties: `property`[];

  /** family guidance and cautions, such as fibre fill wear on nozzles and mating surfaces; never a grade allowable */
  guidance?: Common.texts;

  note?: Common.text;
}

/** A fact a guideline scope matches on: a known value is lowercase, as scope names are, so 'PLA' is refused */
@extension(
  "allOf",
  #[
    #{ $ref: "common.schema.json#/$defs/text_fact" },
    #{
      `if`: #{
        required: #["status"],
        properties: #{ status: #{ `const`: "known" } },
      },
      then: #{ properties: #{ value: #{ pattern: "^[a-z0-9][a-z0-9_.-]*$" } } },
    }
  ]
)
union scope_fact {
  unknown,
}

@extension(
  "allOf",
  #[
    #{
      `if`: #{
        required: #["name"],
        properties: #{
          name: #{
            `enum`: #[
              "youngs_modulus",
              "flexural_modulus",
              "shear_modulus",
              "creep_modulus"
            ],
          },
        },
      },
      then: #{ properties: #{ value: #{ $ref: "#/$defs/fact_modulus" } } },
    },
    #{
      `if`: #{
        required: #["name"],
        properties: #{ name: #{ `enum`: #["density"] } },
      },
      then: #{ properties: #{ value: #{ $ref: "#/$defs/fact_density" } } },
    },
    #{
      `if`: #{
        required: #["name"],
        properties: #{
          name: #{
            `enum`: #[
              "heat_deflection_temperature",
              "vicat_softening_temperature",
              "glass_transition_temperature",
              "melting_temperature",
              "max_service_temperature"
            ],
          },
        },
      },
      then: #{ properties: #{ value: #{ $ref: "#/$defs/fact_temperature" } } },
    },
    #{
      `if`: #{
        required: #["name"],
        properties: #{ name: #{ `enum`: #["poisson_ratio"] } },
      },
      then: #{ properties: #{ value: #{ $ref: "#/$defs/fact_poisson" } } },
    },
    #{
      `if`: #{
        required: #["name"],
        properties: #{ name: #{ `enum`: #["fu_fy_ratio"] } },
      },
      then: #{ properties: #{ value: #{ $ref: "#/$defs/fact_fu_fy" } } },
    },
    #{
      `if`: #{
        required: #["name"],
        properties: #{ name: #{ not: #{ `const`: "elongation_at_break" } } },
      },
      then: #{
        properties: #{ conditions: #{ not: #{ required: #["gauge"] } } },
      },
    }
  ]
)
model `property` {
  name: Common.semantic_id;
  value: Common.quantity_fact;
  conditions: {
    test_standard: Common.text_fact;
    temperature: Common.quantity_fact;
    conditioning: conditioning;

    /** the print or grain orientation of the specimen */
    orientation?: Common.text_fact;

    /** allowed on elongation_at_break only; optional */
    gauge?: gauge;

    specimen?: Common.text;
    rate?: Common.text;
    notes?: Common.text;
  };
}

@@example(
  ManufacturingMaterials,
  #{
    profiles: #[
      #{
        id: "petg",
        revision: 1,
        title: "PETG, printed (family)",
        level: "family",
        family: "PETG",
        grade: #{
          status: "not_applicable",
          reason: "family guidance only; no filament grade is selected",
        },
        form: "printed",
        process_state: #{
          process: "fdm",
          conditioning: "unknown",
          notes: "no filament lot, drying or print orientation is recorded, so no property is stated",
        },
        typical_not_allowable: true,
        properties: #[],
      }
    ],
  }
);
