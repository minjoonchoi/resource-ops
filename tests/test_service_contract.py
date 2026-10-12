import copy
import shutil
import sqlite3
from unittest.mock import patch

from jsonschema_path import SchemaPath
from openapi_spec_validator import validate

from catalog_test_base import *
from openapi_catalog import make_service, schema_accepts
from service_contract import schema_document
from test_openapi_versions import VERSIONS, document_for


class ServiceContractTests(Fixture):
    def test_documentation_and_unused_components_do_not_change_generated_bytes(self):
        before = (self.root / SERVICE).read_bytes()
        def edit(d):
            d['info'].update(description='Documentation', contact={'name': 'Team'})
            d['tags'] = [{'name': 'changed'}]
            d['components']['schemas']['Unused'] = {'type': 'string'}
            member = d['components']['schemas']['Member']
            member.update(title='Document title', description='Changed', example={})
            op = d['paths'][DETAIL]['get']
            op.update(operationId='renamed', tags=['changed'], externalDocs={'url': 'https://example.invalid/docs'})
        self.change(SOURCE, edit)
        generate(self.root, 'check')
        self.assertEqual(before, (self.root / SERVICE).read_bytes())

    def test_spec_is_direct_library_input_after_yaml_and_database_reload(self):
        # This proves the persisted format, not a DB reconciler implementation.
        with sqlite3.connect(':memory:') as database:
            database.execute('CREATE TABLE service (name TEXT PRIMARY KEY, resource TEXT NOT NULL)')
            for version in VERSIONS:
                with self.subTest(version=version):
                    source = document_for(version)
                    source['info']['version'] = 'release-42'
                    service = make_service(source, 'team', 'api', 'test.json')
                    parsed = yaml.safe_load(yaml.safe_dump(service))
                    database.execute('INSERT OR REPLACE INTO service VALUES (?, ?)',
                                     ('api', json.dumps(parsed)))
                    reloaded = json.loads(database.execute('SELECT resource FROM service WHERE name = ?',
                                                          ('api',)).fetchone()[0])
                    spec = reloaded['spec']
                    # No validation_document/rebasing wrapper or source JSON is involved.
                    validate(spec)
                    self.assertEqual(spec['info'], source['info'])
                    self.assertIs(schema_document(reloaded), spec)
                    tokens = ['paths', '/records/{id}', 'get', 'responses', '200']
                    tokens += ['schema'] if version == '2.0' else ['content', 'application/json', 'schema']
                    resolved = SchemaPath.from_dict(spec, *tokens, handlers={}).read_value()
                    self.assertEqual(resolved['properties']['id'], {'type': 'integer'})
                    registry = spec['definitions'] if version == '2.0' else spec['components']['schemas']
                    self.assertEqual(resolved, registry['Record'])
                    self.assertEqual(list(extract_endpoints(reloaded)), list(extract_endpoints(service)))
                    self.assertEqual(spec['paths']['/records/{id}']['get']['responses']['200']['description'],
                                     SchemaPath.from_dict(source, 'paths', '/records/{id}', 'get', 'responses',
                                                          '200', handlers={}).read_value()['description'])

    def test_transitive_recursive_refs_are_closed_and_preserve_literal_data(self):
        literal = {'$ref': 'https://example.invalid/data', '$id': 'literal', 'description': 'keep me'}
        def edit(d):
            d['openapi'] = '3.1.2'
            schemas = d['components']['schemas']
            schemas['Node'] = {'type': 'object', 'properties': {
                'next': {'$ref': '#/components/schemas/Node'},
                'description': {'type': 'string'},
                'default': {'$ref': '#/components/schemas/Label'}}}
            schemas['Label'] = {'type': 'string', 'minLength': 2, 'description': 'discard'}
            schemas['Unused'] = {'type': 'boolean'}
            schemas['Member']['properties'].update(
                node={'$ref': '#/components/schemas/Node'},
                data={'type': 'object', 'default': literal, 'enum': [literal], 'const': literal},
                **{name: {'type': 'string'} for name in ('title', 'example', 'examples', '$ref', 'default')})
        with patch('jsonschema_path.retrievers.SchemaRetriever.__call__',
                   side_effect=AssertionError('validation must stay offline')):
            self.change_api(edit)
        s = self.read(SERVICE)
        self.assertEqual(set(s['spec']['components']['schemas']), {'Member', 'Node', 'Label'})
        self.assertEqual(s['spec']['components']['schemas']['Node']['properties']['next'], {'$ref': '#/components/schemas/Node'})
        self.assertEqual(s['spec']['components']['schemas']['Member']['properties']['data']['default'], literal)
        self.assertNotIn('description', s['spec']['components']['schemas']['Label'])
        shutil.rmtree(self.root / 'openapi')
        build_snapshot(self.root, verify_sources=False)

    def test_nested_and_percent_encoded_named_refs_keep_exact_targets(self):
        d = document_for('3.1.2')
        d['components']['schemas']['Rate'] = {'type': 'object', 'properties': {'a/b%': {'type': 'string'}}}
        d['components']['schemas']['Record']['properties']['rate'] = {
            '$ref': '#/components/schemas/Rate/properties/a~1b%25'}
        s = make_service(d, 'team', 'api', 'test.json')
        ref = s['spec']['components']['schemas']['Record']['properties']['rate']
        self.assertEqual(ref, {'$ref': '#/components/schemas/Rate/properties/a~1b%25'})
        self.assertTrue(schema_accepts(schema_document(s), ref, 'ok'))
        self.assertFalse(schema_accepts(schema_document(s), ref, 1))

    def test_server_security_and_parameter_inheritance_are_materialized(self):
        def edit(d):
            d['servers'] = [{'url': 'https://{zone}.example.invalid', 'description': 'drop',
                             'variables': {'zone': {'default': 'eu', 'enum': ['eu', 'us'], 'description': 'drop'}}}]
            d['components']['securitySchemes'] = {
                'Token': {'type': 'http', 'scheme': 'bearer', 'description': 'drop'},
                'Unused': {'type': 'apiKey', 'in': 'header', 'name': 'X-Key'}}
            d['security'] = [{'Token': []}]
            d['paths'][DETAIL]['servers'] = [{'url': 'https://detail.example.invalid'}]
            d['paths'][LIST]['get']['security'] = []
        self.change_api(edit)
        s = self.read(SERVICE)['spec']
        self.assertEqual(set(s['components']['securitySchemes']), {'Token'})
        detail = s['paths'][DETAIL]['get']
        listing = s['paths'][LIST]['get']
        self.assertEqual(detail['security'], [{'Token': []}])
        self.assertEqual(listing['security'], [])
        self.assertEqual(detail['servers'], [{'url': 'https://detail.example.invalid'}])
        self.assertNotIn('servers', listing)
        self.assertNotIn('description', s['servers'][0]['variables']['zone'])
        build_snapshot(self.root, verify_sources=False)

    def test_shared_request_response_header_and_encoding_refs_are_resolved(self):
        d = document_for('3.0.4')
        d['components'].update(
            headers={'Trace': {'description': 'drop', 'schema': {'type': 'string'}}},
            requestBodies={'Upload': {'required': True, 'content': {'multipart/form-data': {
                'schema': {'type': 'object', 'properties': {'file': {'type': 'string', 'format': 'binary'}}},
                'encoding': {'file': {'contentType': 'image/png', 'headers': {'X-Trace': {'$ref': '#/components/headers/Trace'}}}}}}}})
        d['paths']['/upload'] = {'post': {'requestBody': {'$ref': '#/components/requestBodies/Upload'},
            'responses': {'204': {'description': 'done', 'headers': {'X-Trace': {'$ref': '#/components/headers/Trace'}}}}}}
        s = make_service(d, 'team', 'api', 'test.json')
        endpoint = s['spec']['paths']['/upload']['post']
        body = endpoint['requestBody']
        self.assertTrue(body['required'])
        self.assertEqual(body['content']['multipart/form-data']['encoding']['file'], {
            'contentType': 'image/png', 'headers': {'X-Trace': {'schema': {'type': 'string'}}}})
        self.assertEqual(endpoint['responses']['204']['headers']['X-Trace'], {'schema': {'type': 'string'}})
        self.assertNotIn('requestBodies', s['spec']['components'])
        self.assertNotIn('headers', s['spec']['components'])

    def test_generated_only_schema_and_contract_tampering_is_rejected(self):
        original = self.read(SERVICE)
        changes = [
            lambda s: s['spec']['components']['schemas']['Member']['properties']['id'].update(type='invalid'),
            lambda s: s['spec']['paths'][LIST]['get']['parameters'][0].update(style='invalid'),
            lambda s: s['spec']['components']['schemas']['Member']['properties'].update(x={'$ref': '#/components/schemas/Missing'}),
            lambda s: s['spec']['components']['schemas'].update(Unused={'type': 'string'}),
            lambda s: s['spec']['paths'][LIST]['get'].update(security=[{'Missing': []}]),
        ]
        for edit in changes:
            with self.subTest(edit=edit):
                changed = copy.deepcopy(original)
                edit(changed)
                self.write(SERVICE, changed)
                with self.assertRaises(CatalogError):
                    build_snapshot(self.root, verify_sources=False)

    def test_native_format_keeps_catalog_route_restrictions_without_sources(self):
        # Native OpenAPI path patterns alone do not reject query/fragment/authority paths.
        original = self.read(SERVICE)
        for path in ('//other-host/members', '/members?limit=1', '/members#detail', '/with space'):
            with self.subTest(path=path):
                changed = copy.deepcopy(original)
                changed['spec']['paths'][path] = changed['spec']['paths'].pop(LIST)
                self.write(SERVICE, changed)
                with self.assertRaises(CatalogError):
                    build_snapshot(self.root, verify_sources=False)

    def test_32_nested_multipart_encoding_is_not_discarded(self):
        d = document_for('3.2.1')
        content = {'multipart/mixed': {
            'schema': {'type': 'array', 'prefixItems': [
                {'type': 'object', 'properties': {'payload': {'type': 'string'}}},
                {'type': 'array', 'items': {'type': 'string'}}],
                'items': {'type': 'array', 'items': {'type': 'string'}}},
            'prefixEncoding': [
                {'contentType': 'multipart/form-data', 'encoding': {'payload': {'contentType': 'text/plain'}}},
                {'contentType': 'multipart/mixed', 'prefixEncoding': [{'contentType': 'text/html'}],
                 'itemEncoding': {'contentType': 'text/plain'}}],
            'itemEncoding': {'contentType': 'multipart/mixed', 'itemEncoding': {'contentType': 'text/plain'}}}}
        d['paths']['/batch'] = {'post': {'requestBody': {'content': content}, 'responses': {'204': {'description': 'OK'}}}}
        self.write('openapi/team/batch-api.json', d)
        generate(self.root, target='team/batch-api')
        s = self.read('services/batch-api.yaml')
        e = s['spec']['paths']['/batch']['post']
        self.assertEqual(e['requestBody']['content'], content)
        build_snapshot(self.root, verify_sources=False)

    def test_external_refs_are_preflighted_in_media_and_headers_before_validation(self):
        d = document_for('3.2.1')
        d['paths']['/upload'] = {'post': {'responses': {'200': {'description': 'OK',
            'content': {'application/json': {'$ref': 'https://example.invalid/media'}}}}}}
        with patch('openapi_catalog.validate_offline', side_effect=AssertionError('must not reach validator')):
            with self.assertRaisesRegex(CatalogError, 'bundle external references'):
                make_service(d, 'team', 'api', 'test.json')

    def test_swagger_native_form_and_hostless_scheme_are_preserved(self):
        d = document_for('2.0')
        d.pop('host')
        s = make_service(d, 'team', 'api', 'test.json')
        self.assertEqual(s['spec']['schemes'], ['https'])
        self.assertEqual(s['spec']['basePath'], '/api')
        self.assertNotIn('servers', s['spec'])
        upload = s['spec']['paths']['/upload']['post']
        self.assertEqual(upload['parameters'], d['paths']['/upload']['post']['parameters'])
        endpoint = next(e for e in extract_endpoints(s) if e['spec']['path'] == '/records/{id}')
        self.assertEqual(endpoint['spec']['operation']['servers'], [{'url': '/api', 'schemes': ['https']}])

    def test_unsupported_schema_dialect_and_keywords_fail_without_writes(self):
        before = (self.root / SERVICE).read_bytes()
        for field, value in [('unknownConstraint', 1), ('$schema', 'https://example.invalid/dialect')]:
            d = document_for('3.1.2')
            d['components']['schemas']['Record'][field] = value
            self.write('openapi/team/custom.json', d)
            with self.assertRaisesRegex(CatalogError, 'unsupported schema|Unknown JSON Schema dialect'):
                generate(self.root, target='team/custom')
            self.assertFalse((self.root / 'services/custom.yaml').exists())
            self.assertEqual(before, (self.root / SERVICE).read_bytes())

    def test_discriminator_keeps_explicit_and_implicit_subtypes(self):
        for version in ('2.0', '3.0.4', '3.1.2', '3.2.1'):
            with self.subTest(version=version):
                d = document_for(version)
                registry = d['definitions'] if version == '2.0' else d['components']['schemas']
                prefix = '#/definitions/' if version == '2.0' else '#/components/schemas/'
                registry['Record']['properties']['kind'] = {'type': 'string'}
                registry['Record']['required'] = ['id', 'kind']
                registry['Record']['discriminator'] = 'kind' if version == '2.0' else {'propertyName': 'kind'}
                registry['Child'] = {'allOf': [{'$ref': prefix + 'Record'}, {'type': 'object', 'properties': {'extra': {'type': 'string'}}}]}
                registry['Unused'] = {'type': 'string'}
                if version != '2.0':
                    registry['Record']['discriminator']['mapping'] = {'explicit': 'Mapped'}
                    registry['Mapped'] = {'type': 'object'}
                s = make_service(d, 'team', 'api', 'test.json')
                selected = s['spec']['definitions'] if version == '2.0' else s['spec']['components']['schemas']
                self.assertIn('Child', selected)
                self.assertNotIn('Unused', selected)
                if version != '2.0':
                    self.assertIn('Mapped', selected)
                    self.assertEqual(selected['Record']['discriminator']['mapping'], {'explicit': '#/components/schemas/Mapped'})
