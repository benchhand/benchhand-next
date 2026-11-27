---
title: Evidence
description: How checks leave evidence in the record.
sidebar:
  order: 2
---

## What evidence is

Before any check runs, benchhand works out from the record which checks the design needs.
Each one is an **obligation**, with:

- its check family;
- the subject it is about: a part, an interface, an assembly operation or the product;
- its evidence level;
- the earliest stage at which it is due;
- its basis, such as the route, interface or requirement it derives from.

Evidence is what settles an obligation.
It comes from three sources only:

- **the record itself**, for facts the record states;
- **the sealed check bundles** of the version, under `hw/checks/<V>/<S>/`, one for each check producer;
- **the accepted evidence ledger**, [`hw/manufacturing/evidence.yaml`](/reference/contracts/record/manufacturing-evidence/).

A check producer writes its bundle for one version.
Its [`result.json`](/reference/contracts/record/manufacturing-check-result/) lists the obligations it was asked to cover, one outcome for each, its findings, and the fingerprints of the inputs it read.
A producer can't shrink its scope by leaving an obligation out: an obligation without an outcome makes the bundle incomplete.

A ledger entry records evidence that no check bundle holds, such as a physical test.
It names its method, the criterion and its source, and the configuration it applies to, and it cites its artifacts or a sealed bundle.
A physically validated entry also records the specimen, the protocol, the instrument and its calibration, the results, the date, who approved it, and what the result covers.

## Evidence levels

Evidence has five levels, and they are independent facets, not a ladder:

| Level | What it shows |
|---|---|
| `cad_valid` | The geometry is valid and reads back. |
| `geometrically_manufacturable` | The geometry can be made with the chosen process. |
| `process_planned` | The route and its operations are planned. |
| `simulation_supported` | An analysis supports the design. |
| `physically_validated` | A physical test supports the design. |

A requirement or a part can hold evidence at several levels at once, and a pass at one level says nothing about another.

## Evidence assessment

benchhand assesses the evidence of one built version at a time.
The [evidence assessment](/reference/contracts/record/evidence-assessment/) gives:

- **a status for every obligation**, with the sources that decided it and the reasons;
- **facets**: for each requirement, part, interface, assembly operation and the product, the worst status of each evidence level over its obligations, or `not_required` where none applies;
- **the findings** about the evidence, and the critical findings of the checks that no disposition settles;
- **whether it is complete**: a partial or refused check bundle makes it incomplete;
- **the acceptance**: the inventory of every file the evidence relies on, with its SHA-256, and the digest of that inventory, `evidence_sha256`, which the freeze records. When the inventory can't be formed, for example because a file is missing, the acceptance is refused with the reason.

An obligation's status is one of these:

| Status | Meaning |
|---|---|
| `pass` | The evidence meets the criterion. |
| `fail` | The evidence doesn't meet the criterion. |
| `waived` | An approved, scoped waiver covers it. It stays waived and never becomes a pass. |
| `not_applicable` | The obligation doesn't apply, and the record says why. |
| `not_assessed` | The check didn't assess it: its calibration is off, or no capability profile exists for it. |
| `stale` | The evidence was for inputs that have changed since. |
| `planned` | Evidence is planned but doesn't exist yet. |
| `unknown` | Nothing covers it, for example because no provider implements the check. |

`unknown`, `planned` and an untested obligation never count as a pass.
`stale` evidence counts as nothing.

## Staleness

Evidence records a fingerprint of each input it relied on, such as the material, the process, the geometry, the interface or the load.
When one of those fingerprints changes, the evidence is stale until an impact assessment carries it forward.

A check outcome is stale when its inputs changed after the version was built.
When benchhand can't compare the built record with the current one, no pass, fail or not-applicable outcome of a check counts, and a finding says why.

## Obligations that don't apply

Some obligations don't apply to a part, and the record says so instead of skipping them.
They are `not_applicable`, with the reason:

- **Existing parts**, the customer's equipment that the product fits to, are never ordered or made, so they have no purchase, route, process, form or manufacture obligations. Their interface, clearance, sweep and access obligations stay.
- **Placed parts** make no joint of their own, so they get no retention or edge-distance obligation.
- **A part with nothing to freeze**, such as a customer envelope without a datasheet, has its frozen specification recorded as `not_applicable` with the reason, and its gate can still pass. What is known about the part, measured or stated by the customer, is still recorded.

## Assembly steps and joint evidence

Each step of an assembly in [`hw/assembly.yaml`](/reference/contracts/record/assembly/) has one of 13 kinds: `press_fit`, `heat_set`, `retaining_ring`, `insert`, `fasten`, `join`, `close`, `adjust`, `inspect`, `disassemble`, `place`, `bench` and `hold`.

- **`place`** installs a part, or a sub-build, without a joint: a sleeve, a ring, washers, a collar held by a pinch screw, a harness held by ties. Its order, access and interference are checked as for any step.
- **`retained_by`** names what holds a placed part: one or more later joining steps in the same build, or an open fact with its reason. A placed part that is delivered, with the role `product`, must have it.
- **The retaining joint** keeps its full evidence rules, and its evidence covers the parts it holds. When that joint changes, the evidence of the placed parts goes stale too.
- **`bench`** opens a sub-build and names its base, and the steps of that unit carry its `sub_build` key.
- **`hold`** records a wait in a fixture: its duration, the fixture, the orientation and an optional cure, with figures from a datasheet.

Any step may carry `instructions`, a list of text that only the build guide and the assembly sheets read.
Existing equipment may be the `part` of a `place` or a `disassemble` step only; it is present from the start and is never a base.

## Test coupons

Some joint evidence can only come from a physical test, such as an insert's pull-out, a screw's torque, or the push-out of a bonded magnet, a snap or a retaining ring.

- benchhand proposes test coupons from the verification rows that need a physical test, and adds them to the calibration print job. They come from the same printer, material and settings as the parts.
- A result records the method and the instrument, the measured values and their uncertainty, the test conditions (temperature, wet or dry, conditioning time), and the print job and material lot.
- A result passes only the conditions it was tested under. A requirement at -10 °C wet and at +40 °C needs a coupon conditioned to each case, and a room-temperature result leaves those cases provisional, as the gate packet says.
- A result you measure yourself has the source kind `user_measured`, with the uncertainty of your instrument. A kitchen scale is coarse, and the margin check uses its uncertainty.
