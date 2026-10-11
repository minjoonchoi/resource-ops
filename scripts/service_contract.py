"""Export the invocation contract, not an embedded copy of an OpenAPI document.

OpenAPI/JSON Schema keywords inside parameters, content, schemas and security schemes
retain their standard spelling. Repository-owned containers use kebab-case.
"""
import copy
import re
from urllib.parse import quote, unquote

from catalog_common import VERSION, require
from openapi_catalog import (METHODS, TEMPLATE, dereference, endpoint_name, merged_parameters,
                             operations, parameters_by_key, pointer, version_family)
from swagger_adapter import swagger_contract
from openapi_walk import SCHEMA_MAPS, SCHEMA_ARRAYS, SCHEMA_SINGLE, nodes

SCHEMA_VALUES = {'type', 'format', 'enum', 'const', 'default', 'required', 'minimum', 'maximum',
                 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf', 'minLength', 'maxLength',
                 'pattern', 'minItems', 'maxItems', 'uniqueItems', 'minContains', 'maxContains',
                 'minProperties', 'maxProperties', 'dependentRequired', 'nullable', 'readOnly',
                 'writeOnly', 'contentEncoding', 'contentMediaType', 'xml', '$schema', 'collectionFormat'}
DOC_KEYS = {'title', 'description', 'example', 'examples', 'externalDocs', 'deprecated', '$comment'}
PARAMETER_KEYS = {'name', 'in', 'required', 'style', 'explode', 'allowEmptyValue', 'allowReserved', 'collectionFormat'}


def schema_document(service):
    spec = service['spec']
    version = spec['openapi-version']
    return {('swagger' if version == '2.0' else 'openapi'): version, 'schemas': spec.get('schemas', {})}


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
        prefix = next((p for p in ('#/components/schemas/', '#/definitions/', '#/schemas/') if decoded.startswith(p)), None)
        require(prefix is not None, f'{ref}: bundle schema references under components.schemas or definitions')
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
        result = '#/schemas/' + quote('/'.join(parts), safe='/~')
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
        # Swagger form serialization needs collectionFormat; do not duplicate the full parameters.
        form = value.get('x-swagger-form-parameters', [])
        serialization = {p['name']: ({'collection-format': p['collectionFormat']} if 'collectionFormat' in p else {}) for p in form}
        if form:
            result['form-serialization'] = serialization
        return result

    def response(self, value):
        value = dereference(value, self.document)
        result = {}
        if 'content' in value:
            result['content'] = self.content(value['content'])
        if 'headers' in value:
            result['headers'] = {}
            for name, header in value['headers'].items():
                if version_family(self.document) == '2.0':
                    from swagger_adapter import scalar_schema
                    header = {'schema': scalar_schema(header), **({'collectionFormat': header['collectionFormat']} if 'collectionFormat' in header else {})}
                result['headers'][name] = self.parameter(header)
        return result


def select_servers(servers):
    return [{key: ({name: {k: copy.deepcopy(v) for k, v in variable.items() if k in ('default', 'enum')}
                    for name, variable in server[key].items()} if key == 'variables' else copy.deepcopy(server[key]))
             for key in ('url', 'variables', 'schemes') if key in server} for server in servers]


def export_service(document, organization, service):
    exporter = Exporter(document)
    family = version_family(document)
    if family == '2.0':
        root_servers = swagger_contract(document, {}, [], lambda v: dereference(v, document))['servers']
    else:
        root_servers = document.get('servers') or [{'url': '/'}]
    spec = {'openapi-version': document.get('swagger', document.get('openapi')),
            'servers': select_servers(root_servers), 'endpoints': []}
    if 'jsonSchemaDialect' in document:
        supported = {'3.1': 'https://spec.openapis.org/oas/3.1/dialect/base',
                     '3.2': 'https://spec.openapis.org/oas/3.2/dialect/2025-09-17'}
        require(document['jsonSchemaDialect'] == supported.get(family), 'unsupported jsonSchemaDialect; provide a supported dialect')
    security_names = set()
    for path, method, item, operation in operations(document):
        params = merged_parameters(document, item, operation)
        contract = swagger_contract(document, operation, params, lambda v: dereference(v, document)) if family == '2.0' else {
            **operation, 'parameters': params,
            'servers': operation.get('servers', item.get('servers', root_servers)) or [{'url': '/'}]}
        metadata = {'name': endpoint_name(service, method, path), 'organization': organization}
        for key in ('summary', 'description'):
            if isinstance(operation.get(key), str) and operation[key].strip():
                metadata['description'] = operation[key]
                break
        endpoint = {'metadata': metadata, 'method': method, 'path': path,
                    'security': copy.deepcopy(operation.get('security', document.get('security', []))),
                    'request': {'parameters': [exporter.parameter(p) for p in contract['parameters']]},
                    'responses': {status: exporter.response(response) for status, response in contract.get('responses', {}).items()
                                  if not status.startswith('x-')}}
        for requirement in endpoint['security']:
            security_names.update(requirement)
        if 'requestBody' in contract:
            endpoint['request']['body'] = exporter.body(contract['requestBody'])
        servers = select_servers(contract['servers'])
        if servers != spec['servers']:
            endpoint['servers'] = servers
        spec['endpoints'].append(endpoint)
    if exporter.schemas:
        spec['schemas'] = exporter.schemas
    definitions = document.get('securityDefinitions', {}) if family == '2.0' else document.get('components', {}).get('securitySchemes', {})
    if security_names:
        spec['security-schemes'] = {}
        for name in sorted(security_names):
            require(name in definitions, f'undefined security scheme {name}')
            scheme = dereference(definitions[name], document)
            spec['security-schemes'][name] = {k: copy.deepcopy(v) for k, v in scheme.items() if k not in DOC_KEYS and not k.startswith('x-')}
    return {'api-version': VERSION, 'kind': 'Service',
            'metadata': {'name': service, 'title': document['info']['title'], 'organization': organization}, 'spec': spec}


def endpoint_contract(service, endpoint):
    # This adapter is an internal view for existing snapshot/field validation consumers.
    result = {'parameters': copy.deepcopy(endpoint['request']['parameters']),
              'responses': copy.deepcopy(endpoint['responses']),
              'servers': copy.deepcopy(endpoint.get('servers', service['spec']['servers'])),
              'security': copy.deepcopy(endpoint['security'])}
    if 'body' in endpoint['request']:
        result['requestBody'] = copy.deepcopy(endpoint['request']['body'])
    return result


def validate_contract(service):
    """Validate a generated-only download without needing source JSON or executing it."""
    document = schema_document(service)
    family = version_family(document)
    exporter = Exporter(document)
    routes = set()
    used_security = set()
    require(select_servers(service['spec']['servers']) == service['spec']['servers'], 'noncanonical servers')
    for endpoint in service['spec']['endpoints']:
        method, path, meta = endpoint['method'], endpoint['path'], endpoint['metadata']
        require(meta['name'] == endpoint_name(service['metadata']['name'], method, path)
                and meta['organization'] == service['metadata']['organization'], 'generated metadata/endpoints differ from service identity')
        require(family == '3.2' or method in {m.upper() for m in METHODS}, 'method requires OpenAPI 3.2')
        shape = method, TEMPLATE.sub('{}', path)
        require(shape not in routes, f'duplicate method/path route {method} {path}')
        routes.add(shape)
        params = endpoint['request']['parameters']
        parameters_by_key(params, meta['name'])
        placeholders = TEMPLATE.findall(path)
        require(len(placeholders) == len(set(placeholders)) and '{' not in TEMPLATE.sub('', path)
                and '}' not in TEMPLATE.sub('', path), f'malformed path template {path}')
        require({p['name'] for p in params if p['in'] == 'path'} == set(placeholders), 'path placeholders and parameters differ')
        for param in params:
            require(param['in'] != 'path' or param.get('required') is True, 'path parameter must be required')
            require(param['in'] != 'querystring' or family == '3.2', 'querystring requires OpenAPI 3.2')
            require(exporter.parameter(param) == param, 'noncanonical request parameter')
        if 'body' in endpoint['request']:
            body = endpoint['request']['body']
            require(exporter.body(body) == {k: v for k, v in body.items() if k != 'form-serialization'}, 'noncanonical request body')
            if 'form-serialization' in body:
                require(family == '2.0', 'form-serialization is only for Swagger formData')
                for payload in body['content'].values():
                    schema = payload.get('schema', {})
                    require(schema.get('type') == 'object'
                            and set(body['form-serialization']) == set(schema.get('properties', {})),
                            'form-serialization must describe every formData field')
        for response in endpoint['responses'].values():
            # Already normalized response headers use schema even for Swagger.
            normalized = {k: v for k, v in response.items() if k != 'headers'}
            require(exporter.response(normalized) == normalized, 'noncanonical response')
            for header in response.get('headers', {}).values():
                require(exporter.parameter(header) == header, 'noncanonical response header')
        for requirement in endpoint['security']:
            for name, scopes in requirement.items():
                used_security.add(name)
                schemes = service['spec'].get('security-schemes', {})
                require(name in schemes, f'undefined security scheme {name}')
                scheme = schemes[name]
                if scheme.get('type') == 'oauth2':
                    allowed = set(scheme.get('scopes', {}))
                    for flow in scheme.get('flows', {}).values():
                        allowed.update(flow.get('scopes', {}))
                    require(set(scopes) <= allowed, f'unknown OAuth scope in {name}')
    require(exporter.schemas == service['spec'].get('schemas', {}), 'unreachable or noncanonical schema definitions')
    require(used_security == set(service['spec'].get('security-schemes', {})), 'unreachable security schemes')
    from openapi_catalog import validate_openapi
    validate_openapi(validation_document(service), f"Service/{service['metadata']['name']}")


def validation_document(service):
    """Rebuild only the selected contract into a transient document for native validators.

This document is never written to YAML; descriptions required by OpenAPI are placeholders.
"""
    spec = service['spec']
    family = version_family(schema_document(service))
    version_key = 'swagger' if family == '2.0' else 'openapi'
    result = {version_key: spec['openapi-version'], 'info': {'title': service['metadata']['title'], 'version': 'catalog'}, 'paths': {}}
    if family == '2.0':
        result['definitions'] = copy.deepcopy(spec.get('schemas', {}))
        result['securityDefinitions'] = copy.deepcopy(spec.get('security-schemes', {}))
    else:
        result['servers'] = copy.deepcopy(spec['servers'])
        result['components'] = {'schemas': copy.deepcopy(spec.get('schemas', {})),
                                'securitySchemes': copy.deepcopy(spec.get('security-schemes', {}))}

    def scalar_parameter(param):
        require('schema' in param and 'content' not in param, 'Swagger parameters require a schema')
        return {**{k: copy.deepcopy(v) for k, v in param.items() if k != 'schema'}, **copy.deepcopy(param['schema'])}

    def legacy_content(content):
        values = list(content.values())
        require(values and all('schema' in v and v['schema'] == values[0].get('schema') for v in values),
                'Swagger content schemas must agree across media types')
        return copy.deepcopy(values[0]['schema'])

    for endpoint in spec['endpoints']:
        operation = {'parameters': copy.deepcopy(endpoint['request']['parameters']),
                     'security': copy.deepcopy(endpoint['security']), 'responses': {}}
        if family == '2.0':
            operation['parameters'] = [scalar_parameter(p) for p in operation['parameters']]
        elif 'servers' in endpoint:
            operation['servers'] = copy.deepcopy(endpoint['servers'])
        if 'body' in endpoint['request']:
            body = copy.deepcopy(endpoint['request']['body'])
            if family == '2.0':
                operation['consumes'] = list(body['content'])
                schema = legacy_content(body['content'])
                if 'form-serialization' in body:
                    for name, prop in schema['properties'].items():
                        param = {'in': 'formData', 'name': name, **copy.deepcopy(prop)}
                        if param.get('format') == 'binary':
                            param['type'] = 'file'
                            param.pop('format')
                        if name in schema.get('required', []):
                            param['required'] = True
                        encoding = body.get('form-serialization', {}).get(name, {})
                        if 'collection-format' in encoding:
                            param['collectionFormat'] = encoding['collection-format']
                        operation['parameters'].append(param)
                else:
                    operation['parameters'].append({'in': 'body', 'name': 'payload', 'schema': schema,
                                                     'required': body.get('required', False)})
            else:
                operation['requestBody'] = body
        for status, selected in endpoint['responses'].items():
            response = {'description': '', **copy.deepcopy(selected)}
            if family == '2.0':
                if 'content' in response:
                    response['schema'] = legacy_content(response.pop('content'))
                if 'headers' in response:
                    response['headers'] = {name: scalar_parameter(header) for name, header in response['headers'].items()}
            operation['responses'][status] = response
        if family == '3.2' and not operation['responses']:
            operation.pop('responses')
        item = result['paths'].setdefault(endpoint['path'], {})
        method = endpoint['method']
        if method in {m.upper() for m in METHODS} or method == 'QUERY':
            item[method.lower()] = operation
        else:
            item.setdefault('additionalOperations', {})[method] = operation

    prefix = '#/definitions/' if family == '2.0' else '#/components/schemas/'
    for kind, value in nodes(result):
        if '$ref' in value and value['$ref'].startswith('#/schemas/'):
            value['$ref'] = prefix + value['$ref'][len('#/schemas/'):]
        discriminator = value.get('discriminator') if kind == 'schema' else None
        if isinstance(discriminator, dict):
            for name, ref in discriminator.get('mapping', {}).items():
                if ref.startswith('#/schemas/'):
                    discriminator['mapping'][name] = prefix + ref[len('#/schemas/'):]
    return result
