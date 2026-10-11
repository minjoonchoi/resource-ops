import copy

from catalog_test_base import *
from test_openapi_versions import VERSIONS, document_for


class PageRulesTests(Fixture):
    def set_request(self, request):
        self.change_usage('members', 'members.detail.read', lambda u: u.update(request=request))

    def set_fields(self, fields):
        self.change_usage('members', 'members.detail.read', lambda u: u.update(response={'fields': fields}))

    def add_body(self, schema):
        def edit(d):
            d['paths'][DETAIL]['post'] = copy.deepcopy(d['paths'][DETAIL]['get'])
            d['paths'][DETAIL]['post'].pop('operationId', None)
            d['paths'][DETAIL]['post']['requestBody'] = {
                'content': {'application/json': {'schema': schema}}}
        self.change_api(edit)
        self.change('actions/members.detail.read.yaml', lambda d: d['spec']['endpoint'].update(method='POST'))

    def test_owned_keys_use_kebab_case_and_native_keys_are_preserved(self):
        snapshot = build_snapshot(self.root)
        self.assertIn('api-version', snapshot)
        self.assertIn('page-action-usages', snapshot)
        self.assertIn('content-sha256', snapshot)
        service = self.read(SERVICE)
        self.assertNotIn('openapi-version', service['spec'])
        self.assertEqual(service['spec']['openapi'], self.read(SOURCE)['openapi'])
        self.assertIn('organizationCode', service['spec']['components']['schemas']['Member']['properties'])
        self.change('pages/members.yaml', lambda d: d.update(apiVersion=d.pop('api-version')))
        self.invalid('Additional properties')

    def test_nested_body_subject_and_scope_survive_snapshot(self):
        self.add_body({'type': 'object', 'properties': {
            'requester': {'type': 'object', 'properties': {
                'nickname': {'type': 'string'}, 'email': {'type': 'string', 'format': 'email'}}},
            'departments': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'code': {'type': 'string'}}}}}})
        rules = {'body': {'requester': {'nickname': {'source': 'subject', 'field': 'nickname'},
                                       'email': {'source': 'subject', 'field': 'email'}},
                          'departments': {'code': {'source': 'scope', 'name': 'department-codes'}}}}
        self.set_request(rules)
        snapshot = build_snapshot(self.root)
        self.assertEqual(self.effective(snapshot)['request']['rules'], rules)
        self.assertNotIn('rules', self.effective(snapshot, 'member-detail')['request'])
        self.assertEqual(snapshot, build_snapshot(self.root, verify_sources=False))

    def test_subject_query_checks_string_schema_without_changing_parameter_name(self):
        self.change_api(lambda d: d['paths'][DETAIL]['get']['parameters'].append(
            {'in': 'query', 'name': 'user_email', 'schema': {'type': 'string'}}))
        self.set_request({'query': {'user_email': {'source': 'subject', 'field': 'email'}}})
        effective = self.effective(build_snapshot(self.root))
        self.assertEqual(effective['request']['rules']['query']['user_email']['field'], 'email')
        self.change_api(lambda d: d['paths'][DETAIL]['get']['parameters'][-1].update(schema={'type': 'integer'}))
        self.invalid('subject sources require a string')

    def test_invalid_bindings_and_empty_rules_fail(self):
        original = self.read('pages/members.yaml')
        variants = [
            {'request': {}}, {'request': {'query': {}}}, {'request': {'body': {}}},
            {'request': {'query': {'organizationCode': {'source': 'subject', 'field': 'unknown'}}}},
            {'request': {'query': {'organizationCode': {'source': 'subject', 'field': 'email', 'name': 'codes'}}}},
            {'request': {'query': {'organizationCode': {'source': 'scope'}}}},
            {'request': {'query': {'organizationCode': {'source': 'scope', 'name': 'codes', 'value': 'A'}}}},
            {'request': {'query': {'organizationCode': {'source': 'input'}}}},
            {'request': {'parameters': []}}, {'request': {'header': {'host': {}}}},
            {'response': {'fields': {}}}, {'response': {'fields': {'id': False}}},
            {'response': {'fields': ['/id']}}, {'response': {'fields': {'id': {'mask': 'Invalid Name'}}}},
            {'response': {'200': {'fields': {'id': True}}}},
        ]
        for rules in variants:
            with self.subTest(rules=rules):
                self.change_usage('members', 'members.directory.list', lambda u: u.update(rules))
                with self.assertRaises(CatalogError):
                    build_snapshot(self.root)
                self.write('pages/members.yaml', original)

    def test_missing_body_and_unknown_nested_field_fail(self):
        self.set_request({'body': {'email': {'source': 'subject', 'field': 'email'}}})
        self.invalid('no request body')
        self.add_body({'type': 'object', 'properties': {'requester': {'type': 'object', 'properties': {
            'email': {'type': 'string'}}}}})
        self.invalid('does not exist')
        self.set_request({'body': {'requester': {'email': {'source': 'subject', 'field': 'email'}}}})
        build_snapshot(self.root)

    def test_body_requires_one_json_media_type_and_unambiguous_schema(self):
        self.add_body({'type': 'object', 'properties': {'email': {'type': 'string'}}})
        self.set_request({'body': {'email': {'source': 'subject', 'field': 'email'}}})
        self.change_api(lambda d: d['paths'][DETAIL]['post']['requestBody']['content'].update(
            {'text/plain': {'schema': {'type': 'string'}}}))
        self.invalid('exactly one JSON media type')

    def test_native_fields_named_source_mask_and_slashes_are_not_rule_keys(self):
        shape = {'type': 'object', 'properties': {
            name: {'type': 'string'} for name in ('source', 'mask', 'a/b', 'a.b', 'apiVersion', 'snake_case')}}
        self.add_body(shape)
        self.set_request({'body': {'source': {'source': 'subject', 'field': 'email'}}})
        self.change_api(lambda d: d['components']['schemas']['Member']['properties'].update(payload=shape))
        fields = {'payload': {name: True for name in shape['properties']}}
        self.set_fields(fields)
        self.assertEqual(self.effective(build_snapshot(self.root))['response']['fields'], fields)

    def test_allowlist_keeps_only_declared_fields_and_mask_rules(self):
        fields = {'id': True, 'email': {'mask': 'email'}}
        self.set_fields(fields)
        before = build_snapshot(self.root)
        self.change_api(lambda d: d['components']['schemas']['Member']['properties'].update(secret={'type': 'string'}))
        after = build_snapshot(self.root)
        # New upstream fields cannot expand the Page allowlist. Native contracts stay complete.
        self.assertEqual(self.effective(before)['response'], self.effective(after)['response'])
        self.assertEqual(self.effective(after)['response']['fields'], fields)
        self.assertNotIn('secret', self.effective(after)['response']['fields'])
        edge = next(r for r in after['relations'] if r['from'] == 'Page/members' and r['to'] == 'Action/members.detail.read')
        self.assertEqual(edge['response']['fields'], fields)
        self.assertIn('secret', self.read(SERVICE)['spec']['components']['schemas']['Member']['properties'])

    def test_200_contract_resolution_does_not_attach_rules_to_other_statuses(self):
        original = self.read(SOURCE)
        for key in ('200', '2XX', 'default'):
            with self.subTest(key=key):
                d = copy.deepcopy(original)
                response = d['paths'][DETAIL]['get']['responses'].pop('200')
                d['paths'][DETAIL]['get']['responses'][key] = response
                self.write(SOURCE, d)
                generate(self.root)
                self.change('actions/members.contact.read.yaml', lambda a: a['spec'].pop('plugins', None))
                effective = self.effective(build_snapshot(self.root))
                self.assertEqual(effective['response']['fields'], {'id': True, 'nickname': True})
                self.assertNotIn('fields', effective['responses'][key])
        self.change_api(lambda d: d['paths'][DETAIL]['get']['responses'].update({'200': {'description': 'no body'}}))
        self.invalid('exactly one JSON media type')

    def test_no_response_rule_inherits_contract_and_missing_200_fails_when_selected(self):
        self.change('actions/members.contact.read.yaml', lambda d: d['spec'].pop('plugins'))
        self.change_api(lambda d: d['paths'][DETAIL]['get']['responses'].pop('200'))
        self.invalid('no response contract for HTTP 200')
        for page in ('members', 'member-detail'):
            self.change(f'pages/{page}.yaml', lambda d: [u.pop('response', None) for u in d['spec']['actions'] if u['action'] != 'members.directory.list'])
        self.assertNotIn('response', self.effective(build_snapshot(self.root)))

    def test_nested_arrays_and_nullable_objects(self):
        self.change_api(lambda d: d.update(openapi='3.1.2'))
        self.change_api(lambda d: d['components']['schemas']['Member']['properties'].update(
            groups={'type': ['array', 'null'], 'items': {'type': ['object', 'null'], 'properties': {
                'emails': {'type': 'array', 'items': {'type': ['string', 'null']}}}}}))
        self.set_fields({'groups': {'emails': {'mask': 'email'}}})
        build_snapshot(self.root)
        self.set_fields({'groups': True})
        self.invalid('select individual leaves')

    def test_version_matrix_query_body_bindings_and_response_masks(self):
        body = {'type': 'object', 'properties': {
            'requester': {'type': 'object', 'properties': {'email': {'type': 'string'}}},
            'code': {'type': 'integer'}}}
        for version in VERSIONS:
            with self.subTest(version=version):
                d = document_for(version)
                operation = {'responses': copy.deepcopy(d['paths']['/records/{id}']['get']['responses'])}
                if version == '2.0':
                    operation['parameters'] = [
                        {'in': 'query', 'name': 'nickname', 'type': 'string'},
                        {'in': 'body', 'name': 'payload', 'schema': body}]
                else:
                    operation['parameters'] = [{'in': 'query', 'name': 'nickname', 'schema': {'type': 'string'}}]
                    operation['requestBody'] = {'content': {'application/json': {'schema': body}}}
                d['paths']['/records/{id}']['post'] = operation
                self.write('openapi/compat-team/compat-api.json', d)
                generate(self.root, target='compat-team/compat-api')
                self.write('actions/compat.write.yaml', {'api-version': 'resource-ops/v1', 'kind': 'Action',
                    'metadata': {'name': 'compat.write', 'title': 'Write'},
                    'spec': {'endpoint': {'service': 'compat-api', 'method': 'POST', 'path': '/records/{id}'}}})
                rules = {'request': {'query': {'nickname': {'source': 'subject', 'field': 'nickname'}},
                                     'body': {'requester': {'email': {'source': 'subject', 'field': 'email'}},
                                              'code': {'source': 'scope', 'name': 'codes'}}},
                         'response': {'fields': {'id': True, 'label': {'mask': 'label'}}}}
                self.write('pages/compat.yaml', {'api-version': 'resource-ops/v1', 'kind': 'Page',
                    'metadata': {'name': 'compat', 'title': 'Write'},
                    'spec': {'path': '/compat', 'actions': [{'action': 'compat.write', **rules}]}})
                effective = self.effective(build_snapshot(self.root), 'compat', 'compat.write')
                self.assertEqual(effective['request']['rules'], rules['request'])
                self.assertEqual(effective['response'], rules['response'])
                self.assertEqual(self.read('services/compat-api.yaml')['spec']['swagger' if version == '2.0' else 'openapi'], version)
                self.assertNotIn('openapi-version', self.read('services/compat-api.yaml')['spec'])
