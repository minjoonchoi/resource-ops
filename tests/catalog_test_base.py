import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from catalog import CatalogError, build_snapshot
from generate_services import generate
from openapi_catalog import endpoint_name

SOURCE = 'openapi/member-team/member-api.json'
SERVICE = 'services/member-api.yaml'
DETAIL = '/v1/members/{memberId}'
LIST = '/v1/members'


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        source = Path(__file__).resolve().parents[1]
        for directory in ('openapi', 'services', 'actions', 'pages', 'catalog', 'schemas'):
            shutil.copytree(source / directory, self.root / directory)
        shutil.copy(source / 'resource-catalog.yaml', self.root / 'resource-catalog.yaml')
        # Allows CI to test even on a branch whose services were just generated.
        generate(self.root)

    def read(self, path):
        text = (self.root / path).read_text()
        return json.loads(text) if path.endswith('.json') else yaml.safe_load(text)

    def write(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False) if path.endswith('.json')
                          else yaml.safe_dump(value, allow_unicode=True, sort_keys=False))

    def change(self, path, edit):
        value = self.read(path)
        edit(value)
        self.write(path, value)

    def change_api(self, edit):
        self.change(SOURCE, edit)
        generate(self.root)

    def change_usage(self, page, action, edit):
        self.change(f'pages/{page}.yaml', lambda d: edit(next(u for u in d['spec']['actions'] if u['action'] == action)))

    def effective(self, snapshot, page='members', action='members.detail.read'):
        return next(u['effective'] for u in snapshot['pageActionUsages'] if u['page'] == page and u['action'] == action)

    def invalid(self, message):
        with self.assertRaisesRegex(CatalogError, message):
            build_snapshot(self.root)
