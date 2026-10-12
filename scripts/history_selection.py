"""Validate optional history value selections against the native endpoint contract."""
from service_contract import schema_document
from catalog_common import require
from openapi_catalog import dereference, leaf_schema, parameters_by_key


def validate_body_selection(body, fields, document, location):
    body = dereference(body, document)
    content = body.get('content', {})
    require(len(content) == 1, f'{location}: history selection needs exactly one JSON media type')
    media, payload = next(iter(content.items()))
    require(media == 'application/json' or (media.startswith('application/') and media.endswith('+json')),
            f'{location}: history selection needs JSON content')
    require('schema' in payload, f'{location}: history selection needs a schema')
    for field in fields:
        leaf_schema(payload['schema'], field, document, location)


def validate_history_selection(action, endpoint, service):
    document = schema_document(service)
    contract = endpoint['spec']['operation']
    location = f"Action/{action['metadata']['name']}.history"
    for plugin in action['spec'].get('plugins', []):
        if plugin['name'] != 'history':
            continue
        config = plugin.get('config', {})
        request = config.get('request', {})
        available = parameters_by_key(contract['parameters'], location)
        selections = parameters_by_key(request.get('parameters', []), location)
        require(set(selections) <= set(available), f'{location}: unknown request parameter')
        for key, selection in selections.items():
            parameter = available[key]
            require('schema' in parameter, f'{location}: parameter content selection is unsupported')
            for field in selection.get('fields', ['']):
                leaf_schema(parameter['schema'], field, document, f'{location}.request.parameters.{key}')
        if 'body' in request:
            require('requestBody' in contract, f'{location}: endpoint has no request body')
            validate_body_selection(contract['requestBody'], request['body']['fields'], document,
                                    f'{location}.request.body')
        for status, selection in config.get('responses', {}).items():
            require(status in contract.get('responses', {}), f'{location}: unknown response status {status}')
            validate_body_selection(contract['responses'][status], selection['fields'], document,
                                    f'{location}.responses.{status}')
