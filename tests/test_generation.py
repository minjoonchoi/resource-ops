import copy
import subprocess
from unittest.mock import patch

from catalog_test_base import *
from generate_services import HEADER


class GenerationTests(Fixture):
    def fail_generation(self, pattern, mode='create-missing'):
        with self.assertRaisesRegex(CatalogError, pattern):
            generate(self.root, mode)

    def test_organization_filename_and_openapi_preservation(self):
        service = self.read(SERVICE)
        self.assertEqual(service['metadata']['name'], 'member-api')
        self.assertEqual(service['metadata']['organization'], 'member-team')
        self.assertEqual(service['spec']['openapi'], self.read(SOURCE))
        self.assertNotIn('source', service['spec'])
        self.assertEqual(len(service['spec']['endpoints']), 2)

    def test_new_service_auto_creation_matches_local_generation(self):
        expected = (self.root / SERVICE).read_bytes()
        (self.root / SERVICE).unlink()
        self.assertIn(SERVICE, generate(self.root, 'create-missing'))
        self.assertEqual(expected, (self.root / SERVICE).read_bytes())
        self.assertEqual([], generate(self.root, 'create-missing'))
        self.assertEqual([], generate(self.root))

    def test_existing_service_is_not_rewritten_or_touched(self):
        path = self.root / SERVICE
        before = path.stat().st_mtime_ns
        self.assertEqual([], generate(self.root, 'create-missing'))
        self.assertEqual(before, path.stat().st_mtime_ns)

    def test_tampering_is_rejected_without_overwrite(self):
        self.change(SERVICE, lambda d: d['metadata'].update(organization='wrong-team'))
        before = (self.root / SERVICE).read_bytes()
        self.fail_generation('generated files differ')
        self.assertEqual(before, (self.root / SERVICE).read_bytes())

    def test_format_only_edits_are_also_reported(self):
        with (self.root / SERVICE).open('a') as f:
            f.write('# manual change\n')
        self.fail_generation('generated files differ')

    def test_changed_openapi_requires_local_regeneration(self):
        before = (self.root / SERVICE).read_bytes()
        self.change(SOURCE, lambda d: d['info'].update(version='2.0.0'))
        self.fail_generation('run: python scripts/generate_services.py')
        self.assertEqual(before, (self.root / SERVICE).read_bytes())
        generate(self.root)
        generate(self.root, 'check')
        self.assertNotEqual(before, (self.root / SERVICE).read_bytes())

    def test_missing_yaml_in_check_mode_does_not_create_it(self):
        (self.root / SERVICE).unlink()
        self.fail_generation('missing=.*member-api', 'check')
        self.assertFalse((self.root / SERVICE).exists())

    def test_source_key_order_whitespace_do_not_change_outputs(self):
        before = (self.root / SERVICE).read_bytes()
        api = self.read(SOURCE)
        self.write(SOURCE, dict(reversed(list(api.items()))))
        self.assertEqual([], generate(self.root, 'check'))
        self.assertEqual(before, (self.root / SERVICE).read_bytes())

    def test_duplicate_service_names_across_organizations_fail(self):
        self.write('openapi/other-team/member-api.json', self.read(SOURCE))
        self.fail_generation('duplicate service filename')

    def test_organization_directory_name_is_copied_exactly(self):
        new = 'openapi/회원개발팀/member-api.json'
        self.write(new, self.read(SOURCE))
        (self.root / SOURCE).unlink()
        generate(self.root)
        self.assertEqual(self.read(SERVICE)['metadata']['organization'], '회원개발팀')
        self.assertTrue(all(e['metadata']['organization'] == '회원개발팀' for e in self.read(SERVICE)['spec']['endpoints']))

    def test_new_service_manifest_registration(self):
        self.write('openapi/other-team/other-api.json', self.read(SOURCE))
        changed = generate(self.root, 'create-missing')
        self.assertEqual(set(changed), {'services/other-api.yaml', 'catalog/manifest.yaml'})
        self.assertIn('services/other-api.yaml', self.read('catalog/manifest.yaml')['resources'])

    def test_author_added_action_is_registered_without_modification(self):
        action = self.read('actions/members.detail.read.yaml')
        action['metadata']['name'] = 'members.other.read'
        self.write('actions/members.other.read.yaml', action)
        before = (self.root / 'actions/members.other.read.yaml').read_bytes()
        generate(self.root, 'create-missing')
        build_snapshot(self.root)
        self.assertEqual(before, (self.root / 'actions/members.other.read.yaml').read_bytes())

    def test_orphan_yaml_fails_ci_and_local_regeneration_removes_it(self):
        self.write('openapi/other-team/other-api.json', self.read(SOURCE))
        generate(self.root)
        (self.root / 'openapi/other-team/other-api.json').unlink()
        self.fail_generation('orphaned=.*other-api')
        self.assertTrue((self.root / 'services/other-api.yaml').exists())
        generate(self.root)
        self.assertFalse((self.root / 'services/other-api.yaml').exists())

    def test_foreign_file_is_not_deleted_by_generator(self):
        self.write('services/manual.yaml', {'manual': True})
        self.fail_generation('refusing to delete', 'write')

    def test_empty_openapi_tree_is_not_delete_all(self):
        (self.root / SOURCE).unlink()
        self.fail_generation('at least one OpenAPI service', 'write')
        self.assertTrue((self.root / SERVICE).exists())

    def test_nested_or_root_sources_are_rejected(self):
        for path in ('openapi/other.json', 'openapi/team/nested/other.json'):
            with self.subTest(path=path):
                self.write(path, self.read(SOURCE))
                self.fail_generation('expected openapi/')
                (self.root / path).unlink()

    def test_invalid_service_name_and_config_profile_suffix(self):
        for name in ('MemberApi', 'member-default'):
            with self.subTest(name=name):
                path = f'openapi/team/{name}.json'
                self.write(path, self.read(SOURCE))
                self.fail_generation('invalid service filename')
                (self.root / path).unlink()

    def test_duplicate_json_keys_are_rejected(self):
        (self.root / SOURCE).write_text('{"openapi":"3.0.3","openapi":"3.1.0"}')
        self.fail_generation('duplicate JSON key')

    def test_nonfinite_json_is_rejected(self):
        (self.root / SOURCE).write_text('{"x": NaN}')
        self.fail_generation('non-finite JSON')

    def test_no_partial_creation_when_any_source_or_output_is_invalid(self):
        self.write('openapi/team/another-api.json', self.read(SOURCE))
        self.change(SERVICE, lambda d: d['metadata'].update(title='manual'))
        self.fail_generation('generated files differ')
        self.assertFalse((self.root / 'services/another-api.yaml').exists())

    def test_json_and_output_symlinks_are_rejected(self):
        for relative in (SOURCE, SERVICE):
            with self.subTest(relative=relative):
                path = self.root / relative
                original = path.read_bytes()
                path.unlink()
                path.symlink_to(self.root / 'outside')
                self.fail_generation('symlinks')
                path.unlink()
                path.write_bytes(original)

    def test_external_refs_rejected_before_validator_or_network(self):
        for ref in ('https://example.invalid/spec.json', '../spec.json', 'file:///etc/passwd'):
            with self.subTest(ref=ref):
                self.change(SOURCE, lambda d: d['components']['schemas'].update(Member={'$ref': ref}))
                with patch('openapi_catalog.validate') as validate:
                    self.fail_generation('bundle external references')
                    validate.assert_not_called()

    def test_missing_internal_ref_is_rejected(self):
        self.change(SOURCE, lambda d: d['components']['schemas'].update(Member={'$ref': '#/components/schemas/Missing'}))
        self.fail_generation('unresolved')

    def test_openapi_required_fields_are_validated(self):
        self.change(SOURCE, lambda d: d['info'].pop('version'))
        self.fail_generation('invalid OpenAPI')

    def test_missing_and_camelcase_operation_id_do_not_block_import(self):
        def edit(d):
            d['paths'][LIST]['get'].pop('operationId')
            d['paths'][DETAIL]['get']['operationId'] = 'getMemberById'
        before = [e['metadata']['name'] for e in self.read(SERVICE)['spec']['endpoints']]
        self.change_api(edit)
        self.assertEqual(before, [e['metadata']['name'] for e in self.read(SERVICE)['spec']['endpoints']])
        build_snapshot(self.root)

    def test_duplicate_operation_ids_are_rejected(self):
        self.change(SOURCE, lambda d: d['paths'][DETAIL]['get'].update(operationId='members.list'))
        self.fail_generation('invalid OpenAPI')

    def test_route_collision_with_different_parameter_names_is_rejected(self):
        def edit(d):
            operation = copy.deepcopy(d['paths'][DETAIL])
            operation['get']['operationId'] = 'other'
            operation['get']['parameters'][0]['name'] = 'id'
            d['paths']['/v1/members/{id}'] = operation
        self.change(SOURCE, edit)
        self.fail_generation('duplicate method/path')

    def test_spring_placeholder_even_json_escaped_is_rejected(self):
        text = (self.root / SOURCE).read_text().replace('회원 API', '\\u0024{PLACEHOLDER}')
        (self.root / SOURCE).write_text(text)
        self.fail_generation('Spring placeholders')

    def test_boolean_like_strings_and_status_codes_roundtrip(self):
        self.change_api(lambda d: d['info'].update(title='on', description='2026-10-11'))
        self.assertEqual(self.read(SERVICE)['spec']['openapi'], self.read(SOURCE))
        build_snapshot(self.root)

    def test_cli_exit_code_and_consumer_snapshot(self):
        scripts = Path(__file__).resolve().parents[1] / 'scripts'
        result = subprocess.run([sys.executable, str(scripts / 'generate_services.py'), '--root', str(self.root), '--all', '--check'], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.change(SERVICE, lambda d: d['metadata'].update(title='bad'))
        result = subprocess.run([sys.executable, str(scripts / 'generate_services.py'), '--root', str(self.root), '--all', '--check'], capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b'generated files differ', result.stderr)
