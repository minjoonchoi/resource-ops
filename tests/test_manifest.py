from catalog_test_base import *


class ManifestTests(Fixture):
    def test_generated_manifest_is_only_a_file_inventory(self):
        manifest = self.read('catalog/manifest.yaml')
        self.assertEqual(set(manifest), {'resources'})
        self.assertEqual(manifest['resources'], sorted(manifest['resources']))
        snapshot = build_snapshot(self.root)
        self.assertNotIn('metadata', snapshot)
        self.assertNotIn('Catalog', {r['kind'] for r in snapshot['resources']})
        self.assertEqual(snapshot, build_snapshot(self.root, verify_sources=False))

    def test_consumer_rejects_legacy_and_malformed_manifest(self):
        valid = self.read('catalog/manifest.yaml')
        cases = [
            {'apiVersion': 'resource-ops/v1', 'kind': 'Catalog',
             'metadata': {'name': 'resource-catalog', 'title': 'Catalog'}, 'spec': valid},
            {**valid, 'kind': 'Catalog'}, {}, {'resources': []},
            {'resources': ['services/member-api.yaml', 'services/member-api.yaml']},
            {'resources': ['../other.yaml']},
            {'resources': ['catalog/manifest.yaml']},
            {'resources': ['services/missing.yaml']},
            {'resources': valid['resources'][:-1]},
        ]
        for manifest in cases:
            with self.subTest(manifest=manifest):
                self.write('catalog/manifest.yaml', manifest)
                with self.assertRaises(CatalogError):
                    build_snapshot(self.root, verify_sources=False)

    def test_catalog_kind_is_not_a_resource_definition(self):
        self.change('actions/members.detail.read.yaml', lambda d: d.update(kind='Catalog'))
        with self.assertRaisesRegex(CatalogError, 'not one of'):
            build_snapshot(self.root)
