import "@typespec/json-schema";
import "../common/cel.tsp";
import "../flow/rules.tsp";
import "../record/common.tsp";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/policy/contribution/")
namespace Policy.Contribution;

/** Provisional: what one policy provider adds to the flow (ADR-0014): rule-list files, by kind, in the shape of flow/rules.schema.json, and CEL requirements for the gates of flow.yaml. Each file is relative to the provider's root. The lists of one kind are evaluated in a fixed order: the contributions in ascending provider name, then flow.yaml's own list. For checks_by_iteration, dispatch and fidelity the first list whose output isn't the kind's no-match value gives the value; the no-match values are [], "unknown" and "none", and a contributed list ends with its kind's. For rigor every list must give true. A gate's contributed requirements must hold as well as flow.yaml's, and are checked after them in the same provider order. A requirement for a step the gate doesn't have, or for a gate flow.yaml doesn't declare, is refused when the flow loads. The owner has yet to confirm this order */
@summary("benchhand policy provider contribution, provisional")
@id("https://benchhand.github.io/benchhand/contracts/policy/contribution.schema.json")
@extension("x-version", "0.1.0")
@extension("x-status", "provisional")
@extension("minProperties", 1)
model PolicyContribution {
  rules?: PolicyRuleLists;

  /** Requirements by the gate id flow.yaml declares */
  @extension("propertyNames", Records.Common.gate_id)
  @minProperties(1)
  gates?: Record<PolicyGateRequirements>;
}

/** The contributed rule-list files, by kind: at least one */
@extension("minProperties", 1)
model PolicyRuleLists is OptionalProperties<Flow.Rules.FlowRuleLists>;

/** Extra requirements for the steps of one gate */
@extension("minProperties", 1)
model PolicyGateRequirements {
  provisional?: Common.Cel.CelExpressions;
  full?: Common.Cel.CelExpressions;
  human?: Common.Cel.CelExpressions;
}

@@example(
  PolicyContribution,
  #{
    rules: #{ rigor: #{ file: "rules/rigor.rules.yaml", rules_version: 1 } },
    gates: #{
      design_freeze: #{
        human: #["record.verification.all(v, v.reviewed_by.present)"],
      },
    },
  }
);
@@example(
  PolicyContribution,
  #{
    rules: #{
      dispatch: #{
        file: "rules/welding-dispatch.rules.yaml",
        rules_version: 1,
      },
    },
  }
);
