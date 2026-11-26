import "@typespec/json-schema";
import "../common/cel.tsp";
import "../flow/rules.tsp";
import "../record/common.tsp";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/policy/contribution/")
namespace Policy.Contribution;

/** Provisional: what one policy provider adds to the flow (ADR-0014): rule lists in the shape of flow/<kind>.rules.yaml, and CEL requirements for the gates of flow.yaml. The merge order is fixed. A contributed rule list's rules come before the rules of the flow's list of the same kind, so a contributed rule matches first; the contributions are taken in ascending provider name, each in its own order. A gate's contributed requirements must hold as well as flow.yaml's, and are checked after them in the same provider order. A requirement for a step the gate doesn't have, or for a gate flow.yaml doesn't declare, is refused when the flow loads */
@summary("benchhand policy provider contribution, provisional")
@id("https://benchhand.github.io/benchhand/contracts/policy/contribution.schema.json")
@extension("x-version", "0.1.0")
@extension("x-status", "provisional")
@extension("minProperties", 1)
model PolicyContribution {
  @minItems(1)
  rules?: Flow.Rules.RuleList[];

  /** Requirements by the gate id flow.yaml declares */
  @extension("propertyNames", Records.Common.gate_id)
  @minProperties(1)
  gates?: Record<PolicyGateRequirements>;
}

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
    rules: #[
      #{
        rules_version: 1,
        kind: "rigor",
        rules: #[
          #{
            when: "policy.rigor == \"regulated\"",
            then: #["record.requirements.all(r, r.standard.present)"],
          }
        ],
      }
    ],
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
    rules: #[
      #{
        rules_version: 1,
        kind: "dispatch",
        rules: #[
          #{
            when: "obligation.family.startsWith(\"process.welding.\")",
            then: #["process.welding"],
          }
        ],
      }
    ],
  }
);
