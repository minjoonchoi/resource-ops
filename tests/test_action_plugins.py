import copy

from catalog_test_base import *


ACTION = 'actions/members.detail.read.yaml'


def confirm_plugin():
    return {'name': 'confirm', 'config': {
        'pool': {'users': ['reviewer-a']},
        'count': 1, 'execution': 'requester'}}


class ActionPluginTests(Fixture):
    def set_plugins(self, plugins):
        self.change(ACTION, lambda d: d['spec'].update(plugins=plugins))

    def usages(self, snapshot):
        return [u for u in snapshot['pageActionUsages'] if u['action'] == 'members.detail.read']

    def test_plugins_are_optional_and_missing_phases_normalize_to_empty_arrays(self):
        for plugins in (None, {'before': [confirm_plugin()]}, {'after': [{'name': 'history'}]}):
            with self.subTest(plugins=plugins):
                if plugins is not None:
                    self.set_plugins(plugins)
                snapshot = build_snapshot(self.root)
                for usage in self.usages(snapshot):
                    self.assertEqual(usage['plugins'], {phase: (plugins or {}).get(phase, [])
                                                       for phase in ('before', 'after')})

    def test_plugin_configuration_survives_snapshot_without_affecting_endpoint_contract(self):
        before = build_snapshot(self.root)
        plugins = {'before': [confirm_plugin()],
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

    def test_confirm_quorum_and_execution_modes_are_preserved(self):
        for mode in ('requester', 'automatic'):
            with self.subTest(mode=mode):
                plugin = confirm_plugin()
                plugin['config'].update(pool={'users': ['a', 'b', 'c']}, count=2, execution=mode)
                self.set_plugins({'before': [plugin]})
                snapshot = build_snapshot(self.root)
                for usage in self.usages(snapshot):
                    self.assertEqual(usage['plugins']['before'], [plugin])
                self.assertEqual(snapshot, build_snapshot(self.root, verify_sources=False))

    def test_confirm_rejects_missing_invalid_and_unachievable_conditions(self):
        base = confirm_plugin()['config']
        invalid = [None, {}, *[{k: v for k, v in base.items() if k != missing}
                               for missing in base]]
        for count in (0, -1, 1.5, True, '1', 2):
            invalid.append({**base, 'count': count})
        invalid += [{**base, 'pool': pool} for pool in (
            {}, [], {'users': []}, {'organizations': []},
            {'users': ['a', 'a']}, {'organizations': ['org', 'org']},
            {'users': ['']}, {'users': [' \n']}, {'organizations': [' ']},
            {'users': [None]}, {'users': 'a'}, {'organizations': 'org'},
            {'users': [{'kind': 'User', 'name': 'a'}]},
            {'roles': ['reviewer']}, {'users': ['a'], 'unknown': ['b']})]
        invalid += [{'targets': [{'kind': 'User', 'name': 'a'}],
                     'requiredCount': 1, 'execution': 'requester'},
                    {**base, 'requiredCount': 1}]
        invalid += [{**base, 'execution': mode} for mode in ('manual', '', None)]
        invalid += [{**base, 'required': 1}]
        for config in invalid:
            with self.subTest(config=config):
                self.set_plugins({'before': [{'name': 'confirm', 'config': config}]})
                with self.assertRaises(CatalogError):
                    build_snapshot(self.root)
        self.set_plugins({'before': [{'name': 'confirm'}]})
        with self.assertRaises(CatalogError):
            build_snapshot(self.root)

    def test_organization_only_and_mixed_pools_are_preserved(self):
        for pool in ({'organizations': ['security-team']},
                     {'users': ['reviewer-a'], 'organizations': ['security-team', 'member-team']},
                     {'users': ['홍 길동', 'Reviewer.A', 'reviewer.a']}):
            with self.subTest(pool=pool):
                plugin = confirm_plugin()
                plugin['config'].update(pool=pool, count=3)
                self.set_plugins({'before': [plugin]})
                for usage in self.usages(build_snapshot(self.root)):
                    self.assertEqual(usage['plugins']['before'], [plugin])

    def test_unpaged_action_cannot_require_more_than_user_candidates(self):
        for page in ('members', 'member-detail'):
            self.change(f'pages/{page}.yaml', lambda d: d['spec'].update(
                actions=[u for u in d['spec']['actions'] if u['action'] != 'members.detail.read']))
        plugin = confirm_plugin()
        plugin['config']['count'] = 2
        self.set_plugins({'before': [plugin]})
        self.invalid('count exceeds pool user nicknames')
