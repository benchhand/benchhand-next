# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""An OpenFeature provider over a flagd-format flags.yaml: boolean flags only, read on every evaluation.

The flagd provider (openfeature-provider-flagd) is not used: it imports the generated flagd gRPC stubs at
load, so it pulls grpcio and protobuf into the install even in file mode. Bead bhn-2dm documents that option
and when to switch to it.

A flag is served from ``flags.<key>`` as its ``defaultVariant``'s value when ``state`` is ENABLED. Anything
else serves the caller's default, with an error code: a missing or unreadable file (GENERAL), YAML that
doesn't parse or a flag that isn't well formed (PARSE_ERROR), a missing flag (FLAG_NOT_FOUND), a DISABLED
flag (reason DISABLED, FLAG_NOT_FOUND), and a variant that isn't a boolean (TYPE_MISMATCH)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from openfeature.evaluation_context import EvaluationContext
from openfeature.exception import ErrorCode
from openfeature.flag_evaluation import FlagResolutionDetails, Reason
from openfeature.provider import AbstractProvider, Metadata


class _Unserved(Exception):
    """A flag the file can't serve as a boolean; the provider answers with the caller's default."""

    def __init__(self, code: ErrorCode, message: str, reason: Reason = Reason.ERROR) -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason


class FlagsFileProvider(AbstractProvider):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path

    def get_metadata(self) -> Metadata:
        return Metadata(name="benchhand flags.yaml")

    def resolve_boolean_details(
        self, flag_key: str, default_value: bool, evaluation_context: EvaluationContext | None = None
    ) -> FlagResolutionDetails[bool]:
        try:
            variant, value = _boolean_variant(self._flag(flag_key), flag_key)
        except _Unserved as unserved:
            return FlagResolutionDetails(
                value=default_value,
                reason=unserved.reason,
                error_code=unserved.code,
                error_message=str(unserved),
            )
        return FlagResolutionDetails(value=value, reason=Reason.STATIC, variant=variant)

    def resolve_string_details(
        self, flag_key: str, default_value: str, evaluation_context: EvaluationContext | None = None
    ) -> FlagResolutionDetails[str]:
        return _only_boolean(default_value)

    def resolve_integer_details(
        self, flag_key: str, default_value: int, evaluation_context: EvaluationContext | None = None
    ) -> FlagResolutionDetails[int]:
        return _only_boolean(default_value)

    def resolve_float_details(
        self, flag_key: str, default_value: float, evaluation_context: EvaluationContext | None = None
    ) -> FlagResolutionDetails[float]:
        return _only_boolean(default_value)

    def resolve_object_details(
        self, flag_key: str, default_value: Any, evaluation_context: EvaluationContext | None = None
    ) -> FlagResolutionDetails[Any]:
        return _only_boolean(default_value)

    def _flag(self, key: str) -> dict[str, Any]:
        try:
            document = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except OSError as error:
            raise _Unserved(ErrorCode.GENERAL, f"cannot read {self._path}: {error.strerror}") from error
        except yaml.YAMLError as error:
            raise _Unserved(ErrorCode.PARSE_ERROR, f"{self._path} is not valid YAML") from error
        flags = document.get("flags") if isinstance(document, dict) else None
        flag = flags.get(key) if isinstance(flags, dict) else None
        if not isinstance(flag, dict):
            raise _Unserved(ErrorCode.FLAG_NOT_FOUND, f"{self._path} has no flag {key}")
        return flag


def _boolean_variant(flag: dict[str, Any], key: str) -> tuple[str, bool]:
    state, variant, variants = flag.get("state"), flag.get("defaultVariant"), flag.get("variants")
    if state == "DISABLED":
        raise _Unserved(ErrorCode.FLAG_NOT_FOUND, f"flag {key} is disabled", Reason.DISABLED)
    if (
        state != "ENABLED"
        or not isinstance(variants, dict)
        or not isinstance(variant, str)
        or variant not in variants
    ):
        raise _Unserved(
            ErrorCode.PARSE_ERROR, f"flag {key} needs state ENABLED and a defaultVariant in variants"
        )
    if not isinstance(variants[variant], bool):
        raise _Unserved(ErrorCode.TYPE_MISMATCH, f"flag {key} variant {variant} is not a boolean")
    return variant, variants[variant]


def _only_boolean[T](default_value: T) -> FlagResolutionDetails[T]:
    return FlagResolutionDetails(
        value=default_value,
        reason=Reason.ERROR,
        error_code=ErrorCode.TYPE_MISMATCH,
        error_message="flags.yaml serves boolean flags only",
    )
