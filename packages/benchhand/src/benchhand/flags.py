# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The benchhand feature flags: one typed definition per flag, chosen in flags.yaml (flagd format) and read
through OpenFeature by the provider in flag_provider.py. The CLI decides every flag once per run and passes
the decisions on; nothing else evaluates a flag, and benchhand-core never sees one."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from openfeature.provider import FeatureProvider

FLAGS_FILE = Path(__file__).with_name("flags.yaml")
DOMAIN = "benchhand"
"""The OpenFeature domain the CLI binds its provider to."""


@dataclass(frozen=True)
class BooleanFlag:
    key: str
    default: bool
    """Served when flags.yaml is missing, unreadable or lacks the flag, or its variant isn't a boolean."""
    kind: Literal["release"]
    owner: str
    remove_by: date


RECORD_MIGRATION = BooleanFlag(
    key="record-migration", default=False, kind="release", owner="sjors", remove_by=date(2027, 2, 26)
)
"""`benchhand record migrate`, prototype record version 2 to 3. Not offered at the first release (owner,
2026-11-27): prototype record v2 exists only inside the benchhand repositories. The evidence reader's
in-memory upgrade of sealed v2 snapshots uses the migrate rules directly and is not behind this flag."""

FLAGS = (RECORD_MIGRATION,)


@dataclass(frozen=True)
class FlagDecisions:
    """Every flag, decided once for a run."""

    record_migration: bool


def file_provider(path: Path = FLAGS_FILE) -> FeatureProvider:
    """The provider over a flags.yaml; it reads the file on each evaluation."""
    from benchhand.flag_provider import FlagsFileProvider

    return FlagsFileProvider(path)


def decide(provider: FeatureProvider) -> FlagDecisions:
    """Bind ``provider``, decide every flag, and release the provider. A provider that fails to start serves
    each flag's default."""
    from openfeature import api
    from openfeature.exception import OpenFeatureError

    with contextlib.suppress(OpenFeatureError):
        api.set_provider_and_wait(provider, DOMAIN)
    try:
        client = api.get_client(DOMAIN)
        return FlagDecisions(
            record_migration=client.get_boolean_value(RECORD_MIGRATION.key, RECORD_MIGRATION.default)
        )
    finally:
        api.clear_providers()
