# ADR-0022: A hazards and risk-assessment contract

Status: accepted 2026-11-27. Source: the owner's decisions D-35 and D-40 on the CAD-libraries study ([decision record](../design/cad-libraries-2026-11-27.md)). It adds to section 12a of [the plan](../design-plan.md).

## Context

The product documents have safety sections: warnings in the assembly guide, and the hazards and maintenance parts of the user manual. No record contract holds hazards, so every safety cell is UNKNOWN. A product's service class (`common.schema.json#/$defs/service_class`) can already be `safety_critical`, but nothing reads it at release.

## Decision

1. Hazards and their risk assessment get their own record contract, beside the product, part and requirement contracts. Its fields are designed when it is built, after Phase 4, in `contracts/` (ADR-0017).
2. A release blocks on a safety UNKNOWN only where the service class is `safety_critical`. For every other service class, a safety UNKNOWN is reported in the gate packet and the release notes, and it doesn't block.
3. The documents ship no ISO 7010 or ISO 7000 symbols by default. A hazard prints as a signal-word panel with text. A project may supply its own symbol files.

## Consequences

- The safety sections stay UNKNOWN until the contract exists. That is honest, and it blocks nothing except a `safety_critical` release.
- The service class sits on the product in the record contract at 2026-11-27. Whether a part carries its own is part of the contract's design.
- Symbol licences need tracking only when a project adds its own symbols.
