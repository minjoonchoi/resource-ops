import subprocess

from catalog_test_base import *

TARGET = 'member-team/member-api'
GENERATOR = Path(__file__).resolve().parents[1] / 'scripts/generate_services.py'


class TargetConversionTests(Fixture):
    def cli(self, *args):
        return subprocess.run([sys.executable, str(GENERATOR), '--root', str(self.root), *args], capture_output=True, text=True)

    def test_no_selection_and_ambiguous_selection_require_explicit_choice(self):
        before = (self.root / SERVICE).read_bytes()
        for args in ([], ['--check'], [TARGET, '--all']):
            result = self.cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertIn('provide exactly one', result.stderr)
        self.assertEqual(before, (self.root / SERVICE).read_bytes())

    def test_target_cli_updates_only_selected_service(self):
        self.write('openapi/other-team/other-api.json', self.read(SOURCE))
        generate(self.root)
        before = (self.root / 'services/other-api.yaml').read_bytes()
        other_mtime = (self.root / 'services/other-api.yaml').stat().st_mtime_ns
        self.change(SOURCE, lambda d: d['info'].update(version='2.0'))
        result = self.cli(TARGET)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read(SERVICE)['spec']['openapi']['info']['version'], '2.0')
        self.assertEqual(before, (self.root / 'services/other-api.yaml').read_bytes())
        self.assertEqual(other_mtime, (self.root / 'services/other-api.yaml').stat().st_mtime_ns)

    def test_unrelated_bad_json_is_not_parsed_or_registered(self):
        self.write('openapi/other-team/other-api.json', {'broken': True})
        result = self.cli(TARGET)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / 'services/other-api.yaml').exists())
        self.assertNotEqual(self.cli('--all', '--check').returncode, 0)

    def test_target_does_not_overwrite_unrelated_stale_output_or_prune_orphans(self):
        self.write('openapi/other-team/other-api.json', self.read(SOURCE))
        generate(self.root)
        (self.root / 'openapi/other-team/other-api.json').unlink()
        self.change('services/other-api.yaml', lambda d: d['metadata'].update(title='manual'))
        before = (self.root / 'services/other-api.yaml').read_bytes()
        self.assertEqual(self.cli(TARGET).returncode, 0)
        self.assertEqual(before, (self.root / 'services/other-api.yaml').read_bytes())

    def test_target_creates_missing_output_and_registers_it(self):
        self.write('openapi/other-team/other-api.json', self.read(SOURCE))
        result = self.cli('other-team/other-api')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / 'services/other-api.yaml').is_file())
        generate(self.root, 'check')

    def test_target_check_and_ci_mode_do_not_overwrite_existing_yaml(self):
        self.change(SERVICE, lambda d: d['metadata'].update(title='manual'))
        before = (self.root / SERVICE).read_bytes()
        for flag in ('--check', '--create-missing'):
            result = self.cli(TARGET, flag)
            self.assertEqual(result.returncode, 1)
            self.assertIn('generated files differ', result.stderr)
        self.assertEqual(before, (self.root / SERVICE).read_bytes())

    def test_invalid_targets_and_missing_source_do_not_write(self):
        before = (self.root / SERVICE).read_bytes()
        for target in ('../member-api', 'member-team/../member-api', '/tmp/member-api',
                       'member-api', 'member-team/member-api.json', 'member-team/missing'):
            with self.subTest(target=target):
                self.assertEqual(self.cli(target).returncode, 1)
        self.assertEqual(before, (self.root / SERVICE).read_bytes())

    def test_selected_service_still_rejects_cross_organization_name_collision(self):
        self.write('openapi/other-team/member-api.json', self.read(SOURCE))
        result = self.cli(TARGET)
        self.assertEqual(result.returncode, 1)
        self.assertIn('duplicate service filename', result.stderr)

    def test_explicit_all_mode_remains_available_for_ci(self):
        (self.root / SERVICE).unlink()
        result = self.cli('--all', '--create-missing')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.cli('--all', '--check').returncode, 0)
