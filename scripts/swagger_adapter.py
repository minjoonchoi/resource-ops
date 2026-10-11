"""Adapt Swagger 2.0 operation contracts for Page usage; the source stays unchanged.

Schema $refs stay rooted in the original Swagger document (including #/definitions).
This is a catalog view, not a rewrite into an OpenAPI 3 document.
"""
import copy

from catalog_common import require

SCHEMA_KEYS = {'type', 'format', 'items', 'default', 'maximum', 'exclusiveMaximum', 'minimum',
               'exclusiveMinimum', 'maxLength', 'minLength', 'pattern', 'maxItems', 'minItems',
               'uniqueItems', 'enum', 'multipleOf'}


def scalar_schema(parameter):
    return {key: copy.deepcopy(value) for key, value in parameter.items() if key in SCHEMA_KEYS}


def swagger_contract(document, operation, parameters, resolve):
    result = copy.deepcopy(operation)
    consumes = operation.get('consumes', document.get('consumes', []))
    produces = operation.get('produces', document.get('produces', []))
    result['consumes'], result['produces'] = copy.deepcopy(consumes), copy.deepcopy(produces)
    schemes = operation.get('schemes', document.get('schemes', []))
    host, base_path = document.get('host'), document.get('basePath', '/')
    # Retain the source context requirements instead of inventing an HTTP scheme or host.
    result['swaggerServer'] = {'host': host, 'basePath': base_path, 'schemes': copy.deepcopy(schemes)}
    if host and schemes:
        result['servers'] = [{'url': f'{scheme}://{host}{base_path}'} for scheme in schemes]
    else:
        result['servers'] = [{'url': (f'//{host}' if host else '') + base_path}]

    normal, body, form = [], [], []
    for parameter in parameters:
        parameter = copy.deepcopy(parameter)
        if parameter['in'] == 'body':
            body.append(parameter)
        elif parameter['in'] == 'formData':
            form.append(parameter)
        else:
            parameter['schema'] = scalar_schema(parameter)
            normal.append(parameter)
    require(len(body) <= 1 and not (body and form), 'Swagger: body and formData are mutually exclusive; at most one body')
    result['parameters'] = normal
    if body:
        parameter = body[0]
        result['requestBody'] = {
            'required': parameter.get('required', False),
            'content': {media: {'schema': copy.deepcopy(parameter['schema'])} for media in consumes or ['*/*']},
            'x-swagger-body-parameter': parameter,
        }
        if 'description' in parameter:
            result['requestBody']['description'] = parameter['description']
    elif form:
        properties, required = {}, []
        for parameter in form:
            schema = scalar_schema(parameter)
            if schema.get('type') == 'file':
                schema = {'type': 'string', 'format': 'binary'}
            properties[parameter['name']] = schema
            if parameter.get('required'):
                required.append(parameter['name'])
        schema = {'type': 'object', 'properties': properties}
        if required:
            schema['required'] = required
        result['requestBody'] = {
            'required': bool(required),
            'content': {media: {'schema': copy.deepcopy(schema)} for media in consumes or ['*/*']},
            # Includes collectionFormat and the original file type for exact wire handling.
            'x-swagger-form-parameters': copy.deepcopy(form),
        }
    result['responses'] = {}
    for status, raw in operation.get('responses', {}).items():
        if status.startswith('x-'):
            result['responses'][status] = copy.deepcopy(raw)
            continue
        response = copy.deepcopy(resolve(raw))
        if 'schema' in response:
            content = {}
            for media in produces or ['*/*']:
                content[media] = {'schema': copy.deepcopy(response['schema'])}
                if media in response.get('examples', {}):
                    content[media]['example'] = copy.deepcopy(response['examples'][media])
            response['content'] = content
        result['responses'][status] = response
    return result
