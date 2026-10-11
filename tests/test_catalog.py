import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from catalog import CatalogError, build_snapshot


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = Path(__file__).resolve().parents[1]
        for folder in ("catalog", "schemas"):
            shutil.copytree(source / folder, self.root / folder)
        shutil.copy(source / "resource-catalog.yaml", self.root / "resource-catalog.yaml")

    def read(self, path):
        return yaml.safe_load((self.root / path).read_text())

    def write(self, path, value):
        (self.root / path).write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False))

    def change(self, path, edit):
        value = self.read(path)
        edit(value)
        self.write(path, value)

    def invalid(self, message):
        with self.assertRaisesRegex(CatalogError, message):
            build_snapshot(self.root)

    def test_valid_snapshot_and_relations(self):
        snapshot = build_snapshot(self.root)
        self.assertEqual(len(snapshot["resources"]), 8)
        self.assertEqual(len(snapshot["relations"]), 10)
        self.assertIn({"from": "Action/members.contact.read", "type": "invokes", "to": "Endpoint/members.get"}, snapshot["relations"])
        self.assertEqual(len(snapshot["contentSha256"]), 64)

    def test_manifest_order_and_yaml_format_do_not_change_hash(self):
        before = build_snapshot(self.root)
        self.change("catalog/manifest.yaml", lambda d: d["spec"]["resources"].reverse())
        self.change("catalog/endpoints/members.list.yaml", lambda d: None)
        self.assertEqual(before, build_snapshot(self.root))

    def test_duplicate_yaml_keys(self):
        path = self.root / "catalog/pages/members.yaml"
        path.write_text(path.read_text() + "spec: {}\n")
        self.invalid("duplicate YAML key")

    def test_missing_reference(self):
        self.change("catalog/actions/members.detail.read.yaml", lambda d: d["spec"].update(endpoint="missing"))
        self.invalid("missing reference Endpoint/missing")

    def test_missing_manifest_file(self):
        (self.root / "catalog/actions/members.contact.read.yaml").unlink()
        self.invalid("manifest mismatch")

    def test_unlisted_file(self):
        shutil.copy(self.root / "catalog/pages/members.yaml", self.root / "catalog/pages/orphan.yaml")
        self.invalid("unlisted=.*orphan")

    def test_empty_manifest_is_not_delete_all(self):
        self.change("catalog/manifest.yaml", lambda d: d["spec"].update(resources=[]))
        self.invalid("non-empty")

    def test_path_traversal(self):
        self.change("catalog/manifest.yaml", lambda d: d["spec"]["resources"].append("catalog/../../secret.yaml"))
        self.invalid("does not match")

    def test_symlink_is_rejected(self):
        path = self.root / "catalog/servers/member-api.yaml"
        original = self.root / "server-copy.yaml"
        path.rename(original)
        path.symlink_to(original)
        self.invalid("symlinks")

    def test_unknown_fields_do_not_silently_change_meaning(self):
        self.change("catalog/pages/members.yaml", lambda d: d["spec"].update(actionz=[]))
        self.invalid("Additional properties")

    def test_page_parent_cycle(self):
        self.change("catalog/pages/members.yaml", lambda d: d["spec"].update(parent="member-detail"))
        self.invalid("parent cycle")

    def test_required_parameter_needs_binding(self):
        self.change("catalog/actions/members.directory.list.yaml", lambda d: d["spec"]["request"]["parameters"].pop(0))
        self.invalid("required endpoint parameter")

    def test_constant_must_match_endpoint_range(self):
        self.change("catalog/actions/members.directory.list.yaml", lambda d: d["spec"]["request"]["parameters"][2].update(value=101))
        self.invalid("constant.*violates")

    def test_unknown_request_parameter(self):
        self.change("catalog/actions/members.detail.read.yaml", lambda d: d["spec"]["request"]["parameters"][0].update(name="member_id"))
        self.invalid("unknown endpoint parameter")

    def test_source_and_value_are_mutually_exclusive(self):
        self.change("catalog/actions/members.detail.read.yaml", lambda d: d["spec"]["request"]["parameters"][0].update(value="123"))
        self.invalid("valid under each")

    def test_unknown_subject_source(self):
        self.change("catalog/actions/members.detail.read.yaml", lambda d: d["spec"]["request"]["parameters"][0].update(source="subject.anything"))
        self.invalid("not one of")

    def test_response_field_must_exist(self):
        self.change("catalog/actions/members.directory.list.yaml", lambda d: d["spec"]["responses"]["200"].update(fields=["/items/*/not-found"]))
        self.invalid("does not exist")

    def test_container_projection_is_forbidden(self):
        self.change("catalog/actions/members.directory.list.yaml", lambda d: d["spec"]["responses"]["200"].update(fields=["/items"]))
        self.invalid("selects a container")

    def test_response_statuses_must_cover_error_contract(self):
        self.change("catalog/actions/members.detail.read.yaml", lambda d: d["spec"]["responses"].pop("404"))
        self.invalid("response statuses")

    def test_numeric_status_keys_are_rejected(self):
        path = self.root / "catalog/endpoints/members.get.yaml"
        path.write_text(path.read_text().replace('"200":', '200:'))
        self.invalid("quote HTTP status")

    def test_path_template_requires_matching_parameters(self):
        self.change("catalog/endpoints/members.get.yaml", lambda d: d["spec"].update(path="/v1/members/{id}"))
        self.invalid("path placeholders")

    def test_semantically_duplicate_endpoint_path(self):
        item = self.read("catalog/endpoints/members.get.yaml")
        item["metadata"]["name"] = "members.duplicate"
        item["spec"]["path"] = "/v1/members/{otherId}"
        item["spec"]["request"]["parameters"][0]["name"] = "otherId"
        path = "catalog/endpoints/members.duplicate.yaml"
        self.write(path, item)
        self.change("catalog/manifest.yaml", lambda d: d["spec"]["resources"].append(path))
        self.invalid("duplicate server/method/path")

    def test_header_names_are_case_insensitive(self):
        additions = [
            {"in": "header", "name": name, "required": False, "schema": {"type": "string"}}
            for name in ["X-Request-Id", "x-request-id"]
        ]
        self.change("catalog/endpoints/members.get.yaml", lambda d: d["spec"]["request"]["parameters"].extend(additions))
        self.invalid("duplicate parameter")

    def test_spring_placeholder_is_forbidden(self):
        self.change("catalog/servers/member-api.yaml", lambda d: d["spec"].update(baseUrl="https://${SERVER_HOST}"))
        self.invalid("Spring placeholders")

    def test_anchors_are_forbidden(self):
        path = self.root / "catalog/pages/members.yaml"
        path.write_text(path.read_text().replace("spec:", "spec: &shared"))
        self.invalid("anchors and aliases")

    def test_inline_schema_required_property_must_exist(self):
        self.change("catalog/endpoints/members.get.yaml", lambda d: d["spec"]["responses"]["200"]["schema"]["required"].append("missing"))
        self.invalid("required property is not declared")

    def test_schema_refs_are_not_supported(self):
        self.change("catalog/endpoints/members.get.yaml", lambda d: d["spec"]["responses"]["200"]["schema"].update({"$ref": "https://example.invalid/schema"}))
        self.invalid("Additional properties")

    def test_required_json_body_and_binding(self):
        endpoint = "catalog/endpoints/members.get.yaml"
        self.change(endpoint, lambda d: d["spec"]["request"].update(body={"required": True, "schema": {"type": "string"}}))
        self.invalid("required endpoint body")
        for name in ["members.detail.read", "members.contact.read"]:
            self.change(f"catalog/actions/{name}.yaml", lambda d: d["spec"]["request"].update(body={"source": "input"}))
        build_snapshot(self.root)

    def test_pointer_escaping_preserves_wire_field_names(self):
        def add_field(d):
            d["spec"]["responses"]["200"]["schema"]["properties"]["test/~field"] = {"type": "string"}
        self.change("catalog/endpoints/members.get.yaml", add_field)
        self.change("catalog/actions/members.detail.read.yaml", lambda d: d["spec"]["responses"]["200"].update(fields=["/test~1~0field"]))
        build_snapshot(self.root)

    def test_renaming_is_an_explicit_identity_change(self):
        self.change("catalog/pages/members.yaml", lambda d: d["metadata"].update(name="renamed"))
        self.invalid("kind/name must match")

    def test_config_marker_must_match_version(self):
        self.change("resource-catalog.yaml", lambda d: d["resourceOps"].update(apiVersion="wrong/v1"))
        self.invalid("Config Server marker")

    def test_profile_specific_resource_names_are_rejected(self):
        old = "catalog/pages/member-detail.yaml"
        new = "catalog/pages/member-detail-default.yaml"
        self.change(old, lambda d: d["metadata"].update(name="member-detail-default"))
        (self.root / old).rename(self.root / new)
        self.change("catalog/manifest.yaml", lambda d: d["spec"].update(resources=[new if p == old else p for p in d["spec"]["resources"]]))
        self.invalid("reserved by Config Server")


if __name__ == "__main__":
    unittest.main()
