"""Validate nested Page request bindings and HTTP 200 response allowlists.

The catalog records policies; the execution server resolves subjects, scopes and masks.
Native field names are literal keys, including names such as source, mask, dots or slashes.
"""
from catalog_common import NAME, require
from openapi_catalog import dereference, parameters_by_key


def json_body_schema(body, document, location):
    body = dereference(body, document)
    content = body.get('content', {})
    require(len(content) == 1, f'{location}: needs exactly one JSON media type')
    media, payload = next(iter(content.items()))
    require(media == 'application/json' or (media.startswith('application/') and media.endswith('+json')),
            f'{location}: needs JSON content')
    require('schema' in payload, f'{location}: needs a schema')
    return payload['schema']


def validate_binding(rule, schema, location):
    require(isinstance(rule, dict), f'{location}: expected a subject or scope binding')
    if rule.get('source') == 'subject':
        require(set(rule) == {'source', 'field'} and rule['field'] in ('id', 'nickname', 'email'),
                f'{location}: subject binding needs field: id, nickname or email')
        types = schema.get('type')
        types = [types] if isinstance(types, str) else types
        require(set(types) - {'null'} == {'string'}, f'{location}: subject sources require a string field')
    else:
        require(rule.get('source') == 'scope' and set(rule) == {'source', 'name'}
                and isinstance(rule['name'], str) and NAME.fullmatch(rule['name']) and len(rule['name']) <= 128,
                f'{location}: scope binding needs a valid name')


def validate_leaf(rule, schema, location, response):
    if response:
        require(rule is True or (isinstance(rule, dict) and set(rule) == {'mask'}
                and isinstance(rule['mask'], str) and NAME.fullmatch(rule['mask']) and len(rule['mask']) <= 128),
                f'{location}: response leaf must be true or a named mask')
    else:
        validate_binding(rule, schema, location)


def validate_tree(schema, rules, document, location, response=False, array_chain=(), depth=0):
    require(depth <= 128, f'{location}: rule nesting is too deep')
    schema = dereference(schema, document)
    require(isinstance(schema, dict) and not any(k in schema for k in ('allOf', 'oneOf', 'anyOf', 'not', 'if')),
            f'{location}: rules need an unambiguous schema; composition/boolean schemas are unsupported')
    types = schema.get('type', [])
    types = [types] if isinstance(types, str) else types
    types = set(types) - {'null'}
    require(len(types) == 1, f'{location}: rules need an unambiguous schema type')
    kind = next(iter(types))
    if kind == 'array':
        require(id(schema) not in array_chain and 'items' in schema and 'prefixItems' not in schema,
                f'{location}: recursive or tuple array rules are unsupported')
        validate_tree(schema['items'], rules, document, location + '[]', response,
                      (*array_chain, id(schema)), depth + 1)
    elif kind == 'object':
        require(isinstance(rules, dict) and rules, f'{location}: select individual leaves in a non-empty object')
        properties = schema.get('properties', {})
        for name, rule in rules.items():
            require(name in properties, f'{location}: field {name!r} does not exist')
            validate_tree(properties[name], rule, document, f'{location}[{name!r}]', response, (), depth + 1)
    else:
        require(kind in {'string', 'number', 'integer', 'boolean'}, f'{location}: unsupported leaf type {kind}')
        validate_leaf(rules, schema, location, response)


def validate_page_rules(usage, contract, document, location):
    request = usage.get('request', {})
    parameters = parameters_by_key(contract['parameters'], location)
    for name, rules in request.get('query', {}).items():
        parameter = parameters.get(('query', name))
        require(parameter is not None, f'{location}: unknown endpoint query parameter {name!r}')
        require('schema' in parameter, f'{location}: parameter content bindings are unsupported')
        validate_tree(parameter['schema'], rules, document, f'{location}.request.query[{name!r}]')
    if 'body' in request:
        require('requestBody' in contract, f'{location}: endpoint has no request body')
        schema = json_body_schema(contract['requestBody'], document, location + '.request.body')
        validate_tree(schema, request['body'], document, location + '.request.body')
    if 'response' in usage:
        responses = contract.get('responses', {})
        # Resolve the contract covering 200; the rule still applies ONLY to actual HTTP 200.
        status = next((key for key in ('200', '2XX', 'default') if key in responses), None)
        require(status is not None, f'{location}: endpoint has no response contract for HTTP 200')
        schema = json_body_schema(responses[status], document, location + '.response')
        validate_tree(schema, usage['response']['fields'], document, location + '.response.fields', response=True)
