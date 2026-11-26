import "@typespec/json-schema";
import "../common/cel.tsp";

using TypeSpec.JsonSchema;
using Common.Cel;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/flow/rules/")
namespace Flow.Rules;

/** Provisional: one rule-list file, flow/<kind>.rules.yaml (ADR-0014). A rule list replaces a decision table: an ordered, first-match list of {when, then} rules, where the first rule whose when holds gives the value. kind names the list and decides the shape of then. checks_by_iteration gives the checks to run at an iteration (inner, commit, provisional, full, design_freeze, release) and stage, in run order; no match runs none. dispatch gives the process-check handlers for an obligation, from its process, operation and material; no match means UNKNOWN coverage, never a pass. fidelity gives the form-check fidelity at a stage. rigor gives requirements that hold as well as a gate's own under a rigor policy such as regulated */
@summary("benchhand rule list (flow/<kind>.rules.yaml), provisional")
@id("https://benchhand.github.io/benchhand/contracts/flow/rules.schema.json")
@extension("x-version", "0.1.0")
@extension("x-status", "provisional")
@oneOf
union RuleList {
  ChecksByIterationRules,
  DispatchRules,
  FidelityRules,
  RigorRules,
}

model ChecksByIterationRules {
  rules_version: 1;
  kind: "checks_by_iteration";
  rules: ChecksByIterationRule[];
}

model DispatchRules {
  rules_version: 1;
  kind: "dispatch";
  rules: DispatchRule[];
}

model FidelityRules {
  rules_version: 1;
  kind: "fidelity";
  rules: FidelityRule[];
}

model RigorRules {
  rules_version: 1;
  kind: "rigor";
  rules: RigorRule[];
}

/** A check id, such as static.changed_only */
@pattern("^[a-z][a-z0-9_]*(\\.[a-z0-9_]+)*$")
scalar CheckId extends string;

/** A process-check handler id, such as process.fdm */
@pattern("^[a-z][a-z0-9_]*(\\.[a-z0-9_]+)*$")
scalar HandlerId extends string;

model ChecksByIterationRule {
  when: CelExpression;
  then: CheckSelection[];
}

/** A check that always runs when its rule matches, or one that also needs its own condition, such as being stale */
union CheckSelection {
  CheckId,
  ConditionalCheck,
}

model ConditionalCheck {
  check: CheckId;
  when: CelExpression;
}

model DispatchRule {
  when: CelExpression;

  @minItems(1)
  @uniqueItems
  then: HandlerId[];
}

model FidelityRule {
  when: CelExpression;
  then: "F0" | "F1" | "F2" | "F3";
}

model RigorRule {
  when: CelExpression;
  then: CelExpressions;
}

@@example(
  RuleList,
  #{
    rules_version: 1,
    kind: "checks_by_iteration",
    rules: #[
      #{
        when: "stage in [\"parts\", \"detail\"] && iteration == \"commit\"",
        then: #[
          "form_check",
          "check_changed_only",
          #{
            check: "sweep.smoke_changed",
            when: "version.has_independent_joint",
          }
        ],
      }
    ],
  }
);
@@example(
  RuleList,
  #{
    rules_version: 1,
    kind: "dispatch",
    rules: #[
      #{ when: "obligation.process == \"fdm\"", then: #["process.fdm"] }
    ],
  }
);
@@example(
  RuleList,
  #{
    rules_version: 1,
    kind: "fidelity",
    rules: #[#{ when: "stage == \"parts\"", then: "F2" }],
  }
);
@@example(
  RuleList,
  #{
    rules_version: 1,
    kind: "rigor",
    rules: #[
      #{
        when: "policy.rigor == \"regulated\"",
        then: #["!record.flow.profile.exists(s, s.turns_check_off)"],
      }
    ],
  }
);
