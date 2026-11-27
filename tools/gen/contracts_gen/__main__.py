# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Command line: ``python -m contracts_gen {generate,check,breaking,lint-allowed}`` (`just contracts`)."""

from __future__ import annotations

import argparse
import sys

from .breaking import check_against, last_release_tag
from .generate import drift, generate
from .lint import unexpected
from .sources import REPO_ROOT


def _generate(_args: argparse.Namespace) -> int:
    generate(REPO_ROOT)
    print("contracts: generated")
    return 0


def _check(_args: argparse.Namespace) -> int:
    lines = drift()
    if lines:
        print("contracts: generated files are out of date; run `just contracts`:", file=sys.stderr)
        print("\n".join(f"  {line}" for line in lines), file=sys.stderr)
        return 1
    print("contracts: generated files are up to date")
    return 0


def _breaking(args: argparse.Namespace) -> int:
    base = args.base or last_release_tag(REPO_ROOT)
    if base is None:
        print("contracts: no release tag reachable from HEAD; skipping the breaking-change check")
        return 0
    failed = False
    for report in check_against(REPO_ROOT, base):
        if report.allowed:
            continue
        failed = True
        print(
            f"{report.rel_path}: breaking change since {base} without a major x-version bump "
            f"({report.old_version} -> {report.new_version}):",
            file=sys.stderr,
        )
        for change in report.changes:
            print(f"  {change.pointer or '/'}: {change.rule}: {change.detail}", file=sys.stderr)
    if not failed:
        print(f"contracts: no unannounced breaking change since {base}")
    return 1 if failed else 0


def _lint_allowed(_args: argparse.Namespace) -> int:
    new, stale = unexpected(sys.stdin.read())
    for line in new:
        print(f"contracts: lint finding not in contracts_gen.lint.ALLOWED: {line}", file=sys.stderr)
    for line in stale:
        print(f"contracts: lint.ALLOWED lists a finding no longer reported: {line}", file=sys.stderr)
    if new or stale:
        return 1
    print("contracts: every kept lint finding is listed, with its reason")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="contracts_gen", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("generate", help="regenerate every output from contracts/").set_defaults(
        run=_generate
    )
    commands.add_parser("check", help="fail when the generated files differ from a fresh run").set_defaults(
        run=_check
    )
    breaking = commands.add_parser(
        "breaking", help="fail on a breaking change without a major x-version bump"
    )
    breaking.add_argument("--base", help="git revision to compare with (default: the last v* tag)")
    breaking.set_defaults(run=_breaking)
    commands.add_parser(
        "lint-allowed", help="compare a `jsonschema lint --json` report on stdin with the kept findings"
    ).set_defaults(run=_lint_allowed)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
