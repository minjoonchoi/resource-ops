"""Walk specification objects without interpreting user data or field names as keywords."""

SCHEMA_MAPS = {'properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'}
SCHEMA_ARRAYS = {'allOf', 'anyOf', 'oneOf', 'prefixItems'}
SCHEMA_SINGLE = {'additionalProperties', 'additionalItems', 'contains', 'propertyNames', 'not',
                 'if', 'then', 'else', 'unevaluatedItems', 'unevaluatedProperties', 'contentSchema'}

CHILDREN = {
    'root': {'paths': ('map', 'path'), 'webhooks': ('map', 'path'), 'components': ('one', 'components'),
             'definitions': ('map', 'schema'), 'parameters': ('map', 'parameter'), 'responses': ('map', 'response'),
             'securityDefinitions': ('map', 'security')},
    'components': {name: ('map', kind) for name, kind in {
        'schemas': 'schema', 'parameters': 'parameter', 'headers': 'parameter', 'requestBodies': 'body',
        'responses': 'response', 'callbacks': 'callback', 'pathItems': 'path', 'securitySchemes': 'security',
        'examples': 'example', 'links': 'link', 'mediaTypes': 'media'}.items()},
    'path': {**{method: ('one', 'operation') for method in
               ('get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace', 'query')},
             'parameters': ('list', 'parameter'), 'additionalOperations': ('map', 'operation')},
    'operation': {'parameters': ('list', 'parameter'), 'requestBody': ('one', 'body'),
                  'responses': ('map', 'response'), 'callbacks': ('map', 'callback')},
    'parameter': {'schema': ('one', 'schema'), 'items': ('one', 'schema'),
                  'content': ('map', 'media'), 'examples': ('map', 'example')},
    'body': {'content': ('map', 'media')},
    'response': {'schema': ('one', 'schema'), 'content': ('map', 'media'),
                 'headers': ('map', 'parameter'), 'links': ('map', 'link')},
    'media': {'schema': ('one', 'schema'), 'itemSchema': ('one', 'schema'), 'examples': ('map', 'example'),
              'encoding': ('map', 'encoding'), 'prefixEncoding': ('list', 'encoding'),
              'itemEncoding': ('one', 'encoding')},
    'encoding': {'headers': ('map', 'parameter'), 'encoding': ('map', 'encoding'),
                 'prefixEncoding': ('list', 'encoding'), 'itemEncoding': ('one', 'encoding')},
}


def nodes(value, kind='root'):
    if not isinstance(value, dict):
        return
    yield kind, value
    if kind == 'schema':
        for key, child in value.items():
            if key in SCHEMA_MAPS and isinstance(child, dict):
                for schema in child.values():
                    yield from nodes(schema, 'schema')
            elif key in SCHEMA_ARRAYS and isinstance(child, list):
                for schema in child:
                    yield from nodes(schema, 'schema')
            elif key in SCHEMA_SINGLE:
                yield from nodes(child, 'schema')
            elif key == 'items':
                for schema in child if isinstance(child, list) else [child]:
                    yield from nodes(schema, 'schema')
            elif key == 'dependencies' and isinstance(child, dict):
                for schema in child.values():
                    yield from nodes(schema, 'schema')
        return
    if kind == 'callback':
        for key, child in value.items():
            if key != '$ref' and not key.startswith('x-'):
                yield from nodes(child, 'path')
        return
    for key, (container, child_kind) in CHILDREN.get(kind, {}).items():
        child = value.get(key)
        if container == 'map' and isinstance(child, dict):
            for entry in child.values():
                yield from nodes(entry, child_kind)
        elif container == 'list' and isinstance(child, list):
            for entry in child:
                yield from nodes(entry, child_kind)
        elif container == 'one':
            yield from nodes(child, child_kind)
