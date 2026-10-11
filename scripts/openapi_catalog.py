"""Version-aware Swagger 2.0 / OpenAPI 3.0, 3.1, 3.2 catalog extraction."""
import copy
import re
from urllib.parse import unquote

from jsonschema import Draft4Validator
from openapi_spec_validator import (OpenAPIV2SpecValidator, OpenAPIV30SpecValidator,
                                    OpenAPIV31SpecValidator, OpenAPIV32SpecValidator)
from openapi_schema_validator import OAS30WriteValidator, OAS31Validator, OAS32Validator
from jsonschema_path import SchemaPath
from jsonschema_path.accessors import SchemaAccessor
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from catalog_common import CatalogError, NAME, VERSION, require
from openapi_walk import nodes

METHODS = ('get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace')
TEMPLATE = re.compile(r'\{([^{}]+)\}')


class PatchCompatibleOpenAPIV30SpecValidator(OpenAPIV30SpecValidator):
    # The bundled 3.0 meta-schema limits the patch component to one digit.
    # OAS §4.1 defines compatibility by major.minor; leave the input untouched
    # and widen only this version string pattern, retaining all structural checks.
    _schema = copy.deepcopy(OpenAPIV30SpecValidator.schema_validator.schema)
    _schema['properties']['openapi']['pattern'] = r'^3\.0\.\d+$'
    schema_validator = OpenAPIV30SpecValidator.schema_validator.evolve(schema=_schema)


SPEC_VALIDATORS = {'2.0': OpenAPIV2SpecValidator, '3.0': PatchCompatibleOpenAPIV30SpecValidator,
                   '3.1': OpenAPIV31SpecValidator, '3.2': OpenAPIV32SpecValidator}
VALUE_VALIDATORS = {'2.0': Draft4Validator, '3.0': OAS30WriteValidator,
                    '3.1': OAS31Validator, '3.2': OAS32Validator}


def validate_offline(document, cls):
    # jsonschema-path otherwise follows a literal default object's "$ref" as a schema ref.
    schema_ids = {id(value) for kind, value in nodes(document) if kind in ('schema', 'parameter')}

    class LiteralSafePath(SchemaPath):
        def read_value(self):
            if self.parts and self.parts[-1] == 'default':
                parent = self.parent.read_value()
                if id(parent) in schema_ids:
                    return parent['default']
            return super().read_value()

    # A closed registry has no retrieval callback: neither network nor local files can be fetched,
    # even if the upstream validator starts following another kind of reference in a future release.
    registry = Registry().with_resource('', Resource(document, DRAFT202012))
    path = LiteralSafePath(SchemaAccessor(document, registry.resolver()))
    cls(path).validate()


def version_family(document, location='OpenAPI'):
    require(isinstance(document, dict), f'{location}: OpenAPI document must be an object')
    require(not ('swagger' in document and 'openapi' in document),
            f'{location}: declare either swagger or openapi, not both')
    if document.get('swagger') == '2.0':
        return '2.0'
    version = document.get('openapi')
    match = re.fullmatch(r'(3\.[012])\.\d+', version) if isinstance(version, str) else None
    require(match is not None,
            f'{location}: unsupported or missing spec version {document.get("swagger", version)!r}; '
            'supported: Swagger 2.0, OpenAPI 3.0.x/3.1.x/3.2.x. '
            'Check docs/openapi-compatibility.md and the official versioned specification; do not rewrite the version.')
    return match.group(1)


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
        if version_family(document) in ('3.1', '3.2') and len(value) > 1:
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
    name = parameter['name']
    return parameter['in'], name.lower() if parameter['in'] == 'header' else name


def parameters_by_key(parameters, location):
    result = {}
    for param in parameters:
        key = parameter_key(param)
        require(key not in result, f'{location}: duplicate parameter {key}')
        result[key] = param
    return result


def endpoint_name(service, method, path):
    # Stable across documentation/operationId edits and independent of upstream naming conventions.
    # Treat the complete string as an opaque identity; never split it on dots.
    return f'{service}.{method}.{path}'


def operations(document):
    family = version_family(document)
    for path, item in sorted(document['paths'].items()):
        if path.startswith('x-'):
            continue
        item = dereference(item, document)
        for method in (*METHODS, 'query') if family == '3.2' else METHODS:
            if method in item:
                yield path, method.upper(), item, item[method]
        if family == '3.2':
            for method, operation in sorted(item.get('additionalOperations', {}).items()):
                yield path, method, item, operation


def validate_openapi(document, location):
    family = version_family(document, location)
    # Preflight before the third-party validator: it must never fetch remote or local files.
    for kind, value in nodes(document):
        if kind == 'schema':
            require(not any(k in value for k in ('$id', '$anchor', '$dynamicRef', '$dynamicAnchor')),
                    f'{location}: bundle schemas using document-local JSON Pointers (no $id/anchors/dynamic refs)')
        if '$ref' in value:
            pointer(document, value['$ref'])
    try:
        validate_offline(document, cls=SPEC_VALIDATORS[family])
    except Exception as exc:
        message = getattr(exc, 'message', None) or str(exc).splitlines()[0]
        path = '/'.join(map(str, getattr(exc, 'absolute_path', [])))
        raise CatalogError(f'{location}: invalid OpenAPI {path}: {message}') from exc
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
    from service_contract import export_service, validate_contract
    result = export_service(document, organization, service)
    validate_contract(result)
    return result


def validate_service(service):
    from service_contract import validate_contract
    meta = service['metadata']
    require('/' not in meta['organization'] and meta['organization'] not in ('.', '..'), 'invalid organization directory')
    validate_contract(service)


def extract_endpoints(service):
    from service_contract import endpoint_contract
    for endpoint in service['spec']['endpoints']:
        yield {'api-version': VERSION, 'kind': 'Endpoint',
               'metadata': copy.deepcopy(endpoint['metadata']),
               'spec': {'service': service['metadata']['name'], 'method': endpoint['method'],
                        'path': endpoint['path'], 'operation': endpoint_contract(service, endpoint)}}


def schema_accepts(document, schema, value):
    cls = VALUE_VALIDATORS[version_family(document)]
    # Use the caller's schema context (source document or reduced Service contract).
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
