import "@typespec/json-schema";
import "../common/cel.tsp";

using TypeSpec.JsonSchema;
using Common.Cel;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/flow/rules/")
namespace Flow.Rules;

/** Provisional: one rule-list file, <name>.rules.yaml (ADR-0014), written in the cel-policy format (github.com/cel-expr/cel-policy), restricted to one flat first-match match block with no aggregate, no variables and no nested rule. The first item whose condition holds gives its output; an item without a condition always holds, and the last item must be unconditional, so every list gives a value. A CI step compiles each list with the pinned cel-go policy compiler into one checked expression, and it refuses the last-item rule and the excluded features; the schema checks the rest of the shape. The file doesn't say which list it is: the reference to it in flow.yaml, or in a policy contribution, carries its kind and rules_version. The kind sets the type of every output. checks_by_iteration: a list of check ids, in run order, and [] runs none. dispatch: a handler id, or "unknown" for UNKNOWN coverage, never a pass. fidelity: the form-check fidelity, "F0" to "F3". rigor: a bool, true when the extra requirement under the project's rigor policy holds */
@summary("benchhand rule list (<name>.rules.yaml, restricted cel-policy), provisional")
@id("https://benchhand.github.io/benchhand/contracts/flow/rules.schema.json")
@extension("x-version", "0.1.0")
@extension("x-status", "provisional")
model RuleList {
  /** The policy's name */
  name: RuleName;

  @minLength(1)
  description?: string;

  /** Type aliases for the expressions, as cel-policy imports them */
  @minItems(1)
  imports?: RuleImport[];

  rule: Rule;
}

/** A name such as checks_by_iteration or prototype.dispatch */
@pattern("^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$")
scalar RuleName extends string;

model RuleImport {
  /** A qualified type name, such as benchhand.flow.Obligation */
  @pattern("^[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)*$")
  name: string;
}

/** The one rule of the list: an ordered, first-match list of items */
model Rule {
  id?: RuleName;

  @minLength(1)
  description?: string;

  @minItems(1)
  match: RuleMatch[];
}

/** One item: when condition holds, the list gives output. Without condition, the item always holds */
model RuleMatch {
  condition?: CelExpression;
  output: CelExpression;

  /** Why this item gave its output: a CEL expression that gives a string */
  explanation?: CelExpression;
}

/** A reference to one rule-list file */
model RuleListReference {
  /** The file, relative to the file that refers to it */
  file: RuleListFile;

  /** The version of the rule-list format the file is written in */
  rules_version: 1;
}

@pattern("^([a-z0-9][a-z0-9_-]*/)*[a-z0-9][a-z0-9_-]*\\.rules\\.yaml$")
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
    description: "The process-check handler for an obligation",
    rule: #{
      id: "dispatch",
      match: #[
        #{
          condition: "obligation.family == \"route.consistency\"",
          output: "\"route.consistency\"",
        },
        #{
          output: "\"unknown\"",
          explanation: "\"no handler for \" + obligation.family",
        }
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
        #{ condition: "true", output: "\"F0\"" }
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
          condition: "policy.rigor == \"regulated\"",
          output: "!record.flow.profile.exists(s, s.turns_check_off)",
        },
        #{ output: "true" }
      ],
    },
  }
);
