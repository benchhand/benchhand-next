# Contributing

Read [AGENTS.md](AGENTS.md) and [docs/design-plan.md](docs/design-plan.md) before you change an area.
[docs/tooling.md](docs/tooling.md) lists the checks. `just check` runs them, and the git hooks run the same recipes.

## Contributor license agreement

Each contribution to Benchhand needs a signed [Contributor License Agreement](CLA.md) (CLA). The CLA is the Individual Contributor Non-Exclusive License Agreement from the Contributor Agreements chooser. You keep the copyright in your contribution. You grant Sjors Robroek a license to use it and to license it to others.

### How to sign

[CLA Assistant](https://cla-assistant.io) asks you to sign when you open your first pull request. Sign through the link in its comment. It posts the result as the CLA status on the pull request. A signature covers your later pull requests.

The agreement text is [CLA.md](CLA.md). A public [gist](https://gist.github.com/srobroek/235173e8c3e2efb8de2ec9858e8b36a4) mirrors it for CLA Assistant. Any change to CLA.md must update the gist in the same change.

### Contributions from your employer

If your employer has rights in work that you create, get its permission first. The "How to use this Contributor Agreement" section of the CLA describes this. Benchhand has no CLA for companies.

### Bots

These accounts do not sign:

- `dependabot[bot]`
- `renovate[bot]`
- `github-actions[bot]`
- `sjorsr-release-bot[bot]`, the release bot

## Licence headers

Each source file carries an SPDX header, and files that cannot carry a comment are covered by
[REUSE.toml](REUSE.toml). `reuse lint` checks both, in `just check`, in the pre-commit hook and in CI. The
CLA grants the maintainer a licence and leaves the copyright with you, so name the rights holder of the new file,
yourself or your employer, and the year you wrote it. Add a header to a new file with:

```sh
reuse annotate --license MPL-2.0 --copyright "<rights holder>" --year <year> <file>
```

The maintainer's own files use `--copyright "Sjors Robroek"`.
