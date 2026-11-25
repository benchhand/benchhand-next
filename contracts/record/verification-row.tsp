import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/verification-row/")
namespace Records.VerificationRow;

/** One hw/verification.csv row; the column order is the property order */
@summary("benchhand verification matrix row (hw/verification.csv)")
@id("https://benchhand.github.io/benchhand/contracts/record/verification-row.schema.json")
@extension("x-version", "1.0.0")
model VerificationRow {
  requirement: Common.requirement_id;
  method: VerificationRowMethod;

  @minLength(1)
  criteria: string;

  result: VerificationRowResult;
  evidence: string;
}

@extension("x-inline", true)
enum VerificationRowMethod {
  I,
  A,
  D,
  T,
}

@extension("x-inline", true)
enum VerificationRowResult {
  planned,
  pass,
  fail,
  waived,
  not_assessed,
}

@@extension(
  VerificationRow,
  "examples",
  #[
    #{
      requirement: "REQ-001",
      method: "T",
      criteria: "Measure head travel on both sides of nominal; each direction is at least 45 degrees.",
      result: "planned",
      evidence: "",
    },
    #{
      requirement: "REQ-002",
      method: "T",
      criteria: "Sweep the elbow joint and verify both endpoints.",
      result: "planned",
      evidence: "",
    }
  ]
);
