import copy

from catalog_test_base import *
from openapi_catalog import make_service, schema_accepts, version_family

FIXTURES = Path(__file__).parent / 'fixtures/openapi'
VERSIONS = ['2.0', '3.0.0', '3.0.1', '3.0.2', '3.0.3', '3.0.4',
            '3.1.0', '3.1.1', '3.1.2', '3.2.0', '3.2.1']


def document_for(version):
    files = {'2.0': 'swagger-2.0.json', '3.0': 'openapi-3.0.4.json',
             '3.1': 'openapi-3.1.2.json', '3.2': 'openapi-3.2.1.json'}
    family = version if version == '2.0' else version[:3]
    document = json.loads((FIXTURES / files[family]).read_text())
    document['swagger' if family == '2.0' else 'openapi'] = version
    return document


class VersionTests(Fixture):
    def import_version(self, version):
        document = document_for(version)
        self.write('openapi/compat-team/compat-api.json', document)
        generate(self.root, target='compat-team/compat-api')
        self.assertEqual(self.read('services/compat-api.yaml')['spec']['openapi'], document)
        return document

    def add_usage(self, method='GET', path='/records/{id}', overrides=None):
        self.write('actions/compat.read.yaml', {
            'apiVersion': 'resource-ops/v1', 'kind': 'Action',
            'metadata': {'name': 'compat.read', 'title': 'Read record'},
            'spec': {'service': 'compat-api', 'method': method, 'path': path}})
        usage = {'action': 'compat.read'}
        if overrides:
            usage['overrides'] = overrides
        self.write('pages/compat.yaml', {'apiVersion': 'resource-ops/v1', 'kind': 'Page',
                   'metadata': {'name': 'compat', 'title': 'Records'},
                   'spec': {'path': '/compat', 'actions': [usage]}})
        generate(self.root, target='compat-team/compat-api')
        return self.effective(build_snapshot(self.root), 'compat', 'compat.read')

    def test_published_version_matrix_generation_and_page_projection(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                self.import_version(version)
                effective = self.add_usage(overrides={'responses': {'200': {'fields': ['/id']}}})
                self.assertEqual(effective['responses']['200']['fields'], ['/id'])
                before = (self.root / 'services/compat-api.yaml').read_bytes()
                generate(self.root, 'check', 'compat-team/compat-api')
                generate(self.root, 'create-missing', 'compat-team/compat-api')
                self.assertEqual(before, (self.root / 'services/compat-api.yaml').read_bytes())

    def test_patch_version_uses_family_rules_without_rewriting_input(self):
        for version in ('3.0.99', '3.1.99', '3.2.99'):
            with self.subTest(version=version):
                self.import_version(version)

    def test_version_detection_ignores_business_info_version(self):
        d = document_for('3.1.2')
        d['info']['version'] = '99.0.0'
        self.assertEqual(version_family(d), '3.1')

    def test_missing_ambiguous_and_future_minor_versions_fail_before_writes(self):
        before = (self.root / SERVICE).read_bytes()
        for document in ({'info': {'version': '3.0.3'}}, {'swagger': '1.2'},
                         {'openapi': '3.3.0'}, {'openapi': '4.0.0'},
                         {'openapi': 3.1}, {'swagger': '2.0', 'openapi': '3.0.4'}):
            with self.subTest(document=document):
                self.write('openapi/compat-team/compat-api.json', document)
                with self.assertRaisesRegex(CatalogError, 'spec version|not both'):
                    generate(self.root, target='compat-team/compat-api')
                self.assertEqual(before, (self.root / SERVICE).read_bytes())
                self.assertFalse((self.root / 'services/compat-api.yaml').exists())

    def test_nullable_and_exclusive_minimum_follow_version_semantics(self):
        for version in VERSIONS:
            with self.subTest(version=version):
                d = self.import_version(version)
                if version == '2.0':
                    schema = {'type': 'integer', 'minimum': 1, 'exclusiveMinimum': True}
                elif version.startswith('3.0.'):
                    schema = {'type': 'integer', 'nullable': True, 'minimum': 1, 'exclusiveMinimum': True}
                else:
                    schema = {'type': ['integer', 'null'], 'exclusiveMinimum': 1}
                self.assertTrue(schema_accepts(d, schema, 2))
                self.assertFalse(schema_accepts(d, schema, 1))
                self.assertEqual(schema_accepts(d, schema, None), version != '2.0')

    def test_swagger_body_and_definitions_are_preserved(self):
        self.import_version('2.0')
        effective = self.add_usage('PUT')
        self.assertTrue(effective['request']['body']['required'])
        schema = effective['request']['body']['content']['application/json']['schema']
        self.assertEqual(schema, {'$ref': '#/definitions/Record'})
        self.assertEqual(effective['service']['servers'], [{'url': 'https://legacy.example.invalid/api'}])

    def test_swagger_form_files_and_collection_format_are_preserved(self):
        self.import_version('2.0')
        effective = self.add_usage('POST', '/upload')
        body = effective['request']['body']
        schema = body['content']['multipart/form-data']['schema']
        self.assertEqual(schema['properties']['file'], {'type': 'string', 'format': 'binary'})
        self.assertEqual(body['x-swagger-form-parameters'][1]['collectionFormat'], 'multi')
        self.assertEqual(effective['service']['servers'], [{'url': 'http://legacy.example.invalid/api'}])

    def test_swagger_produces_override_and_unspecified_server_not_invented(self):
        d = self.import_version('2.0')
        d.pop('host')
        d.pop('schemes')
        d['paths']['/records/{id}']['get']['produces'] = ['application/xml']
        self.write('openapi/compat-team/compat-api.json', d)
        generate(self.root, target='compat-team/compat-api')
        effective = self.add_usage()
        self.assertEqual(set(effective['responses']['200']['content']), {'application/xml'})
        self.assertEqual(effective['service']['servers'], [{'url': '/api'}])
        self.assertIsNone(effective['service']['swaggerServer']['host'])

    def test_swagger_missing_mime_types_does_not_assume_json(self):
        d = self.import_version('2.0')
        d.pop('produces')
        self.write('openapi/compat-team/compat-api.json', d)
        generate(self.root, target='compat-team/compat-api')
        effective = self.add_usage()
        self.assertEqual(set(effective['responses']['200']['content']), {'*/*'})

    def test_reference_sibling_constraints_are_checked_in_31_and_32(self):
        for version in ('3.1.2', '3.2.1'):
            d = self.import_version(version)
            schema = {'$ref': '#/components/schemas/Label', 'maxLength': 5}
            self.assertTrue(schema_accepts(d, schema, 'hello'))
            self.assertFalse(schema_accepts(d, schema, 'hi'))
            self.assertFalse(schema_accepts(d, schema, 'too long'))

    def test_boolean_schema_is_not_treated_as_a_dictionary(self):
        for version in ('3.1.2', '3.2.1'):
            d = self.import_version(version)
            self.assertTrue(schema_accepts(d, True, {'any': 'value'}))
            self.assertFalse(schema_accepts(d, False, 'value'))

    def test_32_query_and_stream_schema_are_preserved(self):
        self.import_version('3.2.1')
        effective = self.add_usage('QUERY', '/search')
        self.assertEqual(effective['request']['parameters'][0]['in'], 'querystring')
        self.assertIn('itemSchema', effective['responses']['200']['content']['application/jsonl'])

    def test_32_custom_method_case_sensitive_matching_and_identity(self):
        self.import_version('3.2.1')
        upper = self.add_usage('COPY', '/search')
        upper_id = next(u['endpoint'] for u in build_snapshot(self.root)['pageActionUsages'] if u['page'] == 'compat')
        lower = self.add_usage('copy', '/search')
        lower_id = next(u['endpoint'] for u in build_snapshot(self.root)['pageActionUsages'] if u['page'] == 'compat')
        self.assertEqual(upper['method'], 'COPY')
        self.assertEqual(lower['method'], 'copy')
        self.assertNotEqual(upper_id, lower_id)
        with self.assertRaisesRegex(CatalogError, 'no registered Endpoint'):
            self.add_usage('Copy', '/search')

    def test_new_feature_is_not_silently_accepted_under_old_version(self):
        d = document_for('3.2.1')
        d['openapi'] = '3.0.4'
        with self.assertRaisesRegex(CatalogError, 'invalid OpenAPI'):
            make_service(d, 'compat-team', 'compat-api', 'openapi/compat-team/compat-api.json')

    def test_32_operation_without_responses_is_supported(self):
        d = self.import_version('3.2.1')
        d['paths']['/search']['query'].pop('responses')
        self.write('openapi/compat-team/compat-api.json', d)
        generate(self.root, target='compat-team/compat-api')
        self.assertEqual(self.add_usage('QUERY', '/search')['responses'], {})
