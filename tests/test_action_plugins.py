import copy

from catalog_test_base import *


ACTION = 'actions/members.detail.read.yaml'


def confirm_plugin():
    return {'name': 'confirm', 'config': {
        'pool': {'users': ['reviewer-a']},
        'count': 1, 'execution': 'requester'}}


def history_plugin():
    return {'name': 'history'}


class ActionPluginTests(Fixture):
    def set_plugins(self, plugins):
        self.change(ACTION, lambda d: d['spec'].update(plugins=plugins))

    def usages(self, snapshot):
        return [u for u in snapshot['page-action-usages'] if u['action'] == 'members.detail.read']

    def test_plugins_are_optional_and_omission_normalizes_to_empty_array(self):
        for plugins in (None, [confirm_plugin()], [history_plugin()]):
            with self.subTest(plugins=plugins):
                if plugins is not None:
                    self.set_plugins(plugins)
                snapshot = build_snapshot(self.root)
                for usage in self.usages(snapshot):
                    self.assertEqual(usage['plugins'], plugins or [])

    def test_plugin_configuration_survives_snapshot_without_affecting_endpoint_contract(self):
        before = build_snapshot(self.root)
        plugins = [confirm_plugin(), history_plugin()]
        self.set_plugins(plugins)
        snapshot = build_snapshot(self.root)
        action = next(r for r in snapshot['resources'] if r['kind'] == 'Action'
                      and r['metadata']['name'] == 'members.detail.read')
        self.assertEqual(action['spec']['plugins'], plugins)
        self.assertEqual(snapshot['relations'], before['relations'])
        self.assertNotEqual(snapshot['content-sha256'], before['content-sha256'])
        usages = self.usages(snapshot)
        for usage, previous in zip(usages, self.usages(before)):
            self.assertEqual(usage['plugins'], plugins)
            self.assertEqual(usage['effective'], previous['effective'])
        self.assertEqual(snapshot, build_snapshot(self.root, verify_sources=False))
        usages[0]['plugins'].clear()
        self.assertEqual(usages[1]['plugins'], plugins)
        self.assertEqual(action['spec']['plugins'], plugins)

    def test_old_phases_unknown_names_and_malformed_connections_are_rejected(self):
        invalid = [{}, [], {'before': [confirm_plugin()]}, {'after': [history_plugin()]},
                   [{'name': 'unknown'}], ['confirm'], [{}],
                   [{**confirm_plugin(), 'enabled': False}],
                   [{'name': 'history', 'config': 'invalid'}],
                   [history_plugin(), history_plugin()],
                   [confirm_plugin(), {**confirm_plugin(), 'config': {
                       'pool': {'users': ['another-user']}, 'count': 1, 'execution': 'automatic'}}]]
        for plugins in invalid:
            with self.subTest(plugins=plugins):
                self.set_plugins(plugins)
                with self.assertRaises(CatalogError):
                    build_snapshot(self.root)

    def test_plugin_order_is_preserved_without_changing_contract(self):
        before = build_snapshot(self.root)
        for plugins in ([history_plugin(), confirm_plugin()], [confirm_plugin(), history_plugin()]):
            with self.subTest(plugins=plugins):
                self.set_plugins(plugins)
                snapshot = build_snapshot(self.root)
                for usage in self.usages(snapshot):
                    self.assertEqual(usage['plugins'], plugins)
                self.assertEqual(self.effective(before), self.effective(snapshot))

    def test_unpaged_action_plugins_are_validated(self):
        for page in ('members', 'member-detail'):
            self.change(f'pages/{page}.yaml', lambda d: d['spec'].update(
                actions=[u for u in d['spec']['actions'] if u['action'] != 'members.detail.read']))
        self.set_plugins([{'name': 'unknown'}])
        with self.assertRaises(CatalogError):
            build_snapshot(self.root)

    def test_page_cannot_override_or_disable_plugins(self):
        for placement in ('usage', 'response'):
            with self.subTest(placement=placement):
                original = self.read('pages/members.yaml')
                self.change_usage('members', 'members.detail.read', lambda u:
                                  (u if placement == 'usage' else u['response']).update(plugins={}))
                self.invalid('Additional properties')
                self.write('pages/members.yaml', original)

    def test_flat_endpoint_fields_and_inline_contracts_are_rejected(self):
        original = self.read(ACTION)
        variants = [copy.deepcopy(original['spec']['endpoint']), {'plugins': [{'name': 'confirm'}]}]
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
                self.set_plugins([plugin])
                snapshot = build_snapshot(self.root)
                for usage in self.usages(snapshot):
                    self.assertEqual(usage['plugins'], [plugin])
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
                self.set_plugins([{'name': 'confirm', 'config': config}])
                with self.assertRaises(CatalogError):
                    build_snapshot(self.root)
        self.set_plugins([{'name': 'confirm'}])
        with self.assertRaises(CatalogError):
            build_snapshot(self.root)

    def test_organization_only_and_mixed_pools_are_preserved(self):
        for pool in ({'organizations': ['security-team']},
                     {'users': ['reviewer-a'], 'organizations': ['security-team', 'member-team']},
                     {'users': ['홍 길동', 'Reviewer.A', 'reviewer.a']}):
            with self.subTest(pool=pool):
                plugin = confirm_plugin()
                plugin['config'].update(pool=pool, count=3)
                self.set_plugins([plugin])
                for usage in self.usages(build_snapshot(self.root)):
                    self.assertEqual(usage['plugins'], [plugin])

    def test_unpaged_action_cannot_require_more_than_user_candidates(self):
        for page in ('members', 'member-detail'):
            self.change(f'pages/{page}.yaml', lambda d: d['spec'].update(
                actions=[u for u in d['spec']['actions'] if u['action'] != 'members.detail.read']))
        plugin = confirm_plugin()
        plugin['config']['count'] = 2
        self.set_plugins([plugin])
        self.invalid('count exceeds pool user nicknames')

    def test_history_needs_no_configuration_or_confirm_plugin(self):
        self.set_plugins([history_plugin()])
        snapshot = build_snapshot(self.root)
        for usage in self.usages(snapshot):
            self.assertEqual(usage['plugins'], [{'name': 'history'}])
        self.assertEqual(snapshot, build_snapshot(self.root, verify_sources=False))

    def test_history_rejects_event_filters_and_overridden_action_identity(self):
        extras = [{'config': value} for value in (None, {}, {'events': ['confirm', 'endpoint']},
                                                 {'events': ['endpoint']})]
        extras += [{'events': ['endpoint']}, {'actionName': 'another.action'},
                   {'groupBy': 'endpoint'}, {'actor': False}]
        for extra in extras:
            with self.subTest(extra=extra):
                self.set_plugins([{'name': 'history', **extra}])
                with self.assertRaises(CatalogError):
                    build_snapshot(self.root)

    def test_history_action_binding_follows_metadata_name_not_endpoint(self):
        self.set_plugins([history_plugin()])
        renamed = 'members.detail.audit'
        action = self.read(ACTION)
        action['metadata']['name'] = renamed
        (self.root / ACTION).unlink()
        self.write(f'actions/{renamed}.yaml', action)
        for page in ('members', 'member-detail'):
            self.change_usage(page, 'members.detail.read', lambda u: u.update(action=renamed))
        generate(self.root)
        snapshot = build_snapshot(self.root)
        usages = [u for u in snapshot['page-action-usages'] if u['action'] == renamed]
        self.assertEqual(len(usages), 2)
        for usage in usages:
            self.assertEqual(usage['plugins'], [history_plugin()])
        contact = next(u for u in snapshot['page-action-usages'] if u['action'] == 'members.contact.read')
        self.assertEqual(contact['endpoint'], usages[0]['endpoint'])
        self.assertNotEqual(contact['action'], usages[0]['action'])
        self.assertFalse(any(r['kind'] == 'Action' and r['metadata']['name'] == 'members.detail.read'
                             for r in snapshot['resources']))
