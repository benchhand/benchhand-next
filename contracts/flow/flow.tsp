import "@typespec/json-schema";
import "../common/cel.tsp";
import "../record/common.tsp";
import "../record/decision.tsp";

using TypeSpec.JsonSchema;
using Common.Cel;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/flow/flow/")
namespace Flow.Flow;

/** Provisional: the flow definition, flow.yaml (ADR-0014). The stage and gate graph is data, and every condition in it is a CEL expression: the edge guards, the gate requirements and the VOID cascade scope. The rule lists are files of their own (flow/rules.schema.json). A gate of kind single-human advances its edge when the user approves it; a gate of kind provisional+full+human advances its edge at the provisional gate, and its human gate opens after the full check. The schema checks the shape of one file: every stage of the record's stage enum, once, with at least one gate and one edge. The flow loader checks what refers across the file when it loads it: it refuses a duplicate YAML key, two gates with the same id, an edge that names a gate the file doesn't declare, and a CEL expression that doesn't compile or type-check */
@summary("benchhand flow definition (flow.yaml), provisional")
@id("https://benchhand.github.io/benchhand/contracts/flow/flow.schema.json")
@extension("x-version", "0.1.0")
@extension("x-status", "provisional")
model Flow {
  flow_version: 1;

  stages: FlowStages;

  @minItems(1)
  gates: FlowGate[];

  @minItems(1)
  edges: FlowEdge[];

  /** Selects the stages a VOID reopens besides the voided stage, evaluated for each stage after it */
  void_scope: CelExpression;

  /** Provisional (ADR-0019, owned by Phase 2): selects the approved items a change affects, next to void_scope. An affected item whose fingerprint differs from its approval is changed_since_approval */
  @extension("x-status", "provisional")
  reapproval_scope?: CelExpression;
}

/** Every stage of the record's stage enum (record/common.schema.json#/$defs/stage), by its id, each once. The order of the stages is the enum's, and the graph is the edges; the order of the keys means nothing */
model FlowStages {
  ground: FlowStage;
  intent: FlowStage;
  specify: FlowStage;
  concept: FlowStage;
  layout: FlowStage;
  parts: FlowStage;
  detail: FlowStage;
  bom: FlowStage;
  analysis: FlowStage;
  critique: FlowStage;
  reconcile: FlowStage;
  design_freeze: FlowStage;
  release: FlowStage;
}

model FlowStage {
  guides: FlowGuides;
}

/** The guide fragment for each role at this stage, by role: lead is the lead agent, any other key an agent profile such as cad-part-designer. flow.guide returns a role's own fragment, else the lead's */
@extension("propertyNames", #{ pattern: "^[a-z][a-z0-9-]*$" })
model FlowGuides {
  lead: FlowGuideFragment;
  ...Record<FlowGuideFragment>;
}

/** A Markdown file under guides/, relative to flow.yaml, with an optional heading anchor */
@pattern("^guides/[a-z0-9][a-z0-9_-]*(/[a-z0-9][a-z0-9_-]*)*\\.md(#[a-z0-9][a-z0-9-]*)?$")
scalar FlowGuideFragment extends string;

@oneOf
union FlowGate {
  FlowSingleHumanGate,
  FlowStagedGate,
}

/** A gate the user approves in one step. Each requirement must hold */
model FlowSingleHumanGate {
  id: Records.Common.gate_id;

  /** The stage the gate closes */
  stage: Records.Common.stage;

  kind: "single-human";
  requires: {
    human: CelExpressions;
  };
}

/** A gate that approves a built version in three steps: the provisional gate after the fast checks, the full check on the same version, then the human gate. Each step's requirements must hold */
model FlowStagedGate {
  id: Records.Common.gate_id;

  /** The stage the gate closes */
  stage: Records.Common.stage;

  kind: "provisional+full+human";
  requires: {
    provisional: CelExpressions;

    /** When the full check counts as done */
    full: CelExpressions;

    human: CelExpressions;
  };
}

/** A transition between two stages. gate names the gate it passes through; guard must also hold */
model FlowEdge {
  from: Records.Common.stage;
  to: Records.Common.stage;
  gate?: Records.Common.gate_id;
  guard?: CelExpression;
}

/** What the flow engine takes to record a human-gate decision, from the gate card (app) or from the user's reply in chat. status approved passes the gate. status void withdraws the gate's provisional approval because of a change the user named at the human gate, so it needs a human channel (app or chat) and cites that provisional decision; the VOID the interpreter records itself, after a failing full check or a MAJOR light-review finding, doesn't go through this request. provisional cites the provisional decision of a provisional+full+human gate. Every channel but auto names who decided and quotes their words, and a quote has at least one character that isn't whitespace: an empty answer is no answer. form is refused: form elicitation is not used (ADR-0018) */
@extension(
  "allOf",
  #[
    #{
      `if`: #{ properties: #{ channel: #{ `const`: "auto" } } },
      then: #{ not: #{ required: #["quote"] } },
      `else`: #{ required: #["by", "quote"] },
    },
    #{
      `if`: #{ properties: #{ status: #{ `const`: "void" } } },
      then: #{
        required: #["provisional"],
        properties: #{ channel: #{ `enum`: #["app", "chat"] } },
      },
    }
  ]
)
model GateDecisionRequest {
  gate: Records.Common.gate_id;
  status: "approved" | "void";

  /** The built version the decision is on */
  version?: Records.Common.version;

  @extension("not", #{ `const`: "form" })
  channel: Records.Decision.approval_channel;

  by?: Records.Common.text;

  /** The user's words, quoted. At least one character isn't whitespace */
  @pattern("[^\\t\\n\\v\\f\\r \\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff]")
  quote?: Records.Common.text;

  provisional?: Records.Common.decision;
}

/** Provisional (ADR-0019, owned by Phase 2): the items a human-gate approval covers, each with its fingerprint at approval time, computed the way the evidence service fingerprints its inputs. The decision contract refers to it once Phase 2 adds it there */
@extension("x-status", "provisional")
model ApprovalScope {
  @minItems(1)
  @uniqueItems
  items: ApprovedItem[];
}

/** Provisional (ADR-0019): one approved item */
@extension("x-status", "provisional")
model ApprovedItem {
  kind: ApprovedItemKind;

  /** The item's id in the record, such as an interface id or a PN */
  @minLength(1)
  id: string;

  fingerprint: Records.Common.sha256;
}

union ApprovedItemKind {
  "concept",
  "envelope",
  "interface",
  "joint",
  "part",
}

/** Provisional (ADR-0019): an approved item now. approved: its fingerprint is the one recorded at approval; changed_since_approval: it differs, and the next human gate shows the item with a diff and confirms it. The stage stays where it is */
@extension("x-status", "provisional")
model ApprovedItemState {
  kind: ApprovedItemKind;

  @minLength(1)
  id: string;

  /** The decision that approved it */
  decision: Records.Common.decision;

  status: "approved" | "changed_since_approval";

  /** The item's fingerprint now */
  fingerprint: Records.Common.sha256;
}

@@example(
  Flow,
  #{
    flow_version: 1,
    stages: #{
      ground: #{ guides: #{ lead: "guides/ground.md" } },
      intent: #{ guides: #{ lead: "guides/intent.md" } },
      specify: #{ guides: #{ lead: "guides/specify.md" } },
      concept: #{ guides: #{ lead: "guides/concept.md" } },
      layout: #{ guides: #{ lead: "guides/layout.md" } },
      parts: #{
        guides: #{
          lead: "guides/parts.md",
          `cad-part-designer`: "guides/parts.md#part-designer",
        },
      },
      detail: #{ guides: #{ lead: "guides/detail.md" } },
      bom: #{ guides: #{ lead: "guides/bom.md" } },
      analysis: #{ guides: #{ lead: "guides/analysis.md" } },
      critique: #{ guides: #{ lead: "guides/critique.md" } },
      reconcile: #{ guides: #{ lead: "guides/reconcile.md" } },
      design_freeze: #{ guides: #{ lead: "guides/design-freeze.md" } },
      release: #{ guides: #{ lead: "guides/release.md" } },
    },
    gates: #[
      #{
        id: "layout_freeze",
        stage: Records.Common.stage.layout,
        kind: "provisional+full+human",
        requires: #{
          provisional: #["version.fast_checks.all(c, c.status == \"pass\")"],
          full: #["full_check.status == \"pass\""],
          human: #[
            "full_check.status == \"pass\" && prev_human_gate.approved && (policy.mode == \"auto\" || answer.present)",
            "approvals.all(i, i.status != \"changed_since_approval\" || answer.confirms(i))"
          ],
        },
      }
    ],
    edges: #[
      #{
        from: Records.Common.stage.layout,
        to: Records.Common.stage.parts,
        gate: "layout_freeze",
      }
    ],
    void_scope: "stage.index > voided.stage.index && stage.built_on == voided.version",
    reapproval_scope: "change.items.exists(c, c.kind == item.kind && c.id == item.id)",
  }
);
@@example(
  GateDecisionRequest,
  #{
    gate: "layout_freeze",
    status: "approved",
    version: "v3",
    channel: "chat",
    by: "the user",
    quote: "Yes, freeze the layout.",
    provisional: "DR-012",
  }
);
@@example(
  GateDecisionRequest,
  #{ gate: "intent", status: "approved", channel: "auto" }
);
@@example(
  GateDecisionRequest,
  #{
    gate: "layout_freeze",
    status: "void",
    version: "v3",
    channel: "chat",
    by: "the user",
    quote: "The arm needs 20 mm more reach; don't freeze this.",
    provisional: "DR-012",
  }
);
@@example(
  ApprovalScope,
  #{
    items: #[
      #{
        kind: "interface",
        id: "IF-001",
        fingerprint: "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
      },
      #{
        kind: "part",
        id: "LMP-0003",
        fingerprint: "60303ae22b998861bce3b28f33eec1be758a213c86c93c076dbe9f558c11c752",
      }
    ],
  }
);
@@example(
  ApprovedItemState,
  #{
    kind: "interface",
    id: "IF-001",
    decision: "DR-013",
    status: "changed_since_approval",
    fingerprint: "fd61a03af4f77d870fc21e05e7e80678095c92d808cfb3b5c279ee04c74aca13",
  }
);
