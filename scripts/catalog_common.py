"""Shared strict catalog I/O and validation helpers."""
import copy
import json
import re
from pathlib import Path
import yaml

VERSION = "resource-ops/v1"
NAME = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")

class CatalogError(ValueError):
    """Invalid source data; never a partially applicable snapshot."""


class StrictLoader(yaml.SafeLoader):
    pass


# Avoid YAML 1.1 treating on/off/yes/no or dates as booleans/datetimes.
StrictLoader.yaml_implicit_resolvers = copy.deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)
for first, resolvers in StrictLoader.yaml_implicit_resolvers.items():
    StrictLoader.yaml_implicit_resolvers[first] = [
        item for item in resolvers if item[0] not in {"tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp"}
    ]
StrictLoader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(true|false)$"), list("tf"))


def construct_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise CatalogError(f"line {key_node.start_mark.line + 1}: mapping keys must be strings; quote HTTP status codes")
        if key == "<<":
            raise CatalogError("YAML merge keys are not supported")
        if key in result:
            raise CatalogError(f"line {key_node.start_mark.line + 1}: duplicate YAML key {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)


def read_yaml(root: Path, relative: str):
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise CatalogError(f"{relative}: path escapes repository")
    if any(part.is_symlink() for part in [path, *path.parents] if part != root.parent):
        raise CatalogError(f"{relative}: symlinks are not supported")
    try:
        if path.stat().st_size > 33_554_432:
            raise CatalogError("file exceeds 32 MiB")
        text = path.read_text(encoding="utf-8")
        if "${" in text:
            raise CatalogError("Spring placeholders are forbidden in catalog data; use source: subject.*")
        if any(isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken)) for token in yaml.scan(text)):
            raise CatalogError("YAML anchors and aliases are not supported")
        value = yaml.load(text, Loader=StrictLoader)
        json.dumps(value, allow_nan=False)
        return value
    except (OSError, UnicodeError, yaml.YAMLError, TypeError, ValueError, RecursionError) as exc:
        raise CatalogError(f"{relative}: {exc}") from exc


def require(condition, message):
    if not condition:
        raise CatalogError(message)


def validate_shape(validator, document, location):
    errors = sorted(validator.iter_errors(document), key=lambda e: str(list(e.absolute_path)))
    if errors:
        error = errors[0]
        path = ".".join(map(str, error.absolute_path)) or "<root>"
        raise CatalogError(f"{location}: {path}: {error.message}")
