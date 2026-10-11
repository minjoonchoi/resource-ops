"""Offline OpenAPI 3.0/3.1 validation and catalog extraction; preserve native contracts."""
import copy
import hashlib
import json
import re
from urllib.parse import unquote

from openapi_spec_validator import validate
from openapi_schema_validator import OAS30WriteValidator, OAS31Validator

from catalog_common import CatalogError, NAME, VERSION, require

METHODS = ('get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace')
TEMPLATE = re.compile(r'\{([^{}]+)\}')


def pointer(document, ref):
    require(isinstance(ref, str) and (ref == '#' or ref.startswith('#/')),
            f'only document-local $ref pointers are supported; bundle external references first: {ref!r}')
    value = document
    if ref == '#':
        return value
    try:
        for part in unquote(ref[2:]).split('/'):
            require(not re.search(r'~(?![01])', part), f'invalid reference escape: {ref}')
            part = part.replace('~1', '/').replace('~0', '~')
            value = value[int(part)] if isinstance(value, list) else value[part]
        return value
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise CatalogError(f'unresolved $ref: {ref}') from exc


def dereference(value, document):
    seen = set()
    while isinstance(value, dict) and '$ref' in value:
        ref = value['$ref']
        require(ref not in seen, f'cyclic reference object: {ref}')
        seen.add(ref)
        target = pointer(document, ref)
        if document['openapi'].startswith('3.1.') and len(value) > 1:
            # Schema siblings are constraints, not replacements. Projection cannot ignore them.
            siblings = {k: v for k, v in value.items() if k != '$ref'}
            require(not (set(siblings) - {'summary', 'description'}),
                    'override of a $ref with constraint siblings is unsupported')
            require(isinstance(target, dict), "override of a boolean $ref with siblings is unsupported")
            value = {**target, **siblings}
        else:
            value = target
    return value


def parameter_key(parameter):
    return parameter['in'], parameter['name'].lower() if parameter['in'] == 'header' else parameter['name']


def parameters_by_key(parameters, location):
    result = {}
    for param in parameters:
        key = parameter_key(param)
        require(key not in result, f'{location}: duplicate parameter {key}')
        result[key] = param
    return result


def endpoint_name(service, method, path):
    # Stable across documentation/operationId edits and independent of upstream naming conventions.
    digest = hashlib.sha256(path.encode('utf-8')).hexdigest()[:16]
    return f'{service}.{method.lower()}.{digest}'


def operations(document):
    for path, item in sorted(document['paths'].items()):
        if path.startswith('x-'):
            continue
        item = dereference(item, document)
        for method in METHODS:
            if method in item:
                yield path, method, item, item[method]


def validate_openapi(document, location):
    require(isinstance(document, dict) and re.fullmatch(r'3\.(0|1)\.\d+', str(document.get('openapi', ''))),
            f'{location}: supported OpenAPI versions are 3.0.x and 3.1.x')
    # Preflight before the third-party validator: it must never fetch remote or local files.
    def visit(value):
        if isinstance(value, dict):
            require(not any(k in value for k in ('$id', '$anchor', '$dynamicRef', '$dynamicAnchor')),
                    f'{location}: bundle schemas using document-local JSON Pointers (no $id/anchors/dynamic refs)')
            if '$ref' in value:
                pointer(document, value['$ref'])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(document)
    try:
        validate(document)
    except Exception as exc:
        raise CatalogError(f'{location}: invalid OpenAPI: {exc}') from exc
    require(isinstance(document.get('paths'), dict), f'{location}: paths is required for an endpoint catalog')
    shapes = set()
    for path, method, item, operation in operations(document):
        shape = method, TEMPLATE.sub('{}', path)
        require(shape not in shapes, f'{location}: duplicate method/path route {method.upper()} {path}')
        shapes.add(shape)
        placeholders = TEMPLATE.findall(path)
        require(len(placeholders) == len(set(placeholders)) and '{' not in TEMPLATE.sub('', path)
                and '}' not in TEMPLATE.sub('', path), f'{location}: malformed path template {path}')
        params = merged_parameters(document, item, operation)
        names = {p['name'] for p in params if p['in'] == 'path'}
        require(names == set(placeholders), f'{location}: path placeholders and path parameters differ: {path}')
    require(shapes, f'{location}: at least one endpoint is required')


def merged_parameters(document, item, operation):
    path_params = [dereference(p, document) for p in item.get('parameters', [])]
    op_params = [dereference(p, document) for p in operation.get('parameters', [])]
    combined = parameters_by_key(path_params, 'path parameters')
    combined.update(parameters_by_key(op_params, 'operation parameters'))
    return list(combined.values())


def make_service(document, organization, service, source):
    require(NAME.fullmatch(service) and len(service) <= 128 and not service.endswith('-default'),
            f'{source}: invalid service filename/name (or reserved -default suffix): {service}')
    validate_openapi(document, source)
    endpoints = []
    for path, method, _, operation in operations(document):
        endpoints.append({
            'metadata': {'name': endpoint_name(service, method, path), 'organization': organization,
                         'title': operation.get('summary') or operation.get('operationId') or f'{method.upper()} {path}'},
            'method': method.upper(), 'path': path,
        })
    return {
        'apiVersion': VERSION, 'kind': 'Service',
        'metadata': {'name': service, 'organization': organization, 'title': document['info']['title']},
        'spec': {'source': source, 'endpoints': endpoints, 'openapi': copy.deepcopy(document)},
    }


def validate_service(service):
    spec, meta = service['spec'], service['metadata']
    expected_source = f"openapi/{meta['organization']}/{meta['name']}.json"
    require(spec['source'] == expected_source, 'Service source must match metadata.organization/name')
    require('/' not in meta['organization'] and meta['organization'] not in ('.', '..'), 'invalid organization directory')
    expected = make_service(spec['openapi'], meta['organization'], meta['name'], expected_source)
    require(service == expected, f"Service/{meta['name']}: generated metadata/endpoints differ from OpenAPI")


def extract_endpoints(service):
    document, name = service['spec']['openapi'], service['metadata']['name']
    index = {(e['method'], e['path']): e for e in service['spec']['endpoints']}
    for path, method, item, operation in operations(document):
        contract = copy.deepcopy(operation)
        contract['parameters'] = copy.deepcopy(merged_parameters(document, item, operation))
        contract['servers'] = copy.deepcopy(operation.get('servers', item.get('servers', document.get('servers', [{'url': '/'}]))))
        contract['security'] = copy.deepcopy(operation.get('security', document.get('security', [])))
        yield {'apiVersion': VERSION, 'kind': 'Endpoint',
               'metadata': copy.deepcopy(index[method.upper(), path]['metadata']),
               'spec': {'service': name, 'method': method.upper(), 'path': path, 'operation': contract}}


def schema_accepts(document, schema, value):
    cls = OAS30WriteValidator if document['openapi'].startswith('3.0.') else OAS31Validator
    # Keep all local refs rooted at the original document without network resolution.
    root = {**document, 'x-catalog-validation-schema': schema, '$ref': '#/x-catalog-validation-schema'}
    try:
        return cls(root, format_checker=cls.FORMAT_CHECKER).is_valid(value)
    except Exception as exc:
        raise CatalogError(f'cannot validate override against OpenAPI schema: {exc}') from exc


def leaf_schema(schema, field, document, location):
    tokens = field[1:].split('/') if field else []
    require(not field or field.startswith('/'), f'{location}: invalid field path {field}')
    for index in range(len(tokens) + 1):
        schema = dereference(schema, document)
        require(isinstance(schema, dict) and not any(k in schema for k in ('allOf', 'oneOf', 'anyOf', 'not', 'if')),
                f'{location}: projection needs an unambiguous schema; composition/boolean schemas are unsupported')
        if index == len(tokens):
            types = schema.get('type', [])
            types = [types] if isinstance(types, str) else types
            require(types and not set(types) & {'object', 'array'},
                    f'{location}: field {field!r} selects a container or untyped value; select individual leaves')
            return schema
        token = tokens[index]
        require(not re.search(r'~(?![01])', token), f'{location}: invalid JSON Pointer escape')
        token = token.replace('~1', '/').replace('~0', '~')
        if schema.get('type') == 'array' and token == '*':
            schema = schema.get('items', {})
        elif token in schema.get('properties', {}):
            schema = schema['properties'][token]
        else:
            raise CatalogError(f'{location}: field {field!r} does not exist')
