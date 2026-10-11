import copy

from catalog_test_base import *


ACTION = 'actions/members.detail.read.yaml'


class ActionPluginTests(Fixture):
    def set_plugins(self, plugins):
        self.change(ACTION, lambda d: d['spec'].update(plugins=plugins))

    def usages(self, snapshot):
        return [u for u in snapshot['pageActionUsages'] if u['action'] == 'members.detail.read']

    def test_plugins_are_optional_and_missing_phases_normalize_to_empty_arrays(self):
        for plugins in (None, {'before': [{'name': 'confirm'}]}, {'after': [{'name': 'history'}]}):
            with self.subTest(plugins=plugins):
                if plugins is not None:
                    self.set_plugins(plugins)
                snapshot = build_snapshot(self.root)
                for usage in self.usages(snapshot):
                    self.assertEqual(usage['plugins'], {phase: (plugins or {}).get(phase, [])
                                                       for phase in ('before', 'after')})

    def test_plugin_configuration_survives_snapshot_without_affecting_endpoint_contract(self):
        before = build_snapshot(self.root)
        plugins = {'before': [{'name': 'confirm', 'config': {'message': '확인하시겠습니까?'}}],
                   'after': [{'name': 'history', 'config': {'event': 'member.read',
                                                         'labels': ['member', 'detail']}}]}
        self.set_plugins(plugins)
        snapshot = build_snapshot(self.root)
        action = next(r for r in snapshot['resources'] if r['kind'] == 'Action'
                      and r['metadata']['name'] == 'members.detail.read')
        self.assertEqual(action['spec']['plugins'], plugins)
        self.assertEqual(snapshot['relations'], before['relations'])
        self.assertNotEqual(snapshot['contentSha256'], before['contentSha256'])
        usages = self.usages(snapshot)
        for usage, previous in zip(usages, self.usages(before)):
            self.assertEqual(usage['plugins'], plugins)
            self.assertEqual(usage['effective'], previous['effective'])
        self.assertEqual(snapshot, build_snapshot(self.root, verify_sources=False))
        usages[0]['plugins']['after'][0]['config']['labels'].append('changed')
        self.assertEqual(usages[1]['plugins'], plugins)
        self.assertEqual(action['spec']['plugins'], plugins)

    def test_wrong_phase_unknown_names_and_malformed_connections_are_rejected(self):
        invalid = [{}, {'before': []}, {'after': []}, {'during': [{'name': 'confirm'}]},
                   {'before': [{'name': 'history'}]}, {'after': [{'name': 'confirm'}]},
                   {'before': [{'name': 'unknown'}]}, {'before': ['confirm']},
                   {'before': [{}]}, {'before': [{'name': 'confirm', 'enabled': False}]},
                   {'after': [{'name': 'history', 'config': 'invalid'}]},
                   {'after': [{'name': 'history'}, {'name': 'history', 'config': {'event': 'other'}}]}]
        for plugins in invalid:
            with self.subTest(plugins=plugins):
                self.set_plugins(plugins)
                with self.assertRaises(CatalogError):
                    build_snapshot(self.root)

    def test_unpaged_action_plugins_are_validated(self):
        for page in ('members', 'member-detail'):
            self.change(f'pages/{page}.yaml', lambda d: d['spec'].update(
                actions=[u for u in d['spec']['actions'] if u['action'] != 'members.detail.read']))
        self.set_plugins({'before': [{'name': 'history'}]})
        with self.assertRaises(CatalogError):
            build_snapshot(self.root)

    def test_page_cannot_override_or_disable_plugins(self):
        for placement in ('usage', 'overrides'):
            with self.subTest(placement=placement):
                original = self.read('pages/members.yaml')
                self.change_usage('members', 'members.detail.read', lambda u:
                                  (u if placement == 'usage' else u['overrides']).update(plugins={}))
                self.invalid('Additional properties')
                self.write('pages/members.yaml', original)

    def test_flat_endpoint_fields_and_inline_contracts_are_rejected(self):
        original = self.read(ACTION)
        variants = [copy.deepcopy(original['spec']['endpoint']), {'plugins': {'before': [{'name': 'confirm'}]}}]
        for field in ('request', 'responses'):
            spec = copy.deepcopy(original['spec'])
            spec['endpoint'][field] = {}
            variants.append(spec)
        for spec in variants:
            with self.subTest(spec=spec):
                self.change(ACTION, lambda d: d.update(spec=spec))
                with self.assertRaises(CatalogError):
                    build_snapshot(self.root)
