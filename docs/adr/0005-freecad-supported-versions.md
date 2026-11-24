# ADR-0005: FreeCAD: an explicit supported-version list and a managed download

Status: accepted. Source: [the approved plan](../design-plan.md).

## Context

The prototype required exactly FreeCAD 1.1.4, installed by hand.

## Decision

`freecad-versions.toml` lists every supported version with platforms, URLs, sha256 and a status (`supported`, `deprecated` or `removed`). The managed download offers only supported versions, and a host FreeCAD must be on the list. `--allow-unsupported` is for development only, and its results are UNKNOWN. New FreeCAD versions are qualified in our CI and added in a release.

## Consequences

Users get a predictable FreeCAD. Supporting a new version is a release task.
