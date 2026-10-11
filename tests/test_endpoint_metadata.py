import copy

from catalog_test_base import *
from openapi_catalog import make_service
from test_openapi_versions import VERSIONS, document_for


class EndpointMetadataTests(Fixture):
    def test_original_paths_remain_distinct_through_yaml_and_snapshot(self):
        paths = ['/a/b', '/a.b', '/members', '/members/', '/Members',
                 '/members/{id}', '/members/by-id', '/files/report.pdf',
                 '/.well-known/openid-configuration', '/encoded/%2F', '/encoded/%2f',
                 '/long/' + 'segment/' * 30, '/']
        def edit(document):
            for path in paths:
                operation = {'responses': {'200': {'description': 'OK'}}}
                if '{id}' in path:
                    operation['parameters'] = [{'name': 'id', 'in': 'path', 'required': True,
                                                'schema': {'type': 'string'}}]
                document['paths'][path] = {'get': operation}
        self.change_api(edit)
        snapshot = build_snapshot(self.root)
        names = {e['metadata']['name'] for e in snapshot['resources'] if e['kind'] == 'Endpoint'}
        for path in paths:
            self.assertIn('member-api.GET.' + path, names)
        self.assertEqual(len(names), len(paths) + 2)
        self.assertEqual(snapshot, build_snapshot(self.root, verify_sources=False))

    def test_description_priority_and_omission_across_versions(self):
        cases = [
            ({'summary': '회원 조회', 'description': 'Detailed description'}, '회원 조회'),
            ({'description': '**Details**\n\nSecond paragraph'}, '**Details**\n\nSecond paragraph'),
            ({'summary': ' \t\n', 'description': 'Fallback'}, 'Fallback'),
            ({'summary': '', 'description': '  Keep whitespace\n'}, '  Keep whitespace\n'),
            ({'summary': '', 'description': ' \n'}, None),
            ({}, None),
            ({'operationId': 'readRecord'}, None),
        ]
        for version in VERSIONS:
            for fields, expected in cases:
                with self.subTest(version=version, fields=fields):
                    document = document_for(version)
                    operation = document['paths']['/records/{id}']['get']
                    for field in ('summary', 'description', 'operationId'):
                        operation.pop(field, None)
                    operation.update(fields)
                    original = copy.deepcopy(document)
                    result = make_service(document, 'team', 'api', 'openapi/team/api.json')
                    entry = next(e for e in result['spec']['endpoints']
                                 if e['method'] == 'GET' and e['path'] == '/records/{id}')
                    metadata = {'name': 'api.GET./records/{id}', 'organization': 'team'}
                    if expected is not None:
                        metadata['description'] = expected
                    self.assertEqual(entry['metadata'], metadata)
                    self.assertEqual(document, original)
                    self.assertNotIn('openapi', result['spec'])

    def test_description_changes_keep_action_endpoint_identity(self):
        before = build_snapshot(self.root)
        def edit(document):
            operation = document['paths'][DETAIL]['get']
            operation.pop('summary', None)
            operation['description'] = '회원 상세 설명\n\n두 번째 문단'
            operation['operationId'] = 'renamedOperation'
        self.change_api(edit)
        after = build_snapshot(self.root)
        self.assertEqual(before['relations'], after['relations'])
        endpoint = next(e for e in after['resources'] if e['kind'] == 'Endpoint'
                        and e['spec']['path'] == DETAIL)
        self.assertEqual(endpoint['metadata']['description'], '회원 상세 설명\n\n두 번째 문단')
        self.assertNotIn('title', endpoint['metadata'])
        self.assertEqual(self.effective(before), self.effective(after))

    def test_generated_metadata_tampering_is_rejected_without_sources(self):
        original = self.read(SERVICE)
        for field, value in [('name', 'member-api.GET./wrong'), ('organization', 'wrong'),
                             ('title', 'old title')]:
            with self.subTest(field=field):
                modified = copy.deepcopy(original)
                modified['spec']['endpoints'][0]['metadata'][field] = value
                self.write(SERVICE, modified)
                with self.assertRaises(CatalogError):
                    build_snapshot(self.root, verify_sources=False)
        self.write(SERVICE, original)

    def test_description_tampering_requires_source_comparison(self):
        self.change(SERVICE, lambda s: s['spec']['endpoints'][0]['metadata'].update(description='wrong'))
        build_snapshot(self.root, verify_sources=False)
        self.invalid('generated files differ')

    def test_custom_methods_keep_case_and_punctuation(self):
        document = document_for('3.2.1')
        document['paths']['/custom'] = {'additionalOperations': {
            method: {'responses': {'200': {'description': 'OK'}}}
            for method in ('COPY', 'copy', 'custom.method', 'X!TEST')}}
        self.write('openapi/team/custom-api.json', document)
        generate(self.root, target='team/custom-api')
        snapshot = build_snapshot(self.root)
        names = {e['metadata']['name'] for e in snapshot['resources'] if e['kind'] == 'Endpoint'}
        for method in ('COPY', 'copy', 'custom.method', 'X!TEST'):
            self.assertIn(f'custom-api.{method}./custom', names)

    def test_ambiguous_service_and_custom_method_combination_is_rejected(self):
        for service, method in [('api', 'group.copy'), ('api.group', 'copy')]:
            document = {'openapi': '3.2.1', 'info': {'title': service, 'version': '1'},
                        'paths': {'/resource': {'additionalOperations': {
                            method: {'responses': {'200': {'description': 'OK'}}}}}}}
            self.write(f'openapi/team/{service}.json', document)
        generate(self.root)
        self.invalid('duplicate endpoint identity')
