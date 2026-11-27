---
title: The preview UI
description: The viewer, concept, gallery, gate card and flow view in your browser.
sidebar:
  order: 2
---

## Open the preview

The benchhand MCP server hosts the preview pages itself, on a loopback HTTP listener in the same process.
The listener takes an ephemeral port, checks the `Host` header, and puts a random token in every path.
It is separate from the MCP connection.

The preview's URLs come back in tool results, and you open them in your browser.
The agent serves a page with `preview.serve(kind, target)`, which returns its URL, and manages the pages with `preview.list` and `preview.stop`.
`preview.serve` hosts the viewer, the concept page, the gallery, the flow view, or a prototype page or rendering that the agent made.

Where the host draws MCP Apps, such as Claude Desktop, an App shows the same page inside the conversation.
The App is a thin shell that embeds the preview page, so both show the same thing.

To browse a project without an agent, run the preview host on its own:

```sh
benchhand serve --project . --open
```

Everything is local: the pages are served from your machine, to your machine.

## The views

| View | What it shows |
|---|---|
| Viewer | The design in 3D. `preview.part` and `preview.assembly` update it with a preview build, and `viewer.show`, `viewer.compare`, `viewer.capture` and `viewer.camera` drive it. |
| Concept page | The concept variants that the agent builds with `concept.add_variant`, `concept.set_primitive` and `concept.snapshot`. |
| Gallery | The project's renders, together on one page. |
| Gate card | The gate packet: what you are approving, the renders and the flow view, with **Approve** and **Request changes**. |
| Flow view | The stages and gates of `flow.yaml`, with the project's live state. |

The flow view and the gate card draw the flow with React Flow.
They show the current stage, the open gates, the provisional and void history, and the evidence for each gate.

The gate card records your answer through the channel `app`.
In a host without MCP Apps, the agent gives you the gate page's URL, asks you in the conversation, and records your words through the channel `chat`.

## Viewer layers

The viewer's layers come from the project's annotation set, which the tools derive from the record and you can edit:

- **Callouts** label each part, and each recognised feature such as a hole, thread, slot, fit or sealing face, with its part number, name, material and finish.
- **A legend** lists the callouts.
- **Group toggles** switch groups on and off: by sourcing (make, buy or existing), by subassembly, and by material.
- **Playback of the assembly steps** steps through the assembly order, one numbered step at a time, with the parts and fasteners each step adds.

You can hover over a part or click it to pick it out.
Context parts, such as the customer's equipment, are drawn as ghosts, with a toggle to hide them.
