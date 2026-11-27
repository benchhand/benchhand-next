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
| CI `security` workflow | osv-scanner on the three lockfiles | On lockfile and `mise.toml` changes, and weekly. The audit covers `uv.lock`, `ui/pnpm-lock.yaml` and `contracts/pnpm-lock.yaml` only. The tools pinned in `mise.toml` and the `reuse` install are not audited: nothing here reads their advisories. |
| CI `secrets` workflow | gitleaks over the whole history (`just secrets-history`) | On every pull request, forks included, and every push to `main`. No path filter. The CLI needs no licence key or secret. |
| CI `trivy` workflow | `trivy config` (misconfiguration), SARIF to code scanning | On pull requests, pushes to `main` and weekly. It finds nothing until the repo holds a Dockerfile or a manifest. |
| CI `cla` workflow | CLA Assistant: a pull request needs a signed CLA (`CLA.md`) | On pull request events (opened, reopened, new commits) and on `recheck` or signing comments on a pull request. |
| `just check`, pre-commit and the CI `check` job | `reuse lint`: every file has an SPDX licence and copyright, or a `REUSE.toml` entry | Seconds. The hook is the REUSE project's own, at a pinned rev. |

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
| Secrets | slopvac trufflehog (CI) and trivy secret scan; astro-up and platevault gitleaks (hook) | gitleaks offline in the hook, trufflehog over history in CI | None | Added gitleaks 8.30.1 on the staged diff (hook) and over the whole history (`secrets` workflow). trufflehog is the steering's pick for the history scan; gitleaks does both here to keep one tool. Trivy's secret scanner is off: see "Trivy against osv-scanner and gitleaks". |
| Dependency vulnerabilities | slopvac osv-scanner on `uv.lock`; Dependabot or Renovate | `pip-audit` or `uv audit`; osv-scanner where several ecosystems share a repo | None | Added osv-scanner 2.7.1 on `uv.lock`, `ui/pnpm-lock.yaml` and `contracts/pnpm-lock.yaml`: it covers Python and pnpm in one tool. 0 findings. Runs on lockfile changes and weekly. |
| Licences | slopvac `cargo-deny licenses`; `about.toml` | inventory against policy; REUSE for published source | None; the repo had no `LICENSE` file | The repo is MPL-2.0 (owner decision), checked by REUSE (next row). The dependency allowlist is still open: `osv-scanner --licenses` or `pip-licenses` fits. |
| REUSE | The owner's `benchhand-test-src` and `cad-agent-v6-showcase` (MPL-2.0, `REUSE.toml`) | `reuse lint` in `just check`, the REUSE hook, `fsfe/reuse-action` in a required job | None | Added reuse 6.3.0 (mise, `pipx:reuse` with the `charset-normalizer` extra, locked), `REUSE.toml`, SPDX headers on the hand-written sources, `LICENSES/`, `NOTICE`. See "REUSE" below. |
| CLA | platevault `cla-assistant.yml` (CLA Assistant v2.6.1, GitHub App token) | n/a | None | Added `.github/workflows/cla.yml` and `CLA.md`. Signatures go to `benchhand/cla-signers`. See "CLA" below. |
| Container image scan | slopvac trivy | digest-pinned Trivy, `trivy image` on the built image | No image yet | Recommend only, for Phase 7: `trivy image` on the image the release builds, in the release workflow, SARIF to code scanning, `exit-code: 1` on HIGH and CRITICAL. |
| SAST | slopvac CodeQL, trivy fs | ruff `S`; CodeQL where supported; Semgrep or Opengrep | None | Recommend only: CodeQL, and ruff `S`. |
| Misconfiguration (IaC) | slopvac `trivy fs` with the misconfig scanner | `trivy config` | None | Added `.github/workflows/trivy.yml`: `trivy config`, HIGH and CRITICAL, SARIF to code scanning, weekly as well as on pull requests (the check database changes without a commit). It reports nothing on this tree: the repo has no Dockerfile, Kubernetes manifest or Terraform. |
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

## Trivy against osv-scanner and gitleaks

The brief asked for `trivy fs` (vulnerabilities and secrets) and `trivy config`. Two of those concerns already have a scanner, so Trivy runs `config` only. One scanner per concern, after running all three tools over this tree:

| Concern | Kept | Dropped | Why |
|---|---|---|---|
| Dependency vulnerabilities | osv-scanner | `trivy fs --scanners vuln` | On `uv.lock` and `ui/pnpm-lock.yaml` both report nothing. Trivy skips development dependencies by default and listed no result for `contracts/pnpm-lock.yaml`, whose packages are all dev dependencies, while osv-scanner scans its 250 packages. The two differ only under `research/cel-neutral/`, which ships nothing: Trivy reports 2 HIGH advisories on `golang.org/x/text` and 1 on `lodash-es`, and osv-scanner reports the `lodash-es` ones only. osv-scanner is already a gate, reads every ecosystem here from one tool and uses osv.dev, which aggregates the GitHub advisories. A second scanner would report the same advisories twice and miss the dev-tool lockfile. |
| Secrets | gitleaks | `trivy fs --scanners secret` | gitleaks runs in the pre-commit hook on the staged diff and in CI over the whole history. Trivy scans the tree only: in a probe repo with a key committed and then removed, gitleaks flagged it (`generic-api-key`) and Trivy did not. |
| Misconfiguration | Trivy (`config`) | none | Neither other tool does this. |

Trivy's SARIF upload puts the findings in the Security tab. osv-scanner can emit SARIF too (`--format sarif`); that is a possible later step and the gate doesn't need it.

`trivy config` found nothing on this tree ("Detected config files: 0"). The workflow is ready for the Phase 7 image and its manifests. The action is `aquasecurity/trivy-action` v0.36.0, pinned by commit SHA, with Trivy at v0.76.2. The steering restricts Trivy after the March 2026 compromise of the action's tags; the SHA pin answers that for the action, and a digest-pinned Trivy binary is not done.

## REUSE

- **Licence:** MPL-2.0, the owner's decision (sole copyright holder). `LICENSE` and `LICENSES/MPL-2.0.txt` hold the text. `LICENSES/` also holds the three texts the third-party files need: Apache-2.0, BSD-2-Clause and the W3C Document License. `NOTICE` records where each third-party file came from.
- **Headers:** `reuse annotate --license MPL-2.0 --copyright "Sjors Robroek" --year 2026` on the hand-written Python, TypeSpec, JavaScript, shell, Go, Rust and TypeScript sources, the workflows and the `justfile`. A new source file without a header fails `reuse lint`.
- **Everything else is in `REUSE.toml`:** documents, JSON, YAML, TOML, lockfiles, SVG, D2, protobuf and the frozen `reference/` tree. YAML is listed by location, not by extension, so a workflow without an SPDX header fails `reuse lint`. Precedence is `closest`, so a header in a file wins.
- **Generated files: `REUSE.toml`, not generator headers.** The generators write Python, TypeScript, JavaScript, JSON Schema and Markdown, and `just contracts-drift` compares their output byte for byte. Headers would mean changing the emitters and every committed output, and JSON can't hold a comment. One table entry covers all of them and leaves drift clean. The cost: `reuse lint` does not object to a hand-written file added under a generated directory. `just contracts-check` does: `contracts_gen check` fails on every file in those directories that a fresh generation doesn't write (`extra`), and `tests/test_contracts_gen.py` covers that case.
- **`research/`:** our own code and recorded output carry our licence. The one third-party file is cel-spec's conformance tests (`research/cel-neutral/conformance/suite.json` and the summary derived from it), kept under Apache-2.0 with the copyright holders named and recorded in `NOTICE`.
- **`reference/`:** the prototype is the owner's, so one table entry covers it. Its 3MF and W3C schema files keep BSD-2-Clause and the W3C licence, as in the owner's `benchhand-test-src`.
- **Package metadata:** `license = "MPL-2.0"` and `license-files = ["LICENSE"]` (PEP 639) in the five package `pyproject.toml` files and the workspace root, with `hatchling>=1.27`, which supports PEP 639. Each package has its own `LICENSE`, a regular file with the root file's bytes, because hatchling reads only files inside the package directory, and a symlink turns into a text file holding its target path where `core.symlinks` is false. `tests/test_package_licences.py` checks that each copy is not a symlink and equals the root file, and (marked `wheel`) that a wheel built from each package's unpacked sdist, with no workspace around it, holds `licenses/LICENSE` with the same bytes. The whitespace fixers skip every `LICENSE`. `license` is also set in `research/cel-neutral/py/pyproject.toml` and in the four `package.json` files.
- **Enforcement:** `just reuse` runs `reuse lint` and is part of `just check`. The `reuse` hook comes from `fsfe/reuse-tool` at `v6.3.0`. `fsfe/reuse-action` v6.0.0, pinned by SHA, runs in the CI `check` job, and the `hooks` job skips the hook so the check runs once. `"pipx:reuse"` 6.3.0 with the `charset-normalizer` extra is in `mise.toml`, and `mise.lock` pins it with a uv lock under `.mise/locks/`, which is committed.
- **Required job:** `main` has no branch protection yet, so no job is required. The REUSE step sits in `check`, which a required `ci-gate` would need anyway.

## CLA

- `.github/workflows/cla.yml` runs CLA Assistant (`contributor-assistant/github-action` v2.6.1) on pull request events (opened, reopened, synchronize) and on `recheck` and signing comments, as platevault does. A comment starts the job only if it is on a pull request and is one of those two texts; the check runs before the job mints the token. The job has no `statuses` permission (the action reruns its own Actions check and posts no commit status), and the workflow doesn't react to `closed` while `lock-pullrequest-aftermerge` is `false`. `CLA.md` is platevault's text with the licence named as MPL-2.0. `CONTRIBUTING.md` links it.
- Signatures are written to `signatures/cla.json` on `main` of `benchhand/cla-signers` (`remote-organization-name: benchhand`, `remote-repository-name: cla-signers`). A GitHub App token (`actions/create-github-app-token` v3.4.0, limited to that repository with `contents: write`) does the write, because the workflow's `GITHUB_TOKEN` can't write to another repository.
- The allowlist is platevault's: `srobroek,bot*,dependabot*,renovate*,*[bot]*,sjorsr-release-bot*`.
- **The action is archived** (last push 2026-03-23). The SHA pin means what runs doesn't change, but it gets no fixes. zizmor flags it (`archived-uses`) and flags the `pull_request_target` and `issue_comment` triggers (`dangerous-triggers`). Both are ignored for `cla.yml` only, with the reason, in `.github/zizmor.yml`. The workflow checks out no code.
- **The action has known gaps (v2.6.1):**
  - It fetches only the first 100 commits of a pull request and never follows the pagination cursor, so a contributor who appears only after commit 100 isn't checked.
  - It ignores co-authors.
  - It doesn't check the PR opener independently of the commits.

  The maintained `iainmcgin/cla-github-action` fork fixes these and takes the same inputs. Its `v3.2.0` tag peels to `0d27e5a16278d4adb6b0c4b92f08ad27b0a21dc8`. Its README says it is for internal use and names no official successor, so the choice is the owner's. `cla.yml` keeps the alternative as a comment above the pin, so the swap is one `uses:` line. The review asks for a test that an unsigned contributor on page two fails the check. That needs a pull request with more than 100 commits and a live run, so it isn't done here; do it when the action is chosen.
- The workflow has not run: it needs the secrets under "Left for the owner".

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
- Semgrep or Opengrep. The container image scan (`trivy image`) waits for the Phase 7 image.
- Mutation testing. The steering puts it in a scheduled job. It would be slow on this suite.
- SLSA provenance, an SBOM and OIDC publishing, once a release exists.
- The CLA workflow needs these, on this repository. I invented none of them:
  - a GitHub App installed on `benchhand/cla-signers` with **Contents: read and write**. Create a new one, or install platevault's on the `benchhand` organisation;
  - the repository secret `CLA_APP_CLIENT_ID`, the App's **Client ID** from its settings page (the workflow uses `client-id`, since `app-id` is deprecated in `create-github-app-token` v3; platevault's `CLA_APP_ID` holds the App ID instead);
  - the repository secret `CLA_APP_PRIVATE_KEY`, a private key generated for that App (the whole `.pem`);
  - both secrets come from 1Password through `fnox push`, which writes repository secrets only, never variables. That is why the Client ID is a secret and not a variable. `fnox.toml` holds the setup: a 1Password provider, a `gh` target for `benchhand/benchhand-next`, and the two secrets. Its vault (`TODO-VAULT`) and the item and field of each secret (`TODO-ITEM/TODO-FIELD`) are placeholders. Fill them in, run `fnox push --dry-run`, then `fnox push`. `gh` must be logged in as someone who can manage the repository's secrets. fnox is pinned in `mise.toml` (1.50.0) and CI doesn't install it. Nobody has run `fnox` or `op` against this config;
  - if you prefer a PAT, a secret `PERSONAL_ACCESS_TOKEN` with `contents: write` on `benchhand/cla-signers`, and the token step goes;
  - `main` of `cla-signers` must accept pushes from the App (no required reviews or status checks for it).
- Code scanning must be enabled on the repository for the Trivy SARIF upload. The API reports it as configured.
- The dependency licence allowlist (`osv-scanner --licenses` or `pip-licenses`), now that the repo's own licence is set.
- Whether to replace the archived CLA Assistant action, and with what: v2.6.1 with its gaps above, or the iainmcgin fork (one line in `cla.yml`).
- A commit-msg hook and a PR-range commit check.
- A markdown link check (lychee) and markdownlint.
- `jscpd` as a duplication report.
- `mypy` is in the dev group and unused since pyright is the gate; drop it if the owner agrees.
- Hooks live in the clone's `.git/hooks`, which the worktrees share. This machine's `core.hooksPath` points at a system-wide directory, so `prek install` refuses without `--force`. `just hooks-install` doesn't pass it: it is the owner's call whether to chain the system hooks.
