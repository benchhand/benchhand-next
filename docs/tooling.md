# Tooling

What the repo runs to keep code, config and workflows clean, where each check runs, and what is left for the owner to decide. The survey behind it covers the owner's other repos (slopvac, astro-up, platevault, harness-plugins) and the `toolchain` and `lang-python` steering skills. `docs/testing.md` covers the tests themselves.

## How it fits together

- `mise.toml` pins every tool by exact version, and `mise.lock` holds the checksum of each release asset. `mise install` installs them. CI installs the same set with `jdx/mise-action` and `MISE_LOCKED=1`, so an install fails if a checksum is missing.
- The Python tools (pyright, vulture, pytest-cov, pytest-xdist) are exact pins in the `dev` group of `pyproject.toml`, locked in `uv.lock`.
- Every check is a `just` recipe. The git hooks in `.pre-commit-config.yaml` and the CI jobs call the same recipes, so they can't drift apart. `just hooks-install` installs the hooks. `just hooks` runs all of them on every file, which is what the CI `hooks` job does.
- `just check` runs everything that works offline, including the tests.

| Where | What runs | Time on a laptop (14 cores) |
|---|---|---|
| pre-commit | merge-conflict, private-key, large-file, YAML/TOML/JSON syntax, trailing whitespace, end-of-file, ruff, typos, gitleaks on the staged diff, taplo, workflow lint when `.github/` changed, contract checks when contract files changed | About 1.2 s for a commit that touches one Python file. About 11 s when a `contracts/` file is staged, because `tsp compile` runs. |
| pre-push | pyright, vulture, unit and API tests (`packages/`, in parallel) when Python files changed | About 77 s: pyright 12 s, vulture 1 s, tests about 60 s. |
| CI `hooks` job | Every hook on every file, then the online workflow checks (pin comments match their SHAs, zizmor's online audits) | Not measured; the same recipes, plus setup. |
| CI `check` job | The full test suite with a coverage summary, the wheel tests, the function map, TypeScript types, contract checks and drift, the prose gate | The suite takes about 8 minutes (7:37 and 8:55 in two local runs), and CI has fewer cores than the laptop. |
| CI `security` workflow | osv-scanner on the three lockfiles, gitleaks over the whole history | On lockfile changes and weekly. |

The pre-push hook runs `packages/` only. `tests/` (contract generation, diagram rendering, function map) takes minutes and stays in CI. The `packages/` tests alone take about 5 minutes without `-n auto`.

The contracts hook runs only the checks that need no regeneration: `tsp format --check`, `tsp compile --warn-as-error`, the schema meta-validation and the schema lint (`just contracts-validate`). Drift, a full regeneration, stays in CI and in `just contracts-drift`. A missing `contracts/node_modules` or `d2` fails with the install command.

## Survey

"Peers" are the four repos above. "Steering" is the `toolchain-quality-observability`, `ci-github-actions` and `project-scaffold` skills and `lang-python-quality`. "Before" is benchhand-next before this change. "Now" says what this change did.

| Concern | Peers | Steering | Before | Recommendation and status |
|---|---|---|---|---|
| Formatting (Python) | slopvac ruff in hook and CI | `ruff format --check` | ruff in `just lint` and CI | Kept. Pre-commit hook and `hooks` job call `just lint`. |
| Lint (Python) | ruff | ruff; add `S` and `C901` | ruff `E F W I B UP C901 PLR*` | Kept. Ruff `S` (security) is not enabled: a recommendation below. |
| Types (Python) | none (slopvac has no Python types gate) | pyright or mypy, strict for new code | `[tool.pyright]` configured but never run; mypy in the dev group, never run; 1,800 errors when run, nearly all in `reference/` | Added pyright 1.1.414 (`just typecheck-python`), scoped to `packages/`, `tests/`, `tools/`. 0 errors. Pre-push and CI. |
| Types (TypeScript) | harness-plugins `tsc` | `tsc --noEmit` | `just typecheck` (ui) | Kept as `just typecheck-ui`. `just typecheck` runs both. |
| Tests | slopvac pytest; platevault nextest | `pytest -x` in CI | `uv run pytest`, wheel tests | Kept. `just test-fast` (`packages/` with xdist, pytest-xdist 3.8.0) added for pre-push. |
| Coverage | slopvac and platevault have coverage workflows (Rust) | Python coverage reported | None | Added pytest-cov 7.1.0 (`just test-coverage`). The CI summary lists files below 100%. No threshold. |
| Dead code | none for Python | vulture at 100% confidence with reviewed exceptions | None | Added vulture 2.16 at 60% confidence, which finds unused functions, classes and variables, not just unused arguments. Config and reasons in `[tool.vulture]`. Pre-push and CI. |
| Duplicate code | none | `jscpd` as a report, not a gate | None | Recommend only. Run `jscpd` once as a report on `packages/` and `tools/` before choosing a threshold. |
| Complexity | slopvac lizard (`-C 15`) | cognitive 15 with `complexipy`; cyclomatic 10-12 | ruff `C901` at 10, `PLR0912/0913/0915`, enforced | Kept. Add `complexipy` (cognitive 15) only if the owner wants Sonar-style nesting weights. |
| Secrets | slopvac trufflehog (CI); astro-up and platevault gitleaks (hook) | gitleaks offline in the hook, trufflehog over history in CI | None | Added gitleaks 8.30.1 on the staged diff (hook) and over the whole history (`security` workflow). trufflehog is the steering's pick for the history scan; gitleaks does both here to keep one tool. |
| Dependency vulnerabilities | slopvac osv-scanner on `uv.lock`; Dependabot or Renovate | `pip-audit` or `uv audit`; osv-scanner where several ecosystems share a repo | None | Added osv-scanner 2.7.1 on `uv.lock`, `ui/pnpm-lock.yaml` and `contracts/pnpm-lock.yaml`: it covers Python and pnpm in one tool. 0 findings. Runs on lockfile changes and weekly. |
| Licences | slopvac `cargo-deny licenses`; `about.toml` | inventory against policy; REUSE for published source | None; the repo has no `LICENSE` file | Recommend only: the repo's own licence and the allowed dependency licences are an owner decision. Then `osv-scanner --licenses` or `pip-licenses` fits. |
| SAST | slopvac CodeQL, trivy fs | ruff `S`; CodeQL where supported; Semgrep or Opengrep | None | Recommend only: CodeQL, and ruff `S`. |
| Workflow lint | slopvac actionlint and zizmor | actionlint, zizmor, pinact | None | Added actionlint 1.7.12 and zizmor 1.33.1 (offline in the hook; online audits in CI). Fixed what they found: see below. |
| Action pinning | slopvac pinact, SHA pins; harness-plugins SHA pins; astro-up and platevault use tags | pin by full SHA with a version comment; one updater owns the pins | Tags (`@v4`) | Added pinact 5.0.2. All `uses:` are full SHAs with a comment, each checked against the GitHub API. The hook checks for a full SHA; CI also checks the comment matches. |
| YAML lint | slopvac yamllint | `check-yaml` | None | `check-yaml` in the hook (syntax). yamllint left out: actionlint covers workflows, and the other YAML is small. |
| TOML lint and format | slopvac taplo | `taplo fmt --check` | None | Added taplo 0.10.0 with `.taplo.toml`. |
| Markdown lint | slopvac markdownlint-cli2, Vale, slopvac itself | `markdownlint-cli2` | slopvac on changed `.md` files in CI | Kept slopvac. Recommend only: markdownlint would flag the existing ADRs and plan en masse. |
| Spelling | slopvac, astro-up and platevault use typos | typos (cspell as an alternative) | None | Added typos 1.52.2 with `_typos.toml`. |
| Links | slopvac lychee (online in CI, offline option) | `lychee --offline` in a hook, online in CI | None | Recommend only: `lychee --offline` on `docs/` and `README.md`, online weekly. Needs a decision on which URLs to accept. |
| Large files | astro-up (`--maxkb=2000`), platevault | `--maxkb=512` | None | Added `check-added-large-files` at 1 MiB, generated validators excluded (the largest is 900 KiB). |
| Merge conflicts, private keys, line endings | astro-up, platevault | baseline hooks | None | Added merge-conflict, detect-private-key, trailing-whitespace and end-of-file. `mixed-line-ending` is left out: nothing has CRLF. |
| Commit messages | platevault cocogitto; astro-up `semantic-pr` | conventional-pre-commit `--strict` at commit-msg, plus a CI check over the PR range | None; the log already follows `type(scope): subject` | Recommend only: add a commit-msg hook and a CI check, once the owner confirms the scopes. |
| Supply chain and provenance | slopvac `release-provenance.yml`, SHA-checked mise installs | `actions/attest-build-provenance`, OIDC publishing, SBOM | No releases yet | `mise.lock` checksums added. Provenance and SBOM are recommend only until there is a release. |
| Dependabot or Renovate | slopvac and harness-plugins use Renovate | One updater, with cooldowns and action-pin updates | None | Recommend Renovate, since both peers use it: action SHAs, `uv.lock`, the pnpm lockfiles and `mise.toml` would drift without it. Needs the Renovate app installed on the repo. |
| Required check | astro-up and slopvac have a gate job | one `ci-gate` job as the only required check | `check` job; `paths-ignore: reference/**` on the PR trigger | Recommend only: a `ci-gate` job (`re-actors/alls-green`) and branch protection naming it. The `paths-ignore` on the trigger would block merges once the check is required. |

## What the new tools found

- **pyright:** 1,816 errors on the default config, 1,796 of them in `reference/` and 8 in `research/`. Scoped to the code the repo owns, 6 remained. Three were `ContractValidator` used as a type, though it is a variable made by `validators.extend`: fixed by typing the three parameters as `jsonschema.protocols.Validator` (`tools/gen/contracts_gen/examples.py`). Three were in `tools/probe/probe.py`, a PEP 723 script whose `mcp` dependency the workspace doesn't install: excluded.
- **vulture:** five names nothing used, now removed: `JsonObject` (`record/model.py`), `GuidelineDigests` (`record/evidence/guidelines.py`), `RESULTS` and `RESOLVED` (`record/evidence/results.py`), `EXPORT_3MF` (a test) and `Judge` (`tools/equiv/replay.py`). The other hits were framework-called and are listed with their reasons in `[tool.vulture]`: pydantic's `model_config`, the `__exit__` arguments, `@pytest.fixture`, a typer command, a monkeypatched `Path.unlink` signature, a pydantic field a test assigns, and the reference-map `inferred` field.
- **typos:** 3,067 hits, nearly all in `reference/`, generated files and recorded output. After excluding those (`_typos.toml`) the real source flagged `PN` as `ON` (a part number, so `PN`, `Pn` and `pn` are allowed), `ded` (a process code in `contracts/record/product.tsp`) and `aproved` (a misspelling used on purpose in ADR-0020). `_typos.toml` skips `research/`, whose inputs misspell field names to see how each evaluator fails. Nothing else in the source was misspelled.
- **gitleaks:** 29 hits over 500 commits, all the `generic-api-key` rule. Two sources, both false positives and both allowlisted by path in `.gitleaks.toml`: the minified generated validators in `ui/shared/contracts/`, and sha256 part keys in a `reference/` fixture.
- **taplo:** `pyproject.toml` needed reformatting after the new config was added. Run with the repo's config it finds nothing else. Without a config it walks `reference/` and `target/`, hence `.taplo.toml`.
- **end-of-file fixer:** would have rewritten two recorded evidence fixtures (`lamp_arm_*.412b5d9.json`) and `.pi/settings.json`. The hook skips them, and the generated and verbatim files too: a fixed copy would stop matching its source or fail `just contracts-drift`.
- **actionlint:** one shellcheck finding (SC2086) in the prose-gate step: an unquoted `$files`, which is intended. Suppressed in place with a reason.
- **zizmor:** seven findings in `ci.yml`: five unpinned actions, one template injection (`${{ github.base_ref }}` inside a `run:` script, now passed through `env`), and `actions/checkout` persisting credentials (now `persist-credentials: false`; the repo is public, so the later `git fetch` needs none). Plus an unpinned `just` version: now 1.59.0.
- **pinact:** pinned all six actions. Each SHA was checked against the GitHub API: the tag in the comment resolves to the same commit. The major versions are unchanged (`checkout` v4, `setup-uv` v6, and so on); newer majors exist and are left to the updater.
- **osv-scanner:** no vulnerabilities in 347 locked packages.

## Left for the owner

- Renovate (or Dependabot) for the action SHAs, lockfiles and `mise.toml`. Both peers with an updater use Renovate.
- A `ci-gate` job, and branch protection that names it. See the `paths-ignore` note in the table.
- CodeQL, and ruff's `S` rules, for SAST. ruff `S` is free; CodeQL needs a decision on the repo's code-scanning settings.
- Trivy (the steering restricts it after the March 2026 compromise; use only digest-pinned and signature-checked), Semgrep or Opengrep.
- Mutation testing. The steering puts it in a scheduled job. It would be slow on this suite.
- SLSA provenance, an SBOM and OIDC publishing, once a release exists.
- A licence policy: the repo's own licence, then the dependency allowlist.
- A commit-msg hook and a PR-range commit check.
- A markdown link check (lychee) and markdownlint.
- `jscpd` as a duplication report.
- `mypy` is in the dev group and unused since pyright is the gate; drop it if the owner agrees.
- Hooks live in the clone's `.git/hooks`, which the worktrees share. This machine's `core.hooksPath` points at a system-wide directory, so `prek install` refuses without `--force`. `just hooks-install` doesn't pass it: it is the owner's call whether to chain the system hooks.
