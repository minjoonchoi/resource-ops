#!/usr/bin/env python3
"""Validate source YAML and export a deterministic, DB-neutral catalog snapshot."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

VERSION = "resource-ops/v1"
DIRECTORIES = {"Server": "servers", "Endpoint": "endpoints", "Action": "actions", "Page": "pages"}
TEMPLATE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
RESERVED_HEADERS = {"authorization", "proxy-authorization", "host", "cookie"}


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
        if path.stat().st_size > 1_048_576:
            raise CatalogError("file exceeds 1 MiB")
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


def parameter_key(parameter):
    name = parameter["name"].lower() if parameter["in"] == "header" else parameter["name"]
    return parameter["in"], name


def parameters_by_key(parameters, location):
    result = {}
    for parameter in parameters:
        key = parameter_key(parameter)
        require(key not in result, f"{location}: duplicate parameter {key}")
        require(key[0] != "header" or key[1] not in RESERVED_HEADERS,
                f"{location}: transport/auth header {key[1]} cannot be a catalog parameter")
        result[key] = parameter
    return result


def validate_value_schema(schema, location):
    """Check semantics beyond the structural subset defined in catalog.schema.json."""
    Draft202012Validator.check_schema(schema)
    for minimum, maximum in (("minimum", "maximum"), ("minLength", "maxLength"), ("minItems", "maxItems")):
        if minimum in schema and maximum in schema:
            require(schema[minimum] <= schema[maximum], f"{location}: {minimum} exceeds {maximum}")
    if schema["type"] == "object":
        require(set(schema.get("required", [])) <= set(schema["properties"]),
                f"{location}: required property is not declared")
        for name, child in schema["properties"].items():
            validate_value_schema(child, f"{location}.{name}")
    if schema["type"] == "array":
        validate_value_schema(schema["items"], f"{location}[]")
    # Catch impossible enum/const values (e.g. type: integer, const: twenty).
    base = {key: value for key, value in schema.items() if key not in {"enum", "const"}}
    value_validator = Draft202012Validator(base)
    for value in schema.get("enum", []):
        require(value_validator.is_valid(value), f"{location}: enum value violates its schema")
    if "const" in schema:
        require(value_validator.is_valid(schema["const"]), f"{location}: const violates its schema")
        require("enum" not in schema or schema["const"] in schema["enum"], f"{location}: const is not in enum")


def leaf_schema(schema, pointer, location):
    """JSON Pointer escaping with '*' exclusively for array items; leaves only."""
    if pointer:
        require(pointer.startswith("/"), f"{location}: invalid field path {pointer}")
        for token in pointer[1:].split("/"):
            require(not re.search(r"~(?![01])", token), f"{location}: invalid JSON Pointer escape in {pointer}")
            token = token.replace("~1", "/").replace("~0", "~")
            if schema["type"] == "array" and token == "*":
                schema = schema["items"]
            elif schema["type"] == "object" and token in schema["properties"]:
                schema = schema["properties"][token]
            else:
                raise CatalogError(f"{location}: field {pointer!r} does not exist")
    require(schema["type"] not in {"object", "array"},
            f"{location}: field {pointer!r} selects a container; select individual leaves")
    return schema


def validate_server(resource):
    location = f"Server/{resource['metadata']['name']}"
    base_url = resource["spec"]["baseUrl"]
    url = urlsplit(base_url)
    try:
        port = url.port
    except ValueError as exc:
        raise CatalogError(f"{location}: invalid baseUrl port") from exc
    require(bool(url.hostname) and url.username is None and url.password is None
            and not url.query and not url.fragment and not base_url.endswith("/")
            and (port is None or port > 0),
            f"{location}: baseUrl needs a host, no credentials/query/fragment/trailing slash")


def validate_endpoint(resource):
    location = f"Endpoint/{resource['metadata']['name']}"
    spec = resource["spec"]
    params = parameters_by_key(spec["request"]["parameters"], location)
    placeholders = TEMPLATE.findall(spec["path"])
    remaining = TEMPLATE.sub("", spec["path"])
    require("{" not in remaining and "}" not in remaining, f"{location}: malformed path template")
    require(len(placeholders) == len(set(placeholders)), f"{location}: repeated path placeholder")
    path_parameters = {name for (place, name) in params if place == "path"}
    require(set(placeholders) == path_parameters, f"{location}: path placeholders and path parameters differ")
    for key, parameter in params.items():
        require(key[0] != "path" or parameter["required"], f"{location}: path parameter must be required")
        require(parameter["schema"]["type"] not in {"object", "array", "null"},
                f"{location}: v1 parameters must be non-null scalars; use a JSON body for objects")
        validate_value_schema(parameter["schema"], f"{location}.request.{key}")
    if "body" in spec["request"]:
        validate_value_schema(spec["request"]["body"]["schema"], f"{location}.request.body")
    for status, response in spec["responses"].items():
        validate_value_schema(response["schema"], f"{location}.responses.{status}")


def resolve_page_action(page_name, usage, endpoint):
    """Validate sparse overrides and resolve an independent Page/Action contract."""
    location = f"Page/{page_name}.actions[{usage['action']}]"
    overrides, contract = usage.get("overrides", {}), endpoint["spec"]
    available = parameters_by_key(contract["request"]["parameters"], location)
    changed = parameters_by_key(overrides.get("request", {}).get("parameters", []), location)
    require(set(changed) <= set(available), f"{location}: override references an unknown endpoint parameter")
    for key, binding in changed.items():
        schema = available[key]["schema"]
        if "value" in binding:
            require(Draft202012Validator(schema).is_valid(binding["value"]),
                    f"{location}: constant for {key} violates endpoint schema")
        else:
            require(schema["type"] == "string", f"{location}: subject sources require a string parameter")
    responses = overrides.get("responses", {})
    require(set(responses) <= set(contract["responses"]),
            f"{location}: override references an unknown endpoint response status")
    for status, projection in responses.items():
        for pointer in projection["fields"]:
            leaf_schema(contract["responses"][status]["schema"], pointer, f"{location}.responses.{status}")

    effective = copy.deepcopy(contract)
    for parameter in effective["request"]["parameters"]:
        binding = changed.get(parameter_key(parameter), {"source": "input"})
        # Preserve Endpoint names, types and required flags; only the value source changes.
        if "value" in binding:
            parameter["value"] = copy.deepcopy(binding["value"])
        else:
            parameter["source"] = binding["source"]
    if "body" in effective["request"]:
        effective["request"]["body"]["source"] = "input"
    for status, projection in responses.items():
        # An explicit fields array replaces the projection; never union it with all fields.
        effective["responses"][status]["fields"] = copy.deepcopy(projection["fields"])
    return {
        "page": page_name,
        "action": usage["action"],
        "endpoint": endpoint["metadata"]["name"],
        "effective": effective,
    }


def build_snapshot(root: Path):
    root = root.resolve()
    schema = json.loads((root / "schemas/catalog.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    manifest = read_yaml(root, "catalog/manifest.yaml")
    validate_shape(validator, manifest, "catalog/manifest.yaml")
    require(manifest["kind"] == "Catalog", "catalog/manifest.yaml must have kind Catalog")
    marker = read_yaml(root, "resource-catalog.yaml")
    require(marker == {"resourceOps": {"manifest": "catalog/manifest.yaml", "apiVersion": VERSION}},
            "resource-catalog.yaml: Config Server marker must match the catalog path and version")
    paths = manifest["spec"]["resources"]
    expected = set(paths) | {"catalog/manifest.yaml"}
    discovered = {str(path.relative_to(root)) for path in (root / "catalog").rglob("*")
                  if path.suffix in {".yaml", ".yml"}}
    require(discovered == expected,
            f"manifest mismatch: unlisted={sorted(discovered - expected)}, missing={sorted(expected - discovered)}")
    resources = {}
    for path in paths:
        document = read_yaml(root, path)
        validate_shape(validator, document, path)
        kind, name = document["kind"], document["metadata"]["name"]
        require(kind in DIRECTORIES, f"{path}: Catalog cannot be nested")
        require(not name.endswith("-default"), f"{path}: -default suffix is reserved by Config Server profile resolution")
        require(path == f"catalog/{DIRECTORIES[kind]}/{name}.yaml", f"{path}: kind/name must match directory/filename")
        key = kind, name
        require(key not in resources, f"{path}: duplicate identity {key}")
        resources[key] = document

    relations = []

    def link(source, relation, target_kind, target_name, overrides=None):
        require((target_kind, target_name) in resources, f"{source}: missing reference {target_kind}/{target_name}")
        edge = {"from": source, "type": relation, "to": f"{target_kind}/{target_name}"}
        if overrides is not None:
            edge["overrides"] = copy.deepcopy(overrides)
        relations.append(edge)

    routes = set()
    page_routes = set()
    for (kind, name), resource in sorted(resources.items()):
        spec = resource["spec"]
        source = f"{kind}/{name}"
        if kind == "Server":
            validate_server(resource)
        elif kind == "Endpoint":
            link(source, "providedBy", "Server", spec["server"])
            validate_endpoint(resource)
            route = spec["server"], spec["method"], TEMPLATE.sub("{}", spec["path"])
            require(route not in routes, f"{source}: duplicate server/method/path route {route}")
            routes.add(route)
        elif kind == "Action":
            link(source, "invokes", "Endpoint", spec["endpoint"])
        elif kind == "Page":
            require(spec["path"] not in page_routes, f"{source}: duplicate page path")
            page_routes.add(spec["path"])
            actions = set()
            for usage in spec["actions"]:
                action = usage["action"]
                require(action not in actions, f"{source}: duplicate action usage {action}")
                actions.add(action)
                link(source, "uses", "Action", action, usage.get("overrides"))
            if "parent" in spec:
                link(source, "childOf", "Page", spec["parent"])

    page_action_usages = []
    for (kind, name), resource in sorted(resources.items()):
        if kind == "Page":
            for usage in resource["spec"]["actions"]:
                action = resources["Action", usage["action"]]
                endpoint = resources["Endpoint", action["spec"]["endpoint"]]
                page_action_usages.append(resolve_page_action(name, usage, endpoint))
            visited, current = set(), name
            while current is not None:
                require(current not in visited, f"Page/{name}: parent cycle through {current}")
                visited.add(current)
                current = resources["Page", current]["spec"].get("parent")

    snapshot = {
        "apiVersion": VERSION,
        "kind": "CatalogSnapshot",
        "metadata": manifest["metadata"],
        "resources": [resources[key] for key in sorted(resources)],
        "relations": sorted(relations, key=lambda edge: (edge["from"], edge["type"], edge["to"])),
        "pageActionUsages": sorted(page_action_usages, key=lambda usage: (usage["page"], usage["action"])),
    }
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    snapshot["contentSha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--snapshot", type=Path, help="write a normalized snapshot only after all checks pass")
    args = parser.parse_args()
    try:
        snapshot = build_snapshot(args.root)
        if args.snapshot:
            args.snapshot.parent.mkdir(parents=True, exist_ok=True)
            args.snapshot.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Catalog valid: {len(snapshot['resources'])} resources, {len(snapshot['relations'])} relations")
        print(f"contentSha256: {snapshot['contentSha256']}")
        return 0
    except (CatalogError, OSError, ValueError, RecursionError, SchemaError) as exc:
        print(f"Catalog invalid: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
