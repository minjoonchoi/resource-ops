from catalog_test_base import *


class DiscoveryTests(Fixture):
    def test_no_manifest_or_catalog_resource_is_needed(self):
        self.assertFalse((self.root / 'catalog/manifest.yaml').exists())
        snapshot = build_snapshot(self.root)
        self.assertNotIn('metadata', snapshot)
        self.assertNotIn('Catalog', {r['kind'] for r in snapshot['resources']})
        self.assertEqual(snapshot, build_snapshot(self.root, verify_sources=False))

    def test_action_addition_and_removal_need_no_regeneration(self):
        action = self.read('actions/members.detail.read.yaml')
        action['metadata']['name'] = 'members.other.read'
        path = 'actions/members.other.read.yaml'
        before = build_snapshot(self.root)
        self.write(path, action)
        self.assertEqual(generate(self.root, 'check'), [])
        for verify in (True, False):
            snapshot = build_snapshot(self.root, verify_sources=verify)
            self.assertEqual(len(snapshot['resources']), len(before['resources']) + 1)
        (self.root / path).unlink()
        self.assertEqual(build_snapshot(self.root), before)

    def test_invalid_paths_are_not_silently_skipped(self):
        action = self.read('actions/members.detail.read.yaml')
        for path in ('actions/nested/members.detail.read.yaml', 'actions/members.detail.read.yml'):
            with self.subTest(path=path):
                self.write(path, action)
                with self.assertRaisesRegex(CatalogError, 'kind/name must match'):
                    build_snapshot(self.root, verify_sources=False)
                (self.root / path).unlink()

    def test_directory_symlink_is_rejected(self):
        (self.root / 'actions/linked').symlink_to(self.root / 'pages', target_is_directory=True)
        with self.assertRaisesRegex(CatalogError, 'symlinks'):
            build_snapshot(self.root, verify_sources=False)

    def test_empty_resource_tree_is_not_delete_all(self):
        for directory in ('services', 'actions', 'pages'):
            shutil.rmtree(self.root / directory)
        with self.assertRaisesRegex(CatalogError, 'at least one resource'):
            build_snapshot(self.root, verify_sources=False)

    def test_catalog_kind_is_not_a_resource_definition(self):
        self.change('actions/members.detail.read.yaml', lambda d: d.update(kind='Catalog'))
        with self.assertRaisesRegex(CatalogError, 'not one of'):
            build_snapshot(self.root)
