---
status: accepted
date: 2026-10-26
---

# Three-link revolute lamp-arm layout

## Context and Problem Statement

The first lamp-arm layout needs to hold a light head and let a user aim it with
three revolute joints while keeping the base, links, and head manufacturable.

## Considered Options

* Three-link revolute layout in a printed PETG base and head with machined 6061-T6 links

## Decision Outcome

Chosen option: "Three-link revolute layout in a printed PETG base and head with machined 6061-T6 links", because it lets a user aim a light head with three revolute joints while keeping the base, links and head manufacturable.

### Consequences

This is an L1 layout for refinement, not a detailed or verified released design.
Fit, fastener retention, load limits, analysis, and manufacturing tolerances
must be finalized and verified before release.

## Pros and Cons of the Options

### Three-link revolute layout in a printed PETG base and head with machined 6061-T6 links

Group the base plate and pivot boss into `base_sub`; group the lower and upper
links, lamp head, and their M5 purchased shoulder pins into `arm_sub`. The
part-level joints connect the base plate to lower link, lower link to upper
link, and upper link to lamp head. Use a printed PETG base/head and machined
6061-T6 links for the project starting layout.
