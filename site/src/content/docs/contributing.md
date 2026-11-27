---
title: Contributing
description: Set up the benchhand repository, run its checks, and find the design plan, the decision records and the contributor agreement.
sidebar:
  label: Work on benchhand
---

benchhand is developed in its GitHub repository.
Read [`CONTRIBUTING.md`](repo:CONTRIBUTING.md) before you open a pull request: it covers the contributor license agreement and the licence headers.

## Set up and run the checks

```sh
uv sync --all-packages
mise install        # the pinned tools: d2, prek, typos, taplo, gitleaks, actionlint, zizmor, pinact, osv-scanner, reuse
just hooks-install  # git hooks; they call the same recipes CI does (docs/tooling.md)
just check
```

`just check` runs every check that CI runs, and the git hooks run the same recipes.

## Where the design lives

- [The design plan](repo:docs/design-plan.md): how benchhand is built, with its layers, packages, transport, flow engine and providers.
- [The decision records](repo:docs/adr/): one record for each architecture decision, with its context and consequences.
- [The architecture overview](repo:docs/architecture/overview.md): benchhand in two D2 diagrams, the software in layers and the processes that run it, with links to the other architecture pages.
- [Testing](repo:docs/testing.md): the kinds of test, and the rules every test follows.
- [Tooling](repo:docs/tooling.md): the checks the repository runs, and where each one runs.

## Contributions and licences

- [`CONTRIBUTING.md`](repo:CONTRIBUTING.md): how to contribute, and the licence header each new file carries.
- [The contributor license agreement](repo:CLA.md): CLA Assistant asks you to sign it on your first pull request.
