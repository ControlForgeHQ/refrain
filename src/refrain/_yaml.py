"""Shared strict YAML parsing for configuration and content files."""

from __future__ import annotations

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode


class _StrictSafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[str, object]:
        if not isinstance(node, MappingNode):
            return super().construct_mapping(node, deep=deep)

        keys: set[str] = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "merge keys are not supported",
                    key_node.start_mark,
                )
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "mapping keys must be strings",
                    key_node.start_mark,
                )
            if key in keys:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"duplicate mapping key {key!r}",
                    key_node.start_mark,
                )
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


def load_yaml(contents: str) -> object:
    """Parse one YAML document, rejecting aliases, anchors, and duplicate keys."""
    for event in yaml.parse(contents, Loader=yaml.SafeLoader):
        if isinstance(event, AliasEvent) or getattr(event, "anchor", None) is not None:
            raise yaml.YAMLError("anchors and aliases are not supported")
    loader = _StrictSafeLoader(contents)
    try:
        return loader.get_single_data()
    except (KeyError, ValueError) as error:
        raise yaml.YAMLError(f"invalid YAML scalar: {error}") from error
    finally:
        loader.dispose()


def yaml_error_location(error: yaml.YAMLError) -> str | None:
    """Return a parser error's one-based line and column, when available."""
    mark = getattr(error, "problem_mark", None)
    if mark is None:
        return None
    return f"line {mark.line + 1}, column {mark.column + 1}"
