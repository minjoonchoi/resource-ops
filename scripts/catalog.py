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
from generate_services import files, generate
from history_selection import validate_history_selection
from openapi_catalog import TEMPLATE, dereference, extract_endpoints, validate_service
from page_rules import validate_page_rules

DIRECTORIES = {"Service": "services", "Action": "actions", "Page": "pages"}


def validate_action_plugins(action):
    """Validate statically knowable quorum limits; runtime resolves external memberships."""
    plugins = action["spec"].get("plugins", [])
    names = [plugin["name"] for plugin in plugins]
    require(len(names) == len(set(names)), f"Action/{action['metadata']['name']}: duplicate plugin name")
    for plugin in plugins:
        if plugin["name"] != "confirm":
            continue
        config = plugin["config"]
        pool = config["pool"]
        if not pool.get("organizations"):
            require(config["count"] <= len(pool["users"]),
                    f"Action/{action['metadata']['name']}: confirm count exceeds pool user nicknames")


def resolve_action_endpoint(action, resources, routes):
    """Match a direct Action specification against the registered service and route."""
    name, spec = action["metadata"]["name"], action["spec"]["endpoint"]
    location = f"actions/{name}.yaml (Action/{name})"
    service = spec["service"]
    registered = resources.get(("Service", service))
    require(registered is not None,
            f"{location}: spec.endpoint.service: unregistered service {service!r}")
    route = service, spec["method"], spec["path"]
    endpoint = routes.get(route)
    if endpoint is None:
        shape = TEMPLATE.sub("{}", spec["path"])
        similar = next((key[2] for key in routes if key[:2] == route[:2]
                        and TEMPLATE.sub("{}", key[2]) == shape), None)
        if similar is not None:
            raise CatalogError(f"{location}: spec.endpoint.path must exactly match {similar!r}, "
                               f"including path parameter names; got {spec['path']!r}")
        raise CatalogError(f"{location}: no registered Endpoint for service {service!r}: "
                           f"{spec['method']} {spec['path']}")
    return endpoint


def resolve_page_action(page_name, usage, action, endpoint, service):
    """Keep native contracts intact and attach validated Page execution policies."""
    location = f"Page/{page_name}.actions[{usage['action']}]"
    document = service["spec"]["openapi"]
    contract = endpoint["spec"]["operation"]
    validate_page_rules(usage, contract, document, location)
    raw_responses = {status: copy.deepcopy(dereference(response, document))
                     for status, response in contract.get("responses", {}).items() if not status.startswith("x-")}

    effective = {"service": {"name": service["metadata"]["name"], "servers": copy.deepcopy(contract["servers"])},
                 "method": endpoint["spec"]["method"], "path": endpoint["spec"]["path"],
                 "security": copy.deepcopy(contract["security"]),
                 "request": {"parameters": copy.deepcopy(contract["parameters"])}, "responses": raw_responses}
    if "request" in usage:
        effective["request"]["rules"] = copy.deepcopy(usage["request"])
    if "response" in usage:
        effective["response"] = copy.deepcopy(usage["response"])
    if "swagger-server" in contract:
        effective["service"]["swagger-server"] = copy.deepcopy(contract["swagger-server"])
    if "requestBody" in contract:
        effective["request"]["body"] = copy.deepcopy(dereference(contract["requestBody"], document))
    plugins = action["spec"].get("plugins", [])
    return {"page": page_name, "action": usage["action"], "endpoint": endpoint["metadata"]["name"],
            "plugins": copy.deepcopy(plugins),
            "effective": effective}


def build_snapshot(root: Path, verify_sources=True):
    root = root.resolve()
    if verify_sources:
        generate(root, "check")
    schema = json.loads((root / "schemas/catalog.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    marker = read_yaml(root, "resource-catalog.yaml")
    require(marker == {"resource-ops": {"api-version": VERSION}},
            "resource-catalog.yaml: Config Server marker must match the resource version")
    paths = sorted(path.relative_to(root).as_posix()
                   for directory in DIRECTORIES.values() for path in files(root, directory)
                   if path.suffix in {".yaml", ".yml"})
    require(paths, "at least one resource is required; an empty tree is not a delete-all request")
    resources = {}
    for path in paths:
        document = read_yaml(root, path)
        validate_shape(validator, document, path)
        kind, name = document["kind"], document["metadata"]["name"]
        require(kind in DIRECTORIES, f"{path}: unsupported resource kind {kind}")
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

    def link(source, relation, target_kind, target_name, usage=None):
        require((target_kind, target_name) in resources, f"{source}: missing reference {target_kind}/{target_name}")
        edge = {"from": source, "type": relation, "to": f"{target_kind}/{target_name}"}
        if usage is not None:
            for key in ("request", "response"):
                if key in usage:
                    edge[key] = copy.deepcopy(usage[key])
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
                link(source, "uses", "Action", action, usage)
            if "parent" in spec:
                link(source, "childOf", "Page", spec["parent"])

    # Resolve every Action only after the complete service/Endpoint registry is valid.
    action_endpoints = {}
    for (kind, name), resource in sorted(resources.items()):
        if kind == "Action":
            validate_action_plugins(resource)
            endpoint = resolve_action_endpoint(resource, resources, routes)
            validate_history_selection(resource, endpoint, resources['Service', endpoint['spec']['service']])
            action_endpoints[name] = endpoint
            link(f"Action/{name}", "invokes", "Endpoint", endpoint["metadata"]["name"])

    page_action_usages = []
    for (kind, name), resource in sorted(resources.items()):
        if kind == "Page":
            for usage in resource["spec"]["actions"]:
                action = resources["Action", usage["action"]]
                endpoint = action_endpoints[usage["action"]]
                page_action_usages.append(resolve_page_action(
                    name, usage, action, endpoint, resources["Service", action["spec"]["endpoint"]["service"]]))
            visited, current = set(), name
            while current is not None:
                require(current not in visited, f"Page/{name}: parent cycle through {current}")
                visited.add(current)
                current = resources["Page", current]["spec"].get("parent")

    snapshot = {
        "api-version": VERSION,
        "kind": "CatalogSnapshot",
        "resources": [resources[key] for key in sorted(resources)],
        "relations": sorted(relations, key=lambda edge: (edge["from"], edge["type"], edge["to"])),
        "page-action-usages": sorted(page_action_usages, key=lambda usage: (usage["page"], usage["action"])),
    }
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    snapshot["content-sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
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
        print(f"content-sha256: {snapshot['content-sha256']}")
        return 0
    except (CatalogError, OSError, ValueError, RecursionError, SchemaError) as exc:
        print(f"Catalog invalid: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
