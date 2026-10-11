#!/usr/bin/env python3
"""Validate generated services and authored actions/pages; export an atomic catalog snapshot."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from catalog_common import CatalogError, VERSION, read_yaml, require, validate_shape
from generate_services import generate
from openapi_catalog import (TEMPLATE, dereference, extract_endpoints, leaf_schema, parameter_key,
                             parameters_by_key, schema_accepts, validate_service)

DIRECTORIES = {"Service": "services", "Action": "actions", "Page": "pages"}


def resolve_action_endpoint(action, resources, routes):
    """Match a direct Action specification against the registered service and route."""
    name, spec = action["metadata"]["name"], action["spec"]
    location = f"actions/{name}.yaml (Action/{name})"
    service = spec["service"]
    registered = resources.get(("Service", service))
    require(registered is not None,
            f"{location}: spec.service: unregistered service {service!r}")
    route = service, spec["method"], spec["path"]
    endpoint = routes.get(route)
    if endpoint is None:
        shape = TEMPLATE.sub("{}", spec["path"])
        similar = next((key[2] for key in routes if key[:2] == route[:2]
                        and TEMPLATE.sub("{}", key[2]) == shape), None)
        if similar is not None:
            raise CatalogError(f"{location}: spec.path must exactly match {similar!r}, "
                               f"including path parameter names; got {spec['path']!r}")
        raise CatalogError(f"{location}: no registered Endpoint for service {service!r}: "
                           f"{spec['method']} {spec['path']}")
    return endpoint


def resolve_page_action(page_name, usage, action, endpoint, service):
    """Apply sparse Page overrides; all OpenAPI schema refs remain rooted at Service.spec.openapi."""
    location = f"Page/{page_name}.actions[{usage['action']}]"
    document = service["spec"]["openapi"]
    overrides, contract = usage.get("overrides", {}), endpoint["spec"]["operation"]
    available = parameters_by_key(contract["parameters"], location)
    changed = parameters_by_key(overrides.get("request", {}).get("parameters", []), location)
    require(set(changed) <= set(available), f"{location}: override references an unknown endpoint parameter")
    for key, binding in changed.items():
        require("schema" in available[key], f"{location}: parameter content overrides are unsupported")
        require(key[0] != "header" or key[1] not in {"authorization", "proxy-authorization", "host", "cookie"},
                f"{location}: transport/auth headers cannot be overridden")
        schema = available[key]["schema"]
        if "value" in binding:
            require(schema_accepts(document, schema, binding["value"]),
                    f"{location}: constant for {key} violates endpoint schema")
        else:
            resolved = dereference(schema, document)
            require(isinstance(resolved, dict) and resolved.get("type") == "string",
                    f"{location}: subject sources require a string parameter")
    raw_responses = {status: copy.deepcopy(dereference(response, document))
                     for status, response in contract["responses"].items() if not status.startswith("x-")}
    responses = overrides.get("responses", {})
    require(set(responses) <= set(raw_responses), f"{location}: override references an unknown endpoint response status")
    for status, projection in responses.items():
        content = raw_responses[status].get("content", {})
        require(len(content) == 1, f"{location}: response projection needs exactly one JSON media type")
        media, payload = next(iter(content.items()))
        require(media == "application/json" or (media.startswith("application/") and media.endswith("+json")),
                f"{location}: response projection needs JSON content")
        require("schema" in payload, f"{location}: response projection needs a schema")
        for field in projection["fields"]:
            leaf_schema(payload["schema"], field, document, f"{location}.responses.{status}")
        raw_responses[status]["fields"] = copy.deepcopy(projection["fields"])

    effective = {"service": {"name": service["metadata"]["name"], "servers": copy.deepcopy(contract["servers"])},
                 "method": endpoint["spec"]["method"], "path": endpoint["spec"]["path"],
                 "security": copy.deepcopy(contract["security"]),
                 "request": {"parameters": copy.deepcopy(contract["parameters"])}, "responses": raw_responses}
    for parameter in effective["request"]["parameters"]:
        binding = changed.get(parameter_key(parameter), {"source": "input"})
        if "value" in binding:
            parameter["value"] = copy.deepcopy(binding["value"])
        else:
            parameter["source"] = binding["source"]
    if "requestBody" in contract:
        effective["request"]["body"] = copy.deepcopy(dereference(contract["requestBody"], document))
        effective["request"]["body"]["source"] = "input"
    return {"page": page_name, "action": usage["action"], "endpoint": endpoint["metadata"]["name"], "effective": effective}


def build_snapshot(root: Path, verify_sources=True):
    root = root.resolve()
    if verify_sources:
        generate(root, "check")
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
    discovered = {str(path.relative_to(root)) for directory in (*DIRECTORIES.values(), "catalog") for path in (root / directory).rglob("*")
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
        require(path == f"{DIRECTORIES[kind]}/{name}.yaml", f"{path}: kind/name must match directory/filename")
        key = kind, name
        require(key not in resources, f"{path}: duplicate identity {key}")
        resources[key] = document

    for (kind, _), resource in list(resources.items()):
        if kind == "Service":
            validate_service(resource)
            for endpoint in extract_endpoints(resource):
                key = "Endpoint", endpoint["metadata"]["name"]
                require(key not in resources, f"duplicate endpoint identity {key}")
                resources[key] = endpoint

    relations = []

    def link(source, relation, target_kind, target_name, overrides=None):
        require((target_kind, target_name) in resources, f"{source}: missing reference {target_kind}/{target_name}")
        edge = {"from": source, "type": relation, "to": f"{target_kind}/{target_name}"}
        if overrides is not None:
            edge["overrides"] = copy.deepcopy(overrides)
        relations.append(edge)

    routes = {}
    route_shapes = set()
    page_routes = set()
    for (kind, name), resource in sorted(resources.items()):
        spec = resource["spec"]
        source = f"{kind}/{name}"
        if kind == "Endpoint":
            link(source, "providedBy", "Service", spec["service"])
            shape = spec["service"], spec["method"], TEMPLATE.sub("{}", spec["path"])
            require(shape not in route_shapes, f"{source}: duplicate service/method/path route {shape}")
            route_shapes.add(shape)
            routes[spec["service"], spec["method"], spec["path"]] = resource
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

    # Resolve every Action only after the complete service/Endpoint registry is valid.
    action_endpoints = {}
    for (kind, name), resource in sorted(resources.items()):
        if kind == "Action":
            endpoint = resolve_action_endpoint(resource, resources, routes)
            action_endpoints[name] = endpoint
            link(f"Action/{name}", "invokes", "Endpoint", endpoint["metadata"]["name"])

    page_action_usages = []
    for (kind, name), resource in sorted(resources.items()):
        if kind == "Page":
            for usage in resource["spec"]["actions"]:
                action = resources["Action", usage["action"]]
                endpoint = action_endpoints[usage["action"]]
                page_action_usages.append(resolve_page_action(
                    name, usage, action, endpoint, resources["Service", action["spec"]["service"]]))
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
    parser.add_argument("--from-generated", action="store_true", help="consumer: validate downloaded YAML without OpenAPI JSON sources")
    parser.add_argument("--snapshot", type=Path, help="write a normalized snapshot only after all checks pass")
    args = parser.parse_args()
    try:
        snapshot = build_snapshot(args.root, verify_sources=not args.from_generated)
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
