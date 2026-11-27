---
title: Guidelines and checks
description: Design guidelines, the process checks that apply them, and their findings.
sidebar:
  order: 2
---

## Guidelines

A guideline set is one file of published design-for-manufacturing guidance for a process, under `hw/manufacturing/guidelines/`.
The [guideline contract](/reference/contracts/record/manufacturing-guideline/) lists its fields.

A set has an id, a revision, a scope and a list of limits:

- **The scope** says what the set applies to: the process, and optionally the material family, the filler, the Shore hardness, the nozzle diameters and the nozzle material. Every selector present must match, and a set with more selectors is more specific.
- **A limit** bounds one characteristic, such as the minimum wall, the minimum hole, the bridge span or the overhang angle. It gives a value or an interval, or a factor of the nozzle diameter or line width with a floor, and it can apply only to one orientation or feature.
- **Citations.** Every limit cites its sources. When the sources disagree, the limit is marked `disputed` and the stricter value applies.

A set can extend parent sets, and an abstract set is reached only through `extends` or a capability profile's pin.

Guidelines layer from generic to specific.
A more specific set may only tighten a limit; a limit that relaxes a less specific one needs `relaxes`, with a reason and a citation.
A machine's own sets are reached only through the guideline pins of its [capability profile](/concepts/manufacturing/capabilities/), and they rank above every set that a scope selects.
A calibration ranks above them all.

A guideline is never a calibration.
It is published guidance, and a criterion resolved from it cites the guideline set itself, with its id, revision and SHA-256.
A value that a source doesn't publish is left out, never filled in with a default.
Layer height, shrinkage and Z strength are not guideline limits: they belong to the capability profile and the material profile.

## How checks are dispatched

Before any check runs, benchhand lists the obligations that the record implies for each part and its route.
The process-check provider takes the obligations it owns.
For each one, the dispatch [rule list](/concepts/policy/rule-lists/) picks a handler from the process, the operation and the material.
A handler is named by the obligation family it judges, such as `process.fdm.orientation`.

When no rule matches, the dispatch list gives `"unknown"`, and the obligation's coverage is UNKNOWN.
A gap in coverage is never a pass.
The same holds when no provider implements a needed hook, and when a route uses a process that benchhand has no check contract for.

## Findings and evidence

Each check producer writes a sealed bundle for one version, under `hw/checks/<V>/<S>/`, with its [`result.json`](/reference/contracts/record/manufacturing-check-result/):

- the obligations it was asked to cover;
- one outcome per obligation: `pass`, `fail`, `unknown`, `not_applicable` or `not_assessed`;
- its findings;
- the SHA-256 of each input it read, such as the part record, the material and capability profiles and the geometry;
- whether it covered every obligation.

The bundle's result is `fail` if any outcome fails, else `unknown` if any outcome is unknown or the bundle is incomplete, else `not_assessed` if any outcome is, else `pass`.

A finding is immutable.
It states its subject and severity, the measured value with its units or why it is unknown, the criterion and its source, the method and its evidence, the uncertainty, and the functional consequence.
It can add a remedy with alternatives and their tradeoffs, and the recheck it needs.

The lead agent settles findings in [`hw/manufacturing/findings.yaml`](/reference/contracts/record/manufacturing-findings/).
A disposition names the finding and the exact bundle it is in, and gives a status: `open`, `resolved`, `accepted_waiver` or `declined`, with a reason.
The finding in the bundle is never copied or edited.
Declining or waiving a finding never turns a mandatory `fail` or `unknown` into a pass: the original outcome is assessed together with its disposition.

A waiver is explicit, scoped, justified and approved.
It names its exact subject, criterion and operating envelope, when it ends, the reason, the consequence, and the authority and decision that approved it.
No waiver overrides a governing safety or regulatory requirement, or a forbidden geometry failure.

The check bundles of a version are one of the three sources of its [evidence](/concepts/record/evidence/).
A critical finding whose outcome is `fail` or `unknown`, and that no disposition settles, is listed in the version's evidence assessment.
