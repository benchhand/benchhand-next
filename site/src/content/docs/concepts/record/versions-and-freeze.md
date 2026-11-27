---
title: Versions and the freeze
description: Version snapshots, sealing and the freeze before release.
sidebar:
  order: 3
---

## Version snapshots

`model.build` builds the design as a new version, such as `v4`, under `hw/versions/<V>/`.
The version holds a snapshot of the record documents it was built from, under `record/`.
The snapshot honours the project's ignore rules, so ignored files stay out of it.

`preview.part` and `preview.assembly` build without making a version.
Gates, checks and evidence always refer to a built version, never to a preview.

A snapshot keeps the state of the record at the build.
Evidence compares that state with the current record to tell which check outcomes have gone stale, and a comparison against an earlier version, with `--since-version`, uses the earlier snapshot as its baseline.

## Seal and verify

Each version is sealed by its [`manifest.json`](/reference/contracts/record/bundle-manifest/), which lists the SHA-256 of every other file in the version.
Check bundles are sealed the same way: each bundle under `hw/checks/<V>/<S>/` has its own manifest, and it is bound to the manifest SHA-256 of the version it checked.

Before benchhand reads the evidence of a version, it verifies it:

1. It refuses a path reached through a link.
2. It checks that the version has a manifest.
3. It verifies the seal of `hw/versions/<V>/` against the bytes on disk.
4. It verifies the seal of each check bundle of the version the same way.

A version that isn't built, or fails its seal, is refused before any check bundle or snapshot is read.

Sealed history is never rewritten.
`hw/versions/`, `hw/checks/` and `hw/releases/` keep their exact bytes, through every later change and every record migration.

## The freeze

The DESIGN freeze fixes one built version as the configuration to release.
It is a single human gate, and it opens only when:

- every three-step gate, from the LAYOUT freeze to ANALYSIS, has passed its human gate;
- every made part has its manufacturing outputs;
- the version's [evidence assessment](/concepts/record/evidence/) has formed its acceptance, with an `evidence_sha256`.

When you approve the freeze, the flow engine records the frozen configuration in `flow.frozen` in `hw/product.yaml`:

| Field | What it holds |
|---|---|
| `version` | the frozen version |
| `manifest_sha256` | the SHA-256 of that version's manifest |
| `decision` | the gate decision that approved the freeze |
| `evidence_sha256` | the digest of the acceptance inventory: the verification matrix, the evidence and the finding dispositions, the check bundle manifests the evidence relies on, and the source files |

Once the configuration is frozen, layout findings block at every stage.
A change after the freeze is an engineering change, which [Approvals and scoped re-approval](/concepts/process/approvals/) describes.

## The release

The RELEASE gate is a single human gate.
Its packet shows the frozen version, the revision to issue, the contents of the release and its verification.

After you approve it, the release tool packages the frozen version into `hw/releases/<REV>/`: the product's STEP AP242 file, its GLB and the documentation set.
STEP AP242 is the primary deliverable.

The release refuses to package, and reports findings instead, unless:

- `flow.frozen` names the version and its manifest SHA-256;
- the release decision is approved;
- the version passes its seal check, and its evidence assessment forms an acceptance;
- that acceptance's `evidence_sha256` equals the one the freeze recorded;
- the product export holds no part with the role `context` or `tooling`.

A freeze recorded without an `evidence_sha256` is refused by the release until a new freeze records one.
