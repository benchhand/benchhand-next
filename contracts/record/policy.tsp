import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/policy/")
namespace Records.Policy;

/** How each flow gate asks for approval (ADR-0003): ask (the default) asks the user through the richest interaction the client offers, chat asks in the conversation, auto approves without a human (for development and tests). Gates guide the process; they are not a security control. Every relaxation from ask cites the decision that records it. rigor is the rigor policy: regulated adds the requirements of flow.yaml's rigor rules. An absent file means every gate asks and the rigor is standard */
@summary("benchhand gate policy (hw/policy.yaml)")
@id("https://benchhand.github.io/benchhand/contracts/record/policy.schema.json")
@extension("x-version", "1.1.0")
@extension(
  "if",
  #{
    required: #["default"],
    properties: #{ default: #{ `enum`: #["chat", "auto"] } },
  }
)
@extension("then", #{ required: #["decision"] })
model Policy {
  policy_version: 1;

  /** The mode of every gate without its own entry */
  default?: mode = "ask";

  /** The decision that records a default other than ask */
  decision?: Common.decision;

  /** Per-gate modes, keyed by the gate id flow.yaml declares */
  @extension("propertyNames", Common.gate_id)
  gates?: Record<gate>;

  /** The rigor policy. An absent rigor is standard */
  rigor?: "standard" | "regulated" = "standard";
}

union mode {
  "ask",
  "chat",
  "auto",
}

@extension("if", #{ properties: #{ mode: #{ `enum`: #["chat", "auto"] } } })
@extension("then", #{ required: #["decision"] })
model gate {
  mode: mode;
  decision?: Common.decision;
}

@@example(Policy, #{ policy_version: 1 });
@@example(
  Policy,
  #{
    policy_version: 1,
    default: "ask",
    gates: #{
      layout_freeze: #{ mode: "chat", decision: "DR-014" },
      parts: #{ mode: "ask" },
    },
  }
);
@@example(Policy, #{ policy_version: 1, default: "auto", decision: "DR-001" });
@@example(Policy, #{ policy_version: 1, rigor: "regulated" });
