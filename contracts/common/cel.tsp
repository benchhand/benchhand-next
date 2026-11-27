import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/common/cel/")
namespace Common.Cel;

/** Provisional: the CEL expression types (ADR-0014). Every CEL field of every contract refers to CelExpression or CelExpressions here, and that $ref is how the flow interpreter finds them all */
@summary("benchhand CEL expression types, provisional")
@id("https://benchhand.github.io/benchhand/contracts/common/cel.schema.json")
@extension("x-version", "0.1.0")
@extension("x-status", "provisional")
union Cel {
  unknown,
}

/** A CEL expression. A standalone one, in flow.yaml or a policy contribution, is checked at load by cel-expr-python against the activation types generated from the contracts; one in a rule list is compiled before load by the pinned cel-go tool (ADR-0020). The schema only checks that it is a non-empty string. x-cel is a readable annotation that nothing depends on */
@extension("x-cel", true)
@minLength(1)
scalar CelExpression extends string;

/** One or more CEL expressions, each of which must hold */
@minItems(1)
model CelExpressions is CelExpression[];

@@example(Cel, "version.fast_checks.all(c, c.status == \"pass\")");
@@example(CelExpression, "version.fast_checks.all(c, c.status == \"pass\")");
