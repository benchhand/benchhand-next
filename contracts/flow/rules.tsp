import "@typespec/json-schema";
import "../common/cel.tsp";

using TypeSpec.JsonSchema;
using Common.Cel;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/flow/rules/")
namespace Flow.Rules;

/** Provisional: one rule-list file, flow/<name>.celpolicy, in the restricted cel-policy profile of ADR-0020 (github.com/cel-expr/cel-policy): a name and one rule with one first-match match block. The profile has no variables, no aggregate, no nested rule and no other cel-policy field, explanation and imports included. The first choice whose condition holds gives its output. Every choice but the last has a condition, and the last has none, so every list gives a value. The pinned cel-go tool compiles each list before load into one checked expression of the rules bundle. It refuses a conditional last choice, an excluded feature and a result type other than its kind's; the schema checks the rest of the shape. The file doesn't say which list it is: the reference to it in flow.yaml, or in a policy contribution, carries its kind and rules_version. The kind sets the type of every output. checks_by_iteration: list(string), the check ids in run order, with a conditional check concatenated as a CEL ternary; [] is its no-match value. dispatch: string, a handler id, or its no-match value "unknown", which the host records as UNKNOWN coverage, never a pass. fidelity: string, the form-check fidelity "F0" to "F3", or its no-match value "none", which only a contributed list gives. rigor: list(string), the messages of the requirements the record doesn't meet under the project's rigor policy, ending in []. The slot type is string, so the compiler accepts any string a fidelity or dispatch output gives, computed ones included. The Phase 2 evaluator checks the kind's result against its domain: a fidelity outside F0 to F3, and a dispatch handler id that no handler has, is out of the domain, and the evaluator records it as UNKNOWN with a finding that names the value, never as a pass. policy/contribution.schema.json says how the lists of one kind combine */
@summary("benchhand rule list (flow/<name>.celpolicy, restricted cel-policy), provisional")
@id("https://benchhand.github.io/benchhand/contracts/flow/rules.schema.json")
@extension("x-version", "0.1.0")
@extension("x-status", "provisional")
model RuleList {
  /** The policy's name */
  name: RuleName;

  rule: Rule;
}

/** A name such as checks_by_iteration or prototype.dispatch */
@pattern("^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$")
scalar RuleName extends string;

/** The one rule of the list: an ordered, first-match list of choices */
model Rule {
  @minItems(1)
  match: RuleMatch[];
}

/** One choice: when condition holds, the list gives output. A choice without condition always holds */
model RuleMatch {
  condition?: CelExpression;
  output: CelExpression;
}

/** A reference to one rule-list file */
model RuleListReference {
  /** The file, relative to the file that refers to it */
  file: RuleListFile;

  /** The version of the rule-list format the file is written in */
  rules_version: 1;
}

@pattern("^([a-z0-9][a-z0-9_-]*/)*[a-z0-9][a-z0-9_-]*\\.celpolicy$")
scalar RuleListFile extends string;

/** The rule lists, one file of each kind. The key is the list's kind, which sets the type of its outputs */
model FlowRuleLists {
  checks_by_iteration: RuleListReference;
  dispatch: RuleListReference;
  fidelity: RuleListReference;
  rigor: RuleListReference;
}

@@example(
  RuleList,
  #{
    name: "checks_by_iteration",
    rule: #{
      match: #[
        #{
          condition: "stage in [\"parts\", \"detail\"] && iteration == \"commit\"",
          output: "[\"form_check\", \"check_changed_only\"] + (version.has_independent_joint ? [\"sweep.smoke_changed\"] : [])",
        },
        #{ output: "[]" }
      ],
    },
  }
);
@@example(
  RuleList,
  #{
    name: "dispatch",
    rule: #{
      match: #[
        #{
          condition: "obligation.family == \"route.consistency\"",
          output: "\"route.consistency\"",
        },
        #{ output: "\"unknown\"" }
      ],
    },
  }
);
@@example(
  RuleList,
  #{
    name: "fidelity",
    rule: #{
      match: #[
        #{ condition: "stage == \"parts\"", output: "\"F2\"" },
        #{ output: "\"F0\"" }
      ],
    },
  }
);
@@example(
  RuleList,
  #{
    name: "rigor",
    rule: #{
      match: #[
        #{
          condition: "policy.rigor == \"regulated\" && record.flow.profile.exists(s, s.turns_check_off)",
          output: "[\"regulated rigor refuses a flow profile that turns a check off\"]",
        },
        #{ output: "[]" }
      ],
    },
  }
);
