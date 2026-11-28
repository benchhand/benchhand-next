<!--
SPDX-FileCopyrightText: 2026 Sjors Robroek
SPDX-License-Identifier: MPL-2.0
-->
# Shared parts across projects

A product variant is its own project (RULE-06), so sibling projects need a way to use the same part.
This note records how they do it. It is built in Phase 4, with part sourcing.

## Owner decision, 2026-11-28

Library projects, references that always carry a copy, and forks for local changes, in Phase 4
with part sourcing (IR-228). The owner asked what happens when a source project is deleted. The
design answers that the using project keeps its own copy.

## Library projects

A library project is a benchhand project that releases parts and subassemblies at revisions and
has no product of its own. Any project can use its released parts. Only released revisions are
shared; a part without a release is not.

## A borrowed part

When a project uses a library part at a revision, benchhand copies that release's sealed files
into the project's object store (`.benchhand/objects/sha256/`, ADR-0023):

- the STEP files, the part record, the drawing and the docs;
- the sha256 of each file, and the provenance: the library, the part number, the revision and the
  release digest.

The record holds the reference and the digest. Builds, checks and releases read the copy and never
the library.

| Event | Result |
|---|---|
| The library is deleted or moved | The project works unchanged. A check reports, as information only, that the source is unreachable. |
| The library releases a newer revision | A check reports the newer revision. The project updates only when the user chooses, through change impact and re-approval. |
| Someone edits the copy in the project | The sha256 differs from the recorded digest, and the check fails. |

## A fork

To change a borrowed part for one project, the user forks it. The fork becomes the project's own
part, with its own part number. It records its origin (library, part number, revision, release
digest) and does not follow the library.

## Record changes

The record gains a borrowed-part reference (library, part number, revision, release digest) and a
fork origin field. Both are contract additions, specified with part sourcing.
