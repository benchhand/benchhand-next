# benchhand (next)

This is the temporary home of the benchhand rewrite: agent-guided mechanical CAD as an MCP server with pluggable providers. It will replace `benchhand/benchhand` once it matches that repo on the golden end-to-end run. See ADR-0015 and `release.toml`.

- Design: [`docs/design-plan.md`](docs/design-plan.md)
- Decisions: [`docs/adr/`](docs/adr/README.md)
- Architecture diagrams: [`docs/architecture/`](docs/architecture/README.md)
- Contracts: the [domain model](docs/contract/generated/domain-model/README.md), the [contract reference](docs/contract/generated/README.md), [versioning](docs/contract/versioning.md) and [record migration](docs/contract/record-migration.md)
- Provider protocol: [`docs/contract/provider-protocol.md`](docs/contract/provider-protocol.md)
- Phase summaries: [`docs/phases/`](docs/phases/phase-0-1.md)
- Testing: [`docs/testing.md`](docs/testing.md)
- Behavioural reference from the prototype (tests, fixtures, schemas, examples): [`reference/`](reference/). It is read-only. Production code is written fresh (ADR-0012).

## Develop

```sh
uv sync --all-packages
just check
```
