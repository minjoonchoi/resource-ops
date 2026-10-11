import copy

from catalog_test_base import *
from test_openapi_versions import VERSIONS, document_for

ACTION = 'actions/members.detail.read.yaml'


class HistorySelectionTests(Fixture):
    def select(self, config):
        self.change(ACTION, lambda d: d['spec'].update(
            plugins=[{'name': 'history', 'config': config}]))

    def test_selection_survives_snapshot_and_does_not_change_page_contract(self):
        before = build_snapshot(self.root)
        config = {'request': {'parameters': [{'in': 'path', 'name': 'memberId'}]},
                  'responses': {'200': {'fields': ['/id', '/email']}}}
        self.select(config)
        after = build_snapshot(self.root)
        self.assertEqual(self.effective(before), self.effective(after))
        self.assertNotIn('/email', self.effective(after)['responses']['200']['fields'])
        usages = [u for u in after['pageActionUsages'] if u['action'] == 'members.detail.read']
        for usage in usages:
            self.assertEqual(usage['plugins'][0]['config'], config)
        self.assertEqual(after, build_snapshot(self.root, verify_sources=False))
        usages[0]['plugins'][0]['config']['responses']['200']['fields'].clear()
        self.assertEqual(usages[1]['plugins'][0]['config'], config)

    def test_invalid_selection_shapes(self):
        for config in ({}, {'request': {}}, {'request': {'parameters': []}},
                       {'request': {'body': {'fields': []}}}, {'responses': {}},
                       {'responses': {'200': {'fields': ['/id', '/id']}}},
                       {'responses': {'200': {'fields': ['id']}}},
                       {'events': ['endpoint']}, {'response': {'fields': ['/id']}}):
            with self.subTest(config=config):
                self.select(config)
                with self.assertRaises(CatalogError):
                    build_snapshot(self.root)

    def test_missing_parameters_body_status_and_fields_are_rejected(self):
        cases = [({'request': {'parameters': [{'in': 'query', 'name': 'missing'}]}}, 'unknown request parameter'),
                 ({'request': {'body': {'fields': ['/id']}}}, 'no request body'),
                 ({'responses': {'201': {'fields': ['/id']}}}, 'unknown response status'),
                 ({'responses': {'200': {'fields': ['/missing']}}}, 'does not exist'),
                 ({'responses': {'200': {'fields': ['']}}}, 'container or untyped')]
        for config, message in cases:
            with self.subTest(config=config):
                self.select(config)
                self.invalid(message)

    def test_unpaged_actions_and_generated_only_consumer_validate_selection(self):
        for page in ('members', 'member-detail'):
            self.change(f'pages/{page}.yaml', lambda d: d['spec'].update(
                actions=[u for u in d['spec']['actions'] if u['action'] != 'members.detail.read']))
        self.select({'responses': {'200': {'fields': ['/missing']}}})
        for verify in (True, False):
            with self.subTest(verify=verify), self.assertRaisesRegex(CatalogError, 'does not exist'):
                build_snapshot(self.root, verify_sources=verify)

    def test_nested_array_and_escaped_request_body_fields(self):
        schema = {'type': 'object', 'properties': {
            'reason': {'type': 'string'}, 'a/b': {'type': 'string'}, 'a~b': {'type': 'integer'},
            'items': {'type': 'array', 'items': {'$ref': '#/components/schemas/Member'}}}}
        self.change_api(lambda d: d['paths'][DETAIL]['get'].update(
            requestBody={'content': {'application/json': {'schema': schema}}}))
        self.select({'request': {'body': {'fields': ['/reason', '/items/*/id', '/a~1b', '/a~0b']}}})
        build_snapshot(self.root)
        self.select({'request': {'body': {'fields': ['/items']}}})
        self.invalid('container or untyped')

    def test_header_matching_and_structured_parameter_selection(self):
        def edit(document):
            document['paths'][DETAIL]['get']['parameters'] += [
                {'in': 'header', 'name': 'X-Trace', 'schema': {'type': 'string'}},
                {'in': 'query', 'name': 'filter', 'schema': {'type': 'object', 'properties': {
                    'id': {'type': 'string'}}}}]
        self.change_api(edit)
        parameters = [{'in': 'header', 'name': 'x-trace'},
                      {'in': 'query', 'name': 'filter', 'fields': ['/id']}]
        self.select({'request': {'parameters': parameters}})
        build_snapshot(self.root)
        self.select({'request': {'parameters': [*parameters, {'in': 'header', 'name': 'X-TRACE'}]}})
        self.invalid('duplicate parameter')
        self.select({'request': {'parameters': [{'in': 'query', 'name': 'filter'}]}})
        self.invalid('container or untyped')

    def test_response_range_default_and_array_fields(self):
        self.change_api(lambda d: d['paths'][DETAIL]['get']['responses'].update({
            '2XX': copy.deepcopy(d['paths'][LIST]['get']['responses']['200']),
            'default': copy.deepcopy(d['paths'][DETAIL]['get']['responses']['404']),
            '204': {'description': 'Empty'}}))
        self.select({'responses': {'2XX': {'fields': ['/items/*/id']}, 'default': {'fields': ['/code']}}})
        build_snapshot(self.root)
        self.select({'responses': {'204': {'fields': ['/id']}}})
        self.invalid('exactly one JSON media type')

    def test_ambiguous_non_json_and_content_parameters_are_rejected(self):
        original = self.read(SOURCE)
        for content, message in [
            ({'text/plain': {'schema': {'type': 'string'}}}, 'JSON content'),
            ({'application/json': {'schema': {'type': 'string'}},
              'application/xml': {'schema': {'type': 'string'}}}, 'exactly one'),
            ({'application/json': {'schema': {'oneOf': [{'type': 'string'}, {'type': 'integer'}]}}},
             'unambiguous schema')]:
            with self.subTest(content=content):
                self.write(SOURCE, original)
                self.change_api(lambda d: d['paths'][DETAIL]['get'].update(requestBody={'content': content}))
                self.select({'request': {'body': {'fields': ['']}}})
                self.invalid(message)
        self.write(SOURCE, original)
        self.change_api(lambda d: d['paths'][DETAIL]['get']['parameters'].append(
            {'in': 'query', 'name': 'filter', 'content': {'application/json': {'schema': {'type': 'string'}}}}))
        self.select({'request': {'parameters': [{'in': 'query', 'name': 'filter'}]}})
        self.invalid('parameter content selection is unsupported')

    def test_version_matrix_native_body_parameters_and_response_refs(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                document = document_for(version)
                schema = {'type': 'object', 'properties': {'reason': {'type': 'string'}}}
                operation = document['paths']['/records/{id}']['get']
                if version == '2.0':
                    operation['parameters'].append({'in': 'body', 'name': 'body', 'schema': schema})
                else:
                    operation['requestBody'] = {'content': {'application/json': {'schema': schema}}}
                self.write('openapi/team/compat-api.json', document)
                self.write('actions/compat.audit.yaml', {
                    'apiVersion': 'resource-ops/v1', 'kind': 'Action',
                    'metadata': {'name': 'compat.audit', 'title': 'Audit'},
                    'spec': {'endpoint': {'service': 'compat-api', 'method': 'GET', 'path': '/records/{id}'},
                             'plugins': [{'name': 'history', 'config': {
                                 'request': {'parameters': [{'in': 'path', 'name': 'id'}],
                                             'body': {'fields': ['/reason']}},
                                 'responses': {'200': {'fields': ['/id']}}}}]}})
                generate(self.root, target='team/compat-api')
                snapshot = build_snapshot(self.root)
                self.assertEqual(self.read('services/compat-api.yaml')['spec']['openapi'], document)
                self.assertEqual(snapshot, build_snapshot(self.root, verify_sources=False))
