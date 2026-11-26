import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/common/cel/")
namespace Common.Cel;

/** Provisional: a CEL expression (ADR-0014). Every CEL field of every contract refers to this one type, and the $ref is how the flow interpreter finds them all; x-cel is a readable annotation that nothing depends on. The interpreter compiles and type-checks each expression at load, against activation types generated from the contracts; the schema only checks that it is a non-empty string */
@summary("benchhand CEL expression, provisional")
@id("https://benchhand.github.io/benchhand/contracts/common/cel.schema.json")
@extension("x-version", "0.1.0")
@extension("x-status", "provisional")
@extension("x-cel", true)
@minLength(1)
scalar CelExpression extends string;

@@example(CelExpression, "version.fast_checks.all(c, c.status == \"pass\")");
