import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/decision/")
namespace Records.Decision;

/** The YAML front matter between the two --- lines at the top of a decision record; the Markdown body after it is kept verbatim and has no required sections. kind gate records a flow gate state (approved, provisional or void); kind design records a design decision (proposed, accepted, rejected or superseded). A decision cited as the approval of a freeze, an engineering change or the flow profile must be a gate decision with status approved or a design decision with status accepted */
@summary("benchhand decision record front matter (hw/decisions/DR-###-<slug>.md)")
@id("https://benchhand.github.io/benchhand/contracts/record/decision.schema.json")
@extension("x-version", "1.0.0")
@extension(
  "oneOf",
  #[#{ $ref: "#/$defs/gate_decision" }, #{ $ref: "#/$defs/design_decision" }]
)
model Decision {
  id: Common.decision;
  kind: "gate" | "design";
  ...Record<unknown>;
}

/** One line of text */
@pattern("^[^\\n]*[^\\t\\n\\v\\f\\r \\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000\\ufeff][^\\n]*$")
scalar title extends string;

@minItems(1)
@uniqueItems
model decisions is Common.decision[];

@minItems(1)
model people is title[];

/** Who approved a gate and through which channel: app (an MCP App), form (a form elicitation), chat (the user's words in the conversation) or auto (the policy mode auto, without a human). Every channel but auto names who approved and quotes their words */
@extension("if", #{ properties: #{ channel: #{ `const`: "auto" } } })
@extension("then", #{ not: #{ required: #["quote"] } })
@extension("else", #{ required: #["by", "quote"] })
model approval {
  channel: "app" | "form" | "chat" | "auto";
  by?: Common.text;
  quote?: Common.text;
}

/** A flow gate state. provisional: the fast checks passed and the flow may build on it until the full check and the human gate; approved: the gate is passed; void: a provisional or approved gate is withdrawn. An approved gate supersedes its provisional one, and a void supersedes what it withdraws. An approved gate carries its approval unless the policy mode of its gate is auto, which validation checks against hw/policy.yaml */
@extension("if", #{ properties: #{ status: #{ `const`: "approved" } } })
@extension("else", #{ not: #{ required: #["approval"] } })
model gate_decision {
  id: Common.decision;
  kind: "gate";
  title: title;
  date: Common.date;
  status: "approved" | "provisional" | "void";
  gate: Common.gate_id;

  /** The flow stage the gate belongs to */
  stage: Common.stage;

  /** The built version the gate decided on */
  version?: Common.version;

  /** The result files the gate decided on */
  @minItems(1)
  @uniqueItems
  evidence?: Common.project_path[];

  supersedes?: decisions;
  approval?: approval;
}

/** A design decision. superseded names the decisions that replace it in superseded_by; no other status has superseded_by */
@extension("if", #{ properties: #{ status: #{ `const`: "superseded" } } })
@extension("then", #{ required: #["superseded_by"] })
@extension("else", #{ not: #{ required: #["superseded_by"] } })
model design_decision {
  id: Common.decision;
  kind: "design";
  title: title;
  date: Common.date;
  status: "proposed" | "accepted" | "rejected" | "superseded";
  superseded_by?: decisions;
  decision_makers?: people;
  consulted?: people;
  informed?: people;
}

@@example(
  Decision,
  #{
    id: "DR-012",
    kind: "gate",
    title: "Provisional layout freeze of v3",
    date: "2026-11-22",
    status: "provisional",
    gate: "layout_freeze",
    stage: "layout",
    version: "v3",
    evidence: #["hw/checks/v3/assembly/result.json"],
  }
);
@@example(
  Decision,
  #{
    id: "DR-013",
    kind: "gate",
    title: "Layout freeze of v3",
    date: "2026-11-23",
    status: "approved",
    gate: "layout_freeze",
    stage: "layout",
    version: "v3",
    supersedes: #["DR-012"],
    approval: #{
      channel: "chat",
      by: "the user",
      quote: "Yes, freeze the layout.",
    },
  }
);
@@example(
  Decision,
  #{
    id: "DR-003",
    kind: "design",
    title: "Press-fit pivot pins",
    date: "2026-10-26",
    status: "superseded",
    superseded_by: #["DR-004"],
  }
);
@@example(
  Decision,
  #{
    id: "DR-005",
    kind: "design",
    title: "Print the PETG parts in-house on a Bambu Lab H2D",
    date: "2026-11-18",
    status: "accepted",
    decision_makers: #["the user"],
  }
);
