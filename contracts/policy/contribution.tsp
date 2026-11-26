import "@typespec/json-schema";
import "../common/cel.tsp";
import "../flow/flow.tsp";
import "../record/common.tsp";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/policy/contribution/")
namespace Policy.Contribution;

/** Provisional: what one policy provider adds to the flow (ADR-0014): rules for flow.yaml's rule lists and CEL requirements for its gates. The merge order is fixed. For each rule list, the contributed rules come before flow.yaml's rules, so a contributed rule matches first; the contributions are taken in ascending provider name, each in its own order. A gate's contributed requirements must hold as well as flow.yaml's, and are checked after them in the same provider order. A requirement for a step the gate doesn't have, or for a gate flow.yaml doesn't declare, is refused when the flow loads */
@summary("benchhand policy provider contribution, provisional")
@id("https://benchhand.github.io/benchhand/contracts/policy/contribution.schema.json")
@extension("x-version", "0.1.0")
@extension("x-status", "provisional")
@extension("minProperties", 1)
model PolicyContribution {
  rules?: PolicyContributionRules;

  /** Requirements by the gate id flow.yaml declares */
  @extension("propertyNames", Records.Common.gate_id)
  @minProperties(1)
  gates?: Record<PolicyGateRequirements>;
}

@extension("minProperties", 1)
model PolicyContributionRules {
  @minItems(1)
  checks_by_iteration?: Flow.Flow.FlowCheckRule[];

  @minItems(1)
  dispatch?: Flow.Flow.FlowDispatchRule[];

  @minItems(1)
  fidelity?: Flow.Flow.FlowFidelityRule[];

  @minItems(1)
  rigor?: Flow.Flow.FlowRigorRule[];
}

/** Extra requirements for the steps of one gate */
@extension("minProperties", 1)
model PolicyGateRequirements {
  provisional?: Flow.Flow.CelExpressions;
  full?: Flow.Flow.CelExpressions;
  human?: Flow.Flow.CelExpressions;
}

@@example(
  PolicyContribution,
  #{
    rules: #{
      rigor: #[
        #{
          when: "policy.rigor == \"regulated\"",
          then: #["record.requirements.all(r, r.standard.present)"],
        }
      ],
    },
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
      dispatch: #[
        #{
          when: "obligation.family.startsWith(\"process.welding.\")",
          then: #["process.welding"],
        }
      ],
    },
  }
);
