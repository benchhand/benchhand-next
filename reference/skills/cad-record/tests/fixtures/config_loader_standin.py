"""LOCAL STAND-IN for skills/cad-record/scripts/config_loader.py, which has not landed yet.

It has the loader's public shapes (`Layer`, `Config`, `ConfigError`, `load`, `merge`, `env_layer`) and
only as much behavior as test_cli.py needs: schema defaults, env values and a CLI layer, no validation.
Delete it when the real loader lands and point test_cli.py at that.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

Source = str


@dataclass(frozen=True)
class Layer:
    values: Mapping[str, Any]
    sources: Mapping[str, Source]


@dataclass(frozen=True)
class Config:
    values: Mapping[str, Any]
    sources: Mapping[str, Source]
    warnings: tuple[dict[str, Any], ...] = field(default=())


class ConfigError(Exception):
    """`errors`: a tuple of mappings with message, pointer, source and value.

    Sorted by pointer, then message. `value` is absent for a missing required key, and None for an explicit null."""

    def __init__(self, errors: Iterable[Mapping[str, Any]]) -> None:
        self.errors: tuple[Mapping[str, Any], ...] = tuple(sorted(errors, key=lambda e: (e["pointer"], e["message"])))
        super().__init__(f"{len(self.errors)} invalid config value(s)")


def _leaves(schema: Mapping[str, Any], path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Mapping[str, Any]]]:
    for key, sub in schema.get("properties", {}).items():
        if "properties" in sub:
            yield from _leaves(sub, (*path, key))
        else:
            yield (*path, key), sub


def _pointer(path: tuple[str, ...]) -> str:
    return "".join("/" + key.replace("~", "~0").replace("/", "~1") for key in path)


def _path(pointer: str) -> tuple[str, ...]:
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in pointer.split("/")[1:])


def _set(values: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    for key in path[:-1]:
        values = values.setdefault(key, {})
    values[path[-1]] = value


def _coerce(kind: str, text: str) -> Any:
    return {"integer": int, "number": float, "boolean": lambda t: t.lower() == "true"}.get(kind, str)(text)


def env_layer(schema: Mapping[str, Any], environ: Mapping[str, str]) -> Layer:
    values: dict[str, Any] = {}
    sources: dict[str, Source] = {}
    for path, sub in _leaves(schema):
        name = sub.get("x-env")
        if name in environ:
            _set(values, path, _coerce(sub["type"], environ[name]))
            sources[_pointer(path)] = f"env:{name}"
    return Layer(values, sources)


def _apply(config: Config, layer: Layer) -> Config:
    values = copy.deepcopy(dict(config.values))
    for pointer in layer.sources:
        path = _path(pointer)
        node: Any = layer.values
        for key in path:
            node = node[key]
        _set(values, path, node)
    return Config(values, {**config.sources, **layer.sources}, config.warnings)


def load(schema: Mapping[str, Any], *, files: tuple[Any, ...] = (), env: Mapping[str, str] | None = None,
         cli: Layer | None = None) -> Config:
    defaults: dict[str, Any] = {}
    sources: dict[str, Source] = {}
    for path, sub in _leaves(schema):
        if "default" in sub:
            _set(defaults, path, sub["default"])
            sources[_pointer(path)] = "default"
    config = _apply(Config({}, {}), Layer(defaults, sources))
    config = _apply(config, env_layer(schema, env or {}))
    return _apply(config, cli) if cli is not None else config


def merge(config: Config, cli: Layer) -> Config:
    return _apply(config, cli)
