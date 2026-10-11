"""Select a self-contained, standard OpenAPI document for Service.spec.

The entire spec is the parser/reference root, including after a DB round trip.
Only catalog identity uses an x-resource-ops extension; native keywords stay native.
"""
import copy
import re
from urllib.parse import quote, unquote

from catalog_common import VERSION, require
from openapi_catalog import (METHODS, dereference, endpoint_name, merged_parameters,
                             operations, pointer, version_family)
from swagger_adapter import SCHEMA_KEYS, scalar_schema, swagger_contract
from openapi_walk import SCHEMA_MAPS, SCHEMA_ARRAYS, SCHEMA_SINGLE

SCHEMA_VALUES = {'type', 'format', 'enum', 'const', 'default', 'required', 'minimum', 'maximum',
                 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf', 'minLength', 'maxLength',
                 'pattern', 'minItems', 'maxItems', 'uniqueItems', 'minContains', 'maxContains',
                 'minProperties', 'maxProperties', 'dependentRequired', 'nullable', 'readOnly',
                 'writeOnly', 'contentEncoding', 'contentMediaType', 'xml', '$schema', 'collectionFormat'}
DOC_KEYS = {'title', 'description', 'example', 'examples', 'externalDocs', 'deprecated', '$comment'}
PARAMETER_KEYS = {'name', 'in', 'required', 'style', 'explode', 'allowEmptyValue', 'allowReserved', 'collectionFormat'}


def schema_document(service):
    """Return the actual OpenAPI parser input; never rebuild or rebase its references."""
    return service['spec']


def escape(token):
    return token.replace('~', '~0').replace('/', '~1')


class Exporter:
    def __init__(self, document):
        self.document = document
        self.schemas = {}
        self.origins = {}

    def schema_ref(self, ref):
        pointer(self.document, ref)
        decoded = unquote(ref) if isinstance(ref, str) else ''
        prefix = '#/definitions/' if version_family(self.document) == '2.0' else '#/components/schemas/'
        require(decoded.startswith(prefix), f'{ref}: bundle schema references under components.schemas or definitions')
        parts = decoded[len(prefix):].split('/')
        require(all(not re.search(r'~(?![01])', part) for part in parts), f'invalid schema reference {ref}')
        name = parts[0].replace('~1', '/').replace('~0', '~')
        base = prefix + parts[0]
        require(name not in self.origins or self.origins[name] == base, f'conflicting schema name {name}')
        if name not in self.schemas:
            self.origins[name] = base
            self.schemas[name] = {}  # Register before following recursive references.
            registry = self.document
            for token in prefix[2:-1].split('/'):
                registry = registry[token]
            self.schemas[name] = self.schema(registry[name])
            if isinstance(registry[name], dict) and 'discriminator' in registry[name]:
                # Named allOf descendants are implicit discriminator targets even without a $ref
                # from the parent. Keep that semantic dependency when pruning components.
                pending, visited = [name], set()
                while pending:
                    parent = pending.pop()
                    if parent in visited:
                        continue
                    visited.add(parent)
                    parent_ref = prefix + escape(parent)
                    for child_name, child in registry.items():
                        if isinstance(child, dict) and any(isinstance(part, dict)
                                and isinstance(part.get('$ref'), str) and unquote(part['$ref']) == parent_ref
                                for part in child.get('allOf', [])):
                            self.schema_ref(prefix + quote(escape(child_name), safe='~'))
                            pending.append(child_name)
        result = prefix + quote('/'.join(parts), safe='/~')
        return result

    def schema(self, value):
        if isinstance(value, bool):
            return value
        require(isinstance(value, dict), 'schema must be an object or boolean')
        if '$schema' in value:
            family = version_family(self.document)
            allowed = {'https://json-schema.org/draft/2020-12/schema',
                       'https://spec.openapis.org/oas/3.1/dialect/base' if family == '3.1'
                       else 'https://spec.openapis.org/oas/3.2/dialect/2025-09-17'}
            require(family in ('3.1', '3.2') and value['$schema'] in allowed, 'unsupported schema dialect')
        result = {}
        for key, child in value.items():
            if key in DOC_KEYS or key.startswith('x-'):
                continue
            if key == '$ref':
                result[key] = self.schema_ref(child)
            elif key in SCHEMA_MAPS:
                result[key] = {name: self.schema(item) for name, item in child.items()}
            elif key in SCHEMA_ARRAYS:
                result[key] = [self.schema(item) for item in child]
            elif key in SCHEMA_SINGLE:
                result[key] = self.schema(child)
            elif key == 'items':
                result[key] = [self.schema(item) for item in child] if isinstance(child, list) else self.schema(child)
            elif key == 'dependencies':
                result[key] = {name: copy.deepcopy(item) if isinstance(item, list) else self.schema(item)
                               for name, item in child.items()}
            elif key == 'discriminator':
                result[key] = copy.deepcopy(child)
                if isinstance(child, dict):
                    mapping = result[key].get('mapping', {})
                    for name, ref in list(mapping.items()):
                        if not ref.startswith('#'):
                            prefix = '#/definitions/' if version_family(self.document) == '2.0' else '#/components/schemas/'
                            ref = prefix + escape(ref)
                        mapping[name] = self.schema_ref(ref)
            elif key in SCHEMA_VALUES:
                result[key] = copy.deepcopy(child)
            else:
                require(False, f'unsupported schema keyword {key!r}; do not silently discard validation constraints')
        return result

    def parameter(self, value):
        value = dereference(value, self.document)
        result = {key: copy.deepcopy(value[key]) for key in PARAMETER_KEYS if key in value}
        if version_family(self.document) == '2.0':
            result.update(self.schema({k: v for k, v in value.items() if k in SCHEMA_KEYS}))
        if 'schema' in value:
            result['schema'] = self.schema(value['schema'])
        if 'content' in value:
            result['content'] = self.content(value['content'])
        return result

    def encoding(self, value):
        result = {key: copy.deepcopy(value[key]) for key in ('contentType', 'style', 'explode', 'allowReserved') if key in value}
        if 'headers' in value:
            result['headers'] = {name: self.parameter(header) for name, header in value['headers'].items()}
        result.update(self.encodings(value))
        return result

    def encodings(self, value):
        result = {}
        if 'encoding' in value:
            result['encoding'] = {name: self.encoding(item) for name, item in value['encoding'].items()}
        if 'prefixEncoding' in value:
            result['prefixEncoding'] = [self.encoding(item) for item in value['prefixEncoding']]
        if 'itemEncoding' in value:
            result['itemEncoding'] = self.encoding(value['itemEncoding'])
        return result

    def content(self, value):
        result = {}
        for media, raw in value.items():
            payload = dereference(raw, self.document)
            selected = {}
            for key in ('schema', 'itemSchema'):
                if key in payload:
                    selected[key] = self.schema(payload[key])
            selected.update(self.encodings(payload))
            result[media] = selected
        return result

    def body(self, value):
        value = dereference(value, self.document)
        result = {'content': self.content(value['content'])}
        if 'required' in value:
            result['required'] = value['required']
        return result

    def response(self, value):
        value = dereference(value, self.document)
        # description is required through 3.1; 3.2 permits its omission.
        result = {key: copy.deepcopy(value[key]) for key in ('description',) if key in value}
        if 'schema' in value:
            result['schema'] = self.schema(value['schema'])
        if 'content' in value:
            result['content'] = self.content(value['content'])
        if 'headers' in value:
            result['headers'] = {name: self.parameter(header) for name, header in value['headers'].items()}
        return result


def select_servers(servers):
    return [{key: ({name: {k: copy.deepcopy(v) for k, v in variable.items() if k in ('default', 'enum')}
                    for name, variable in server[key].items()} if key == 'variables' else copy.deepcopy(server[key]))
             for key in ('url', 'variables') if key in server} for server in servers]


def export_service(document, organization, service):
    exporter = Exporter(document)
    family = version_family(document)
    version_key = 'swagger' if family == '2.0' else 'openapi'
    spec = {version_key: document[version_key],
            'info': {key: document['info'][key] for key in ('title', 'version')}, 'paths': {}}
    if family == '2.0':
        for key in ('host', 'basePath', 'schemes'):
            if key in document:
                spec[key] = copy.deepcopy(document[key])
    else:
        spec['servers'] = select_servers(document.get('servers') or [{'url': '/'}])
    if 'jsonSchemaDialect' in document:
        supported = {'3.1': 'https://spec.openapis.org/oas/3.1/dialect/base',
                     '3.2': 'https://spec.openapis.org/oas/3.2/dialect/2025-09-17'}
        require(document['jsonSchemaDialect'] == supported.get(family), 'unsupported jsonSchemaDialect; provide a supported dialect')
        spec['jsonSchemaDialect'] = document['jsonSchemaDialect']
    security_names = set()
    for path, method, item, operation in operations(document):
        metadata = {'name': endpoint_name(service, method, path), 'organization': organization}
        selected = {'x-resource-ops': {'metadata': metadata},
                    'parameters': [exporter.parameter(p) for p in merged_parameters(document, item, operation)],
                    'security': copy.deepcopy(operation.get('security', document.get('security', [])))}
        for key in ('summary', 'description'):
            if isinstance(operation.get(key), str) and operation[key].strip():
                selected['description'] = operation[key]
                break
        if 'responses' in operation:
            selected['responses'] = {status: exporter.response(response)
                                     for status, response in operation['responses'].items() if not status.startswith('x-')}
        if family == '2.0':
            for key in ('consumes', 'produces'):
                if key in operation or key in document:
                    selected[key] = copy.deepcopy(operation.get(key, document.get(key)))
            if 'schemes' in operation and operation['schemes'] != spec.get('schemes'):
                selected['schemes'] = copy.deepcopy(operation['schemes'])
        else:
            if 'requestBody' in operation:
                selected['requestBody'] = exporter.body(operation['requestBody'])
            servers = select_servers(operation.get('servers', item.get('servers', spec['servers'])) or [{'url': '/'}])
            if servers != spec['servers']:
                selected['servers'] = servers
        for requirement in selected['security']:
            security_names.update(requirement)
        target = spec['paths'].setdefault(path, {})
        if method in {m.upper() for m in METHODS} or method == 'QUERY':
            target[method.lower()] = selected
        else:
            target.setdefault('additionalOperations', {})[method] = selected

    definitions = document.get('securityDefinitions', {}) if family == '2.0' else document.get('components', {}).get('securitySchemes', {})
    schemes = {}
    for name in sorted(security_names):
        require(name in definitions, f'undefined security scheme {name}')
        scheme = dereference(definitions[name], document)
        schemes[name] = {k: copy.deepcopy(v) for k, v in scheme.items() if k not in DOC_KEYS and not k.startswith('x-')}
    for _, _, _, operation in operations(spec):
        for requirement in operation['security']:
            for name, scopes in requirement.items():
                scheme = schemes[name]
                if scheme.get('type') == 'oauth2':
                    allowed = set(scheme.get('scopes', {}))
                    for flow in scheme.get('flows', {}).values():
                        allowed.update(flow.get('scopes', {}))
                    require(set(scopes) <= allowed, f'unknown OAuth scope in {name}')
    if family == '2.0':
        if exporter.schemas:
            spec['definitions'] = exporter.schemas
        if schemes:
            spec['securityDefinitions'] = schemes
    else:
        components = {}
        if exporter.schemas:
            components['schemas'] = exporter.schemas
        if schemes:
            components['securitySchemes'] = schemes
        if components:
            spec['components'] = components
    return {'api-version': VERSION, 'kind': 'Service',
            'metadata': {'name': service, 'title': document['info']['title'], 'organization': organization}, 'spec': spec}


def endpoint_contract(document, item, operation):
    """Internal Page/history view. Stored Service.spec remains native OpenAPI/Swagger."""
    params = merged_parameters(document, item, operation)
    if version_family(document) == '2.0':
        adapted = swagger_contract(document, operation, params, lambda v: dereference(v, document))
        result = {key: copy.deepcopy(adapted[key]) for key in ('parameters', 'responses', 'servers')}
        # Retain the existing internal serialization view, not a custom stored spec.
        result['parameters'] = [{k: v for k, v in p.items() if k in PARAMETER_KEYS or k == 'schema'}
                                for p in result['parameters']]
        for response in result['responses'].values():
            response.pop('schema', None)
            if 'headers' in response:
                response['headers'] = {name: {'schema': scalar_schema(header),
                    **({'collectionFormat': header['collectionFormat']} if 'collectionFormat' in header else {})}
                    for name, header in response['headers'].items()}
        if 'requestBody' in adapted:
            body = adapted['requestBody']
            result['requestBody'] = {k: copy.deepcopy(v) for k, v in body.items() if not k.startswith('x-')}
            form = body.get('x-swagger-form-parameters')
            if form:
                result['requestBody']['form-serialization'] = {
                    p['name']: ({'collection-format': p['collectionFormat']} if 'collectionFormat' in p else {}) for p in form}
    else:
        result = {'parameters': copy.deepcopy(params), 'responses': copy.deepcopy(operation.get('responses', {})),
                  'servers': copy.deepcopy(operation.get('servers', item.get('servers', document.get('servers'))) or [{'url': '/'}])}
        if 'requestBody' in operation:
            result['requestBody'] = copy.deepcopy(operation['requestBody'])
    result['security'] = copy.deepcopy(operation.get('security', document.get('security', [])))
    return result


def validate_contract(service):
    """Validate spec directly with native libraries, then check catalog identity/selection."""
    from openapi_catalog import validate_openapi
    document = schema_document(service)
    validate_openapi(document, f"Service/{service['metadata']['name']}.spec")
    meta = service['metadata']
    expected = export_service(document, meta['organization'], meta['name'])
    require(meta['title'] == document['info']['title'], 'Service metadata.title differs from info.title')
    require(expected['spec'] == document,
            'generated metadata/endpoints or noncanonical OpenAPI selection differ from service identity')
