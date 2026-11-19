---
status: accepted
date: 2026-10-26
---

# Rebaseline part mass targets from F3 references

## Context and Problem Statement

The original `mass_target` values in the part records were placeholders, not a
user-approved mass requirement. The `cad-design` F3 reference geometry has
measured masses of 313 g for LMP-0001 base plate and pivot boss, 153 g for
LMP-0002 lower link, 138 g for LMP-0003 upper link, 58 g for LMP-0004 lamp head,
5.9 g for LMP-0005 M5 x 30 pin, 5.1 g for LMP-0006 M5 x 25 pin, and 4.3 g for
LMP-0007 M5 x 20 pin. The pin masses include the press bands of DR-003.

## Considered Options

* Rebaseline the seven part mass targets to the measured F3 reference masses

## Decision Outcome

Chosen option: "Rebaseline the seven part mass targets to the measured F3 reference masses", because the original mass_target values were placeholders, not a user-approved mass requirement.

### Consequences

These values describe the full-density reference geometry and are not an
independent product-level mass requirement. FDM part mass can differ with
infill and wall settings; replace the targets if the project later sets a
verified mass requirement.

## Pros and Cons of the Options

### Rebaseline the seven part mass targets to the measured F3 reference masses

Rebaseline those seven part mass targets to the measured reference values as
starting targets pending a real mass requirement. Each affected `part.yaml`
references this decision.

## More Information

### Status note

The record's original status line read: accepted; the LMP-0004 target (now 62 g) and the catalogue-part targets are set in DR-004
