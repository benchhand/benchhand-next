---
title: "Tutorial: an assembly with a mechanism"
description: A worked example of an assembly with moving joints.
sidebar:
  order: 3
---

This tutorial builds a small assembly with one joint that moves: a printed lid that swings open on a hinge pin, on a base that mounts to equipment the customer already has.
It follows on from [Tutorial: a bracket](/guides/tutorials/bracket/), which covers the stages each part goes through.
An assembly adds parts of three kinds, joints, assembly steps, joint evidence and motion checks.

## What you build

| Part | Kind | Role |
|---|---|---|
| Base | made, printed | `product` |
| Lid | made, printed | `product` |
| Hinge pin | bought, a standard dowel pin | `product` |
| Heat-set inserts and screws | bought | `product` |
| The customer's enclosure | existing | `context` |

At the end, the record holds the assembly in [`hw/assembly.yaml`](/reference/contracts/record/assembly/): the occurrences of each part, the hinge joint, and the numbered steps that put it together.

## Record what already exists

Each part's record says who provides it, in `make_buy`:

- **`make`**: you make it, such as the printed base and lid.
- **`buy`**: you buy it, such as the pin, the inserts and the screws. Each is a [standard part](/concepts/manufacturing/selection/#standard-parts), identified by its designation.
- **`existing`**: it is already there, such as the customer's enclosure.

An existing part has no supplier and no order code.
Instead, it needs each dimension the design depends on as a range, with its basis: measured, from a standard, declared by you, or assumed, and the sources of each.
Ask the agent to record the enclosure's mounting face this way, from your measurements.

For an existing part, benchhand records the purchase, route, process, form and manufacture obligations as `not_applicable`, with the part's role as the reason.
Each one stays in the record with that reason.
The obligations that touch the rest of the design stay: its interfaces, clearances, sweeps and access.
A part with nothing to freeze, such as an enclosure with no datasheet, is an explicit `not_applicable` with its reason, and its gate can still pass.

## Set the roles

Each occurrence of a part has a role, which sets what the exports do with it:

- **`product`** is delivered. This is the default for a made or bought part.
- **`context`** is there to design against, and isn't delivered. This is the default for an existing part.
- **`tooling`** helps build the product, such as a jig, and isn't delivered.

An occurrence can override its part's default, such as a bought jig used as `tooling` in one assembly.

Each version then exports two scenes:

- `product.step` and `product.glb`, with the `product` occurrences only. This is what a release delivers.
- `scene.step` and `scene.glb`, with every occurrence. The checks, the motion and the sweeps read this one.

The release refuses a product export that holds a `context` or `tooling` part.

## Describe the interfaces and the joint

In LAYOUT, the agent records each interface between parts in [`hw/interfaces.yaml`](/reference/contracts/record/interfaces/): where the base meets the enclosure, the pin's fit in the base, and the inserts' holes.
An interface carries the limits of its fit, insert or ring.
For a heat-set insert, that is the hole diameter, its deviation and the minimum depth.

The hinge is a revolute joint between the base and the lid:

```yaml
joints:
  - id: J-001
    type: revolute
    parent: HNG-0001
    child: HNG-0002
    axis: [1, 0, 0]
    origin: [0, 40, 25]
    min: 0
    max: 110
    nominal: 0
    torque: none
```

A joint is `revolute`, `prismatic` or `fixed`, with its axis, origin and range.
From PARTS on, every revolute joint says whether it carries drive torque.
The lid is moved by hand, so its joint's `torque` is `none`.
A cylindrical joint, which slides and turns, is expanded into a slide and a rotation when the record loads.

## Write the assembly steps

In DETAIL, the agent writes the steps that put the assembly together.
Each step has a kind:

| Kinds | What they do |
|---|---|
| `press_fit`, `heat_set`, `retaining_ring` | Join a part with the fit, insert or ring of an interface. |
| `insert`, `fasten`, `join` | Insert, screw or join a part. |
| `place` | Install a part without a joint. |
| `close`, `adjust`, `inspect`, `disassemble` | Close a part over others, adjust, inspect or take apart. |
| `bench`, `hold` | Open a sub-build on the bench; wait in a fixture, such as for a cure. |

A joining step names the part, what it goes `into`, the `direction` it moves, and the `acceptance` that says when it is done, such as `flush`, `seated` or `torqued`.
`predecessors` names the steps that must come first, and `tool_access` the tools that must reach.
Any step can carry `instructions`, a list of sentences for the build guide and the assembly sheets.

For the hinge, the lid is placed on the base, and the pin that is pressed in next holds it:

```yaml
operations:
  - id: heat_set_inserts
    kind: heat_set
    part: HNG-0004
    into: HNG-0001
    interface: IF-002
    direction: [0, 0, -1]
    acceptance: { kind: flush, features: [top_end, boss_top_face] }
  - id: place_lid
    kind: place
    part: HNG-0002
    into: HNG-0001
    retained_by: [press_pin]
  - id: press_pin
    kind: press_fit
    part: HNG-0003
    into: HNG-0001
    interface: IF-001
    direction: [1, 0, 0]
    acceptance: { kind: seated, features: [pin_end, knuckle_face] }
    predecessors: [place_lid]
```

A `place` step installs a part, and its order, access and interference are checked as for any step.
The retention and edge-distance obligations belong to the joint that holds the part.
`retained_by` names the later joining steps that hold the placed part, or gives an open fact with its reason, and a delivered part must have it.
The retaining joint keeps its full evidence rules, and its evidence covers the parts it holds.
If the pin's fit changes, the lid's evidence goes stale too.

The enclosure is present from the start.
An existing part can be the `part` of a `place` or `disassemble` step only, and it is never the base of a build.

## Prove the joints

Some joint evidence can only come from a physical test, such as an insert's pull-out or a screw's torque.
benchhand proposes test coupons from the verification rows that need one, and adds them to the calibration print job, so they come from the same printer, material and settings as the parts.

When you test a coupon, record:

- the method and the instrument, such as a scale or a torque screwdriver;
- the measured values and their uncertainty;
- the conditions: temperature, wet or dry, and the conditioning time;
- the print job and the material lot.

A result passes only the conditions it was tested under.
If the lid must work at -10 °C wet and at +40 °C, each case needs a coupon conditioned to it.
A room-temperature result leaves those cases provisional, and the gate packet says so.
A result you measure yourself has the source `user_measured`, with the uncertainty of your instrument, and the margin check uses that uncertainty.

## Check the motion

`motion.pose` poses the lid at a joint value, and `motion.render` renders the motion for you to watch.
The collision provider checks the mechanism in the scene, enclosure included:

- **Interference and clearance**, through its `check` hook.
- **The motion sweep**, through the joint's range, through its `sweep` hook.

An overlap smaller than the measurement tolerance is a finding that doesn't block, and isn't counted as interference.
Where an existing part's dimension is a range, the clearance and sweep checks run at both ends.

The full sweep runs at each of the three-step gates from the LAYOUT freeze to ANALYSIS, between sampled poses.
Each of those human gates can approve only when the sweep leaves no unproved interval between samples, or a decision on the same version accepts the ones it leaves.
At the gate you can ask for a finer sweep: the full check runs again on the same version, and the gate comes back to you if it passes.

## Release

The release delivers `product.step` and the documentation set.
The assembly drawing has one sheet for each step, and its parts list groups the parts by make, buy and existing.
The enclosure appears in phantom lines, and the BOM and the build guide list it as customer-furnished equipment, with the ranges it must meet.
[Tutorial: a drawing](/guides/tutorials/drawing/) covers the drawings.
