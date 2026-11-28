# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""benchhand/flags.py and benchhand/flag_provider.py over flags.yaml: the shipped file turns every flag off,
the provider reads a turned-on flag, and every way the file can fail to serve a flag gives the caller's
default with an error code."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from benchhand import flags
from benchhand.flag_provider import FlagsFileProvider
from openfeature.exception import ErrorCode
from openfeature.flag_evaluation import Reason

KEY = flags.RECORD_MIGRATION.key


def _flags_file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "flags.yaml"
    path.write_text(body)
    return path


def _flag_body(**fields: str) -> str:
    """A flags.yaml with the record-migration flag from these fields; an empty field is left out. "on" is quoted
    because bare, YAML reads it as true."""
    flag = {"state": "ENABLED", "variants": '{"on": true, "off": false}', "defaultVariant": '"on"'} | fields
    lines = "".join(f"    {name}: {value}\n" for name, value in flag.items() if value)
    return f"flags:\n  {KEY}:\n{lines}"


def test_the_shipped_flags_file_defines_each_flag_with_its_default_variant() -> None:
    shipped = yaml.safe_load(flags.FLAGS_FILE.read_text())["flags"]
    assert sorted(shipped) == sorted(flag.key for flag in flags.FLAGS)
    for flag in flags.FLAGS:
        definition = shipped[flag.key]
        assert definition["variants"][definition["defaultVariant"]] is flag.default, flag.key


def test_the_shipped_flags_file_decides_record_migration_off() -> None:
    assert flags.decide(flags.file_provider()) == flags.FlagDecisions(record_migration=False)


def test_a_flags_file_with_record_migration_on_decides_it_on(tmp_path: Path) -> None:
    body = flags.FLAGS_FILE.read_text().replace('defaultVariant: "off"', 'defaultVariant: "on"')
    decisions = flags.decide(flags.file_provider(_flags_file(tmp_path, body)))
    assert decisions.record_migration is True


def test_an_enabled_flag_serves_its_default_variant_on_or_off(tmp_path: Path) -> None:
    path = _flags_file(tmp_path, _flag_body())
    on = FlagsFileProvider(path).resolve_boolean_details(KEY, False)
    assert (on.value, on.variant, on.reason, on.error_code) == (True, "on", Reason.STATIC, None)
    path = _flags_file(tmp_path, _flag_body(defaultVariant='"off"'))
    off = FlagsFileProvider(path).resolve_boolean_details(KEY, True)
    assert (off.value, off.variant, off.reason, off.error_code) == (False, "off", Reason.STATIC, None)


@pytest.mark.parametrize(
    ("body", "reason", "code"),
    [
        (None, Reason.ERROR, ErrorCode.GENERAL),
        ("flags: [\n", Reason.ERROR, ErrorCode.PARSE_ERROR),
        ("- not a mapping\n", Reason.ERROR, ErrorCode.FLAG_NOT_FOUND),
        ("flags: {other: {}}\n", Reason.ERROR, ErrorCode.FLAG_NOT_FOUND),
        (f"flags: {{{KEY}: 1}}\n", Reason.ERROR, ErrorCode.FLAG_NOT_FOUND),
        (_flag_body(state="DISABLED"), Reason.DISABLED, ErrorCode.FLAG_NOT_FOUND),
        (_flag_body(state=""), Reason.ERROR, ErrorCode.PARSE_ERROR),
        (_flag_body(defaultVariant='"neither"'), Reason.ERROR, ErrorCode.PARSE_ERROR),
        (_flag_body(defaultVariant='["on"]'), Reason.ERROR, ErrorCode.PARSE_ERROR),
        (_flag_body(variants='{"on": "yes", "off": "no"}'), Reason.ERROR, ErrorCode.TYPE_MISMATCH),
    ],
    ids=[
        "missing file",
        "bad yaml",
        "not a mapping",
        "flag missing",
        "flag not a mapping",
        "disabled",
        "no state",
        "default variant not in variants",
        "default variant not a string",
        "non-boolean variant",
    ],
)
def test_a_flag_the_file_cannot_serve_gives_the_callers_default_with_an_error_code(
    tmp_path: Path, body: str | None, reason: Reason, code: ErrorCode
) -> None:
    path = tmp_path / "flags.yaml" if body is None else _flags_file(tmp_path, body)
    for default in (True, False):
        details = FlagsFileProvider(path).resolve_boolean_details(KEY, default)
        assert (details.value, details.reason, details.error_code) == (default, reason, code)
        assert details.error_message
    assert flags.decide(FlagsFileProvider(path)).record_migration is False


def test_a_flag_asked_for_as_another_type_gives_the_default_with_a_type_mismatch(tmp_path: Path) -> None:
    provider = FlagsFileProvider(_flags_file(tmp_path, _flag_body()))
    for details in (
        provider.resolve_string_details(KEY, "x"),
        provider.resolve_integer_details(KEY, 3),
        provider.resolve_float_details(KEY, 1.5),
        provider.resolve_object_details(KEY, {"a": 1}),
    ):
        assert (details.reason, details.error_code) == (Reason.ERROR, ErrorCode.TYPE_MISMATCH)
    assert provider.resolve_integer_details(KEY, 3).value == 3
