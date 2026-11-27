# benchhand (next)

This is the temporary home of the benchhand rewrite: agent-guided mechanical CAD as an MCP server with pluggable providers. It will replace `benchhand/benchhand` once it matches that repo on the golden end-to-end run. See ADR-0015 and `release.toml`.

- Architecture: start with the [overview](docs/architecture/overview.md), then the other [architecture diagrams](docs/architecture/README.md)
- Design: [`docs/design-plan.md`](docs/design-plan.md)
- Decisions: [`docs/adr/`](docs/adr/README.md)
- Contracts: the [domain model](docs/contract/generated/domain-model/README.md), the [contract reference](docs/contract/generated/README.md), [versioning](docs/contract/versioning.md) and [record migration](docs/contract/record-migration.md)
- Provider protocol: [`docs/contract/provider-protocol.md`](docs/contract/provider-protocol.md)
- Phase summaries: [`docs/phases/`](docs/phases/phase-0-1.md)
- Testing: [`docs/testing.md`](docs/testing.md)
- Tooling, hooks and CI checks: [`docs/tooling.md`](docs/tooling.md)
- Behavioural reference from the prototype (tests, fixtures, schemas, examples): [`reference/`](reference/). It is read-only. Production code is written fresh (ADR-0012).

## Develop

```sh
uv sync --all-packages
mise install        # the pinned tools: d2, prek, typos, taplo, gitleaks, actionlint, zizmor, pinact, osv-scanner
just hooks-install  # git hooks; they call the same recipes CI does (docs/tooling.md)
just check
```
