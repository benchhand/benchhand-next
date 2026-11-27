// SPDX-FileCopyrightText: 2026 Sjors Robroek
//
// SPDX-License-Identifier: MPL-2.0

import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/bom-row/")
namespace Records.BomRow;

/** One hw/bom.csv row. The column order is the property order: the required columns, then optionally all seven procurement columns together. An empty cell is null, so a text value is never empty */
@summary("benchhand EBOM row (hw/bom.csv)")
@id("https://benchhand.github.io/benchhand/contracts/record/bom-row.schema.json")
@extension("x-version", "1.0.0")
@extension(
  "dependentRequired",
  #{
    unit: #[
      "designation",
      "manufacturer",
      "manufacturer_part_number",
      "supplier_part_number",
      "specification_reference",
      "specification_revision"
    ],
    designation: #[
      "unit",
      "manufacturer",
      "manufacturer_part_number",
      "supplier_part_number",
      "specification_reference",
      "specification_revision"
    ],
    manufacturer: #[
      "unit",
      "designation",
      "manufacturer_part_number",
      "supplier_part_number",
      "specification_reference",
      "specification_revision"
    ],
    manufacturer_part_number: #[
      "unit",
      "designation",
      "manufacturer",
      "supplier_part_number",
      "specification_reference",
      "specification_revision"
    ],
    supplier_part_number: #[
      "unit",
      "designation",
      "manufacturer",
      "manufacturer_part_number",
      "specification_reference",
      "specification_revision"
    ],
    specification_reference: #[
      "unit",
      "designation",
      "manufacturer",
      "manufacturer_part_number",
      "supplier_part_number",
      "specification_revision"
    ],
    specification_revision: #[
      "unit",
      "designation",
      "manufacturer",
      "manufacturer_part_number",
      "supplier_part_number",
      "specification_reference"
    ],
  }
)
model BomRow {
  @minValue(0)
  level: integer;

  PN: Common.pn;

  @pattern("^(X[1-9][0-9]*|[A-HJ-NPRTUVWY])$")
  rev: string | null;

  @minValue(1)
  qty: integer;

  @minLength(1)
  title: string | null;

  @minLength(1)
  material: string | null;

  process: Common.primary_process | null;

  @extension("type", #["string", "null"])
  make_buy: "make" | "buy" | null;

  @minLength(1)
  supplier: string | null;

  /** grams, copied from the part mass_target */
  @minValueExclusive(0)
  @maxValue(10000000)
  @extension("x-plausible", #{ max: 50000 })
  mass: float64 | null;

  /** what qty counts; the BOM counts STEP instances */
  unit?: BomRowUnit;

  @minLength(1)
  designation?: string | null;

  @minLength(1)
  manufacturer?: string | null;

  @minLength(1)
  manufacturer_part_number?: string | null;

  @minLength(1)
  supplier_part_number?: string | null;

  @minLength(1)
  specification_reference?: string | null;

  @minLength(1)
  specification_revision?: string | null;
}

@extension("x-inline", true)
union BomRowUnit {
  "pcs",
}

@@example(
  BomRow,
  #{
    level: 1,
    PN: "LMP-0001",
    rev: "X1",
    qty: 1,
    title: "Base plate and pivot boss",
    material: "PETG",
    process: "fdm",
    make_buy: "make",
    supplier: null,
    mass: 313,
    unit: "pcs",
    designation: null,
    manufacturer: null,
    manufacturer_part_number: null,
    supplier_part_number: null,
    specification_reference: null,
    specification_revision: null,
  }
);
@@example(
  BomRow,
  #{
    level: 1,
    PN: "LMP-0002",
    rev: "X1",
    qty: 1,
    title: "Lower link",
    material: "Aluminum 6061-T6",
    process: "cnc",
    make_buy: "make",
    supplier: null,
    mass: 153,
    unit: "pcs",
    designation: null,
    manufacturer: null,
    manufacturer_part_number: null,
    supplier_part_number: null,
    specification_reference: null,
    specification_revision: null,
  }
);
@@example(
  BomRow,
  #{
    level: 1,
    PN: "LMP-0001",
    rev: "X1",
    qty: 1,
    title: "Base plate and pivot boss",
    material: "PETG",
    process: "fdm",
    make_buy: "make",
    supplier: null,
    mass: 313,
  }
);
