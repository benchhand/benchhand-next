# Contributing

Read [AGENTS.md](AGENTS.md) and [docs/design-plan.md](docs/design-plan.md) before you change an area.
[docs/tooling.md](docs/tooling.md) lists the checks. `just check` runs them, and the git hooks run the same recipes.

## Contributor License Agreement

Every pull request needs a signed [CLA](CLA.md). The CLA Assistant bot comments on your first pull request
with a link. Reply with `I have read the CLA Document and I hereby sign the CLA` to sign once for all later
contributions. The bot stores the signature in
[benchhand/cla-signers](https://github.com/benchhand/cla-signers). Comment `recheck` to run the check again.

The CLA keeps the maintainer able to offer the code under other terms, such as a commercial licence, without
tracking down every contributor. Your contribution stays available under the project's licence,
[MPL-2.0](LICENSE), either way.

## Licence headers

Each source file carries an SPDX header, and files that cannot carry a comment are covered by
[REUSE.toml](REUSE.toml). `reuse lint` checks both, in `just check`, in the pre-commit hook and in CI. The
CLA grants the maintainer a licence and leaves the copyright with you, so name the rights holder of the new file,
yourself or your employer, and the year you wrote it. Add a header to a new file with:

```sh
reuse annotate --license MPL-2.0 --copyright "<rights holder>" --year <year> <file>
```

The maintainer's own files use `--copyright "Sjors Robroek"`.
