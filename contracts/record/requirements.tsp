import "@typespec/json-schema";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/record/requirements/")
namespace Records.Requirements;

/** Requirements, preferences, assumptions and open questions, kept apart: a mandatory requirement is never downgraded into a preference or an assumption to pass, and an unknown with a filled-in reason is still unknown. Record version 2 carries all four lists; preferences, assumptions and open_questions may be empty. */
@summary("benchhand requirements record (hw/requirements.yaml)")
@id("https://benchhand.github.io/benchhand/contracts/record/requirements.schema.json")
@extension("x-version", "1.0.0")
model Requirements {
  /** What ranks feasible options; a preference never compensates a mandatory failure */
  preferences?: {
    id: Common.preference_id;
    text: Common.text;
    source: Common.source;

    @minValueExclusive(0)
    @maxValue(1000)
    @extension("x-plausible", #{ max: 100 })
    weight: float64;

    criterion?: Common.criterion;

    @minItems(1)
    subjects?: Common.subject[];
  }[];

  /** Bounded statements taken as true for now, each with its owner and the obligation that would validate it */
  assumptions?: RequirementsAssumptionsItem[];

  /** Questions still to answer; material_to_choice or safety_relevant open questions block a final material/process recommendation */
  open_questions?: RequirementsOpenQuestionsItem[];

  @minItems(1)
  requirements: {
    id: Common.requirement_id;

    @minLength(1)
    text: string;

    @minLength(1)
    rationale: string;

    @minLength(1)
    source: string;

    priority: RequirementsRequirementsItemPriority;
    verification: {
      method: RequirementsRequirementsItemVerificationMethod;

      @minLength(1)
      criteria: string;

      /** The flow step that verifies it, so validation can flag a profile that turns that step off (flow.conflict): fea for a strength or stiffness requirement, physical for a trial or inspection outside CAD */
      step?:
        | "interference"
        | "form"
        | "visibility"
        | "access"
        | "process"
        | "motion"
        | "stack_up"
        | "fea"
        | "drawing"
        | "critique"
        | "physical";
    };

    @minItems(1)
    subjects?: Common.subject[];

    /** Structured acceptance criteria; the prose criteria stay, and a final selection evaluates these, never an automatic reading of prose */
    @minItems(1)
    acceptance?: Common.criterion[];

    /** the service conditions the requirement holds under */
    conditions?: Common.text;

    risk?: {
      severity: Common.consequence_severity;
      consequence: Common.text;
    };

    /** The evidence levels a pass needs */
    @minItems(1)
    @uniqueItems
    evidence_required?: Common.evidence_level[];

    waiver_policy?: "forbidden" | "approval_required";

    /** Show-the-motion checks: from view, rendering only the window and target parts at the nominal pose, each target's own visible share of its projected area must reach min_visible_fraction (default 0.5); the check fails when any target falls short. Only transparency: transparent window parts are see-through */
    @minItems(1)
    visibility?: {
      /** A render view: iso, front, side, or a dir-X-Y-Z direction in assembly coordinates */
      @pattern("^(?:iso|front|side|dir-[pm](?:0|[1-9][0-9]{0,5})(?:d[0-9]{0,5}[1-9])?-[pm](?:0|[1-9][0-9]{0,5})(?:d[0-9]{0,5}[1-9])?-[pm](?:0|[1-9][0-9]{0,5})(?:d[0-9]{0,5}[1-9])?)$")
      @extension(
        "not",
        #{
          description: "a direction needs a non-zero component",
          pattern: "^dir-[pm]0-[pm]0-[pm]0$",
        }
      )
      view: string;

      @minItems(1)
      @uniqueItems
      window: Assembly.part_ref[];

      @minItems(1)
      @uniqueItems
      targets: Assembly.part_ref[];

      @minValueExclusive(0)
      @maxValue(1)
      min_visible_fraction?: float64 = 0.5;
    }[];
  }[];
}

@extension("x-inline", true)
@extension(
  "if",
  #{ properties: #{ status: #{ `enum`: #["validated", "invalidated"] } } }
)
@extension("then", #{ required: #["decision"] })
model RequirementsAssumptionsItem {
  id: Common.assumption_id;
  text: Common.text;
  origin: Common.text;
  reason: Common.text;

  @oneOf
  bounds?: Common.quantity | Common.text;

  requirements?: Common.requirement_ids;
  owner: Common.text;

  /** the check, test or answer that would confirm or refute it */
  validation: Common.text;

  status: "open" | "validated" | "invalidated";
  decision?: Common.decision;
}

@extension("x-inline", true)
@extension("if", #{ properties: #{ status: #{ `const`: "resolved" } } })
@extension("then", #{ required: #["resolution"] })
@extension("else", #{ not: #{ required: #["resolution"] } })
model RequirementsOpenQuestionsItem {
  id: Common.question_id;
  question: Common.text;

  @minItems(1)
  subjects?: Common.subject[];

  owner: Common.text;
  material_to_choice: boolean;
  safety_relevant: boolean;
  status: "open" | "resolved";

  @extension(
    "anyOf",
    #[#{ required: #["source"] }, #{ required: #["decision"] }]
  )
  resolution?: {
    answer: Common.text;
    source?: Common.source;
    decision?: Common.decision;
  };
}

@extension("x-inline", true)
enum RequirementsRequirementsItemPriority {
  must,
  should,
  could,
  MUST,
  SHOULD,
  COULD,
}

@extension("x-inline", true)
enum RequirementsRequirementsItemVerificationMethod {
  I,
  A,
  D,
  T,
}

@@example(
  Requirements,
  #{
    requirements: #[
      #{
        id: "REQ-001",
        text: "Replace with a measurable product requirement.",
        rationale: "Explain why this requirement matters.",
        source: "Project brief or other source",
        priority: RequirementsRequirementsItemPriority.must,
        verification: #{
          method: RequirementsRequirementsItemVerificationMethod.T,
          criteria: "Describe the acceptance criteria for verification.",
        },
      }
    ],
    preferences: #[],
    assumptions: #[],
    open_questions: #[
      #{
        id: "Q-001",
        question: "Which service class applies: appearance or concept model, fit or assembly prototype, functional demonstration with limited loads and supervised operation, working prototype, production or end-use product, or safety-critical, regulated or high-consequence application?",
        subjects: #[#{ product: true }],
        owner: "lead",
        material_to_choice: true,
        safety_relevant: true,
        status: "open",
      },
      #{
        id: "Q-002",
        question: "What must the product do, and who uses it?",
        subjects: #[#{ product: true }],
        owner: "lead",
        material_to_choice: true,
        safety_relevant: false,
        status: "open",
      },
      #{
        id: "Q-003",
        question: "What operating temperature range and heat sources apply?",
        subjects: #[#{ product: true }],
        owner: "lead",
        material_to_choice: true,
        safety_relevant: true,
        status: "open",
      },
      #{
        id: "Q-004",
        question: "What moisture, chemical, UV and corrosion exposure applies?",
        subjects: #[#{ product: true }],
        owner: "lead",
        material_to_choice: true,
        safety_relevant: false,
        status: "open",
      },
      #{
        id: "Q-005",
        question: "Which loads act on it: magnitude, direction, static or sustained, cyclic, impact and vibration?",
        subjects: #[#{ product: true }],
        owner: "lead",
        material_to_choice: true,
        safety_relevant: true,
        status: "open",
      },
      #{
        id: "Q-006",
        question: "Which motions occur: speed, range, duty cycle, friction, wear and expected service life?",
        subjects: #[#{ product: true }],
        owner: "lead",
        material_to_choice: true,
        safety_relevant: false,
        status: "open",
      },
      #{
        id: "Q-007",
        question: "What accuracy, repeatability, surface finish and dimensional stability are required?",
        subjects: #[#{ product: true }],
        owner: "lead",
        material_to_choice: true,
        safety_relevant: false,
        status: "open",
      },
      #{
        id: "Q-008",
        question: "What are the consequences of failure, the forbidden outcomes, the applicable standards or safety requirements, the supervision and the approving authority?",
        subjects: #[#{ product: true }],
        owner: "lead",
        material_to_choice: true,
        safety_relevant: true,
        status: "open",
      },
      #{
        id: "Q-009",
        question: "What quantity, budget, lead time, maintenance and repair needs apply?",
        subjects: #[#{ product: true }],
        owner: "lead",
        material_to_choice: true,
        safety_relevant: false,
        status: "open",
      },
      #{
        id: "Q-010",
        question: "Which equipment and operators are available, and is outsourcing acceptable?",
        subjects: #[#{ product: true }],
        owner: "lead",
        material_to_choice: true,
        safety_relevant: false,
        status: "open",
      },
      #{
        id: "Q-011",
        question: "What may a release claim: its purpose, operating limits, exclusions and the evidence each requirement needs?",
        subjects: #[#{ product: true }],
        owner: "lead",
        material_to_choice: false,
        safety_relevant: true,
        status: "open",
      },
      #{
        id: "Q-012",
        question: "How is the assembly installed: which operations, in which order, with which tools, access and closure?",
        subjects: #[#{ product: true }],
        owner: "lead",
        material_to_choice: true,
        safety_relevant: true,
        status: "open",
      },
      #{
        id: "Q-013",
        question: "Which general tolerance must the drawings state for dimensions without their own tolerance: a standard tolerance class or a linear value in mm?",
        subjects: #[#{ product: true }],
        owner: "lead",
        material_to_choice: true,
        safety_relevant: false,
        status: "open",
      }
    ],
  }
);
