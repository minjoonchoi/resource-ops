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

    def change_usage(self, page, action, edit):
        self.change(f"catalog/pages/{page}.yaml", lambda document: edit(next(
            usage for usage in document["spec"]["actions"] if usage["action"] == action
        )))

    def effective(self, snapshot, page, action):
        return next(usage["effective"] for usage in snapshot["pageActionUsages"]
                    if usage["page"] == page and usage["action"] == action)

    def invalid(self, message):
        with self.assertRaisesRegex(CatalogError, message):
            build_snapshot(self.root)

    def test_valid_snapshot_and_relations(self):
        snapshot = build_snapshot(self.root)
        self.assertEqual(len(snapshot["resources"]), 8)
        self.assertEqual(len(snapshot["relations"]), 10)
        self.assertEqual(len(snapshot["pageActionUsages"]), 4)
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
        self.change("catalog/endpoints/members.get.yaml", lambda d: d["spec"].update(server="missing"))
        self.invalid("missing reference Server/missing")

    def test_action_rejects_endpoint_id_reference(self):
        self.change("catalog/actions/members.detail.read.yaml", lambda d: d["spec"].update(endpoint="members.get"))
        self.invalid("Additional properties.*endpoint")

    def test_action_rejects_inline_service_details(self):
        self.change("catalog/actions/members.detail.read.yaml", lambda d: d["spec"].update(
            service={"name": "member-api", "baseUrl": "https://members.example.invalid"}))
        self.invalid("not of type 'string'")

    def test_action_service_must_be_registered(self):
        self.change("catalog/actions/members.detail.read.yaml", lambda d: d["spec"].update(service="missing"))
        self.invalid("catalog/actions/members.detail.read.yaml.*spec.service: unregistered service")

    def test_server_url_change_propagates_without_action_edits(self):
        original = build_snapshot(self.root)
        self.change("catalog/servers/member-api.yaml", lambda d: d["spec"].update(baseUrl="https://new.example.invalid"))
        snapshot = build_snapshot(self.root)
        self.assertNotEqual(snapshot["contentSha256"], original["contentSha256"])
        self.assertEqual([r for r in snapshot["resources"] if r["kind"] == "Action"],
                         [r for r in original["resources"] if r["kind"] == "Action"])
        for usage in snapshot["pageActionUsages"]:
            self.assertEqual(usage["effective"]["service"],
                             {"name": "member-api", "baseUrl": "https://new.example.invalid"})

    def test_action_method_must_match_registered_endpoint(self):
        self.change("catalog/actions/members.detail.read.yaml", lambda d: d["spec"].update(method="POST"))
        self.invalid("no registered Endpoint.*POST /v1/members")

    def test_action_path_must_match_registered_endpoint(self):
        self.change("catalog/actions/members.detail.read.yaml", lambda d: d["spec"].update(path="/v2/members/{memberId}"))
        self.invalid("no registered Endpoint.*GET /v2/members")

    def test_action_path_parameter_names_must_match_exactly(self):
        self.change("catalog/actions/members.detail.read.yaml", lambda d: d["spec"].update(path="/v1/members/{id}"))
        self.invalid("spec.path must exactly match.*memberId.*including path parameter names")

    def test_action_does_not_depend_on_endpoint_identity(self):
        old = "catalog/endpoints/members.get.yaml"
        new = "catalog/endpoints/members.read.yaml"
        actions_before = {p.name: p.read_text() for p in (self.root / "catalog/actions").glob("*.yaml")}
        self.change(old, lambda d: d["metadata"].update(name="members.read"))
        (self.root / old).rename(self.root / new)
        self.change("catalog/manifest.yaml", lambda d: d["spec"].update(resources=[new if p == old else p for p in d["spec"]["resources"]]))
        snapshot = build_snapshot(self.root)
        self.assertIn({"from": "Action/members.detail.read", "type": "invokes", "to": "Endpoint/members.read"}, snapshot["relations"])
        self.assertEqual(actions_before, {p.name: p.read_text() for p in (self.root / "catalog/actions").glob("*.yaml")})

    def test_matching_is_scoped_to_service_even_with_same_base_url(self):
        server = self.read("catalog/servers/member-api.yaml")
        server["metadata"]["name"] = "other-api"
        self.write("catalog/servers/other-api.yaml", server)
        self.change("catalog/manifest.yaml", lambda d: d["spec"]["resources"].append("catalog/servers/other-api.yaml"))
        self.change("catalog/actions/members.contact.read.yaml", lambda d: d["spec"].update(service="other-api"))
        self.invalid("no registered Endpoint for service 'other-api'")
        endpoint = self.read("catalog/endpoints/members.get.yaml")
        endpoint["metadata"]["name"] = "other.members.get"
        endpoint["spec"]["server"] = "other-api"
        self.write("catalog/endpoints/other.members.get.yaml", endpoint)
        self.change("catalog/manifest.yaml", lambda d: d["spec"]["resources"].append("catalog/endpoints/other.members.get.yaml"))
        snapshot = build_snapshot(self.root)
        self.assertIn({"from": "Action/members.contact.read", "type": "invokes", "to": "Endpoint/other.members.get"}, snapshot["relations"])
        self.assertIn({"from": "Action/members.detail.read", "type": "invokes", "to": "Endpoint/members.get"}, snapshot["relations"])

    def test_unpaged_action_still_requires_valid_direct_specification(self):
        self.change("catalog/pages/member-detail.yaml", lambda d: d["spec"].update(actions=[u for u in d["spec"]["actions"] if u["action"] != "members.contact.read"]))
        self.change("catalog/actions/members.contact.read.yaml", lambda d: d["spec"].update(method="DELETE"))
        self.invalid("members.contact.read.yaml.*no registered Endpoint.*DELETE")

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

    def test_unmodified_required_parameter_inherits_input(self):
        self.change_usage("members", "members.directory.list", lambda u: u["overrides"]["request"]["parameters"].pop(0))
        effective = self.effective(build_snapshot(self.root), "members", "members.directory.list")
        parameter = next(p for p in effective["request"]["parameters"] if p["name"] == "organizationCode")
        self.assertEqual(parameter["source"], "input")
        self.assertTrue(parameter["required"])

    def test_sparse_request_merges_by_parameter_identity(self):
        effective = self.effective(build_snapshot(self.root), "members", "members.directory.list")
        params = {p["name"]: p for p in effective["request"]["parameters"]}
        self.assertEqual(params["organizationCode"]["source"], "subject.organization.code")
        self.assertEqual(params["size"]["value"], 20)
        self.assertNotIn("source", params["size"])
        self.assertEqual(params["size"]["schema"]["maximum"], 100)
        self.assertEqual(params["page"]["source"], "input")
        self.assertFalse(params["page"]["required"])

    def test_constant_must_match_endpoint_range(self):
        self.change_usage("members", "members.directory.list", lambda u: u["overrides"]["request"]["parameters"][1].update(value=101))
        self.invalid("constant.*violates")

    def test_unknown_request_parameter(self):
        self.change_usage("members", "members.directory.list", lambda u: u["overrides"]["request"]["parameters"][0].update(name="organization_code"))
        self.invalid("unknown endpoint parameter")

    def test_source_and_value_are_mutually_exclusive(self):
        self.change_usage("members", "members.directory.list", lambda u: u["overrides"]["request"]["parameters"][0].update(value="123"))
        self.invalid("valid under each")

    def test_unknown_subject_source(self):
        self.change_usage("members", "members.directory.list", lambda u: u["overrides"]["request"]["parameters"][0].update(source="subject.anything"))
        self.invalid("not one of")

    def test_response_field_must_exist(self):
        self.change_usage("members", "members.directory.list", lambda u: u["overrides"]["responses"]["200"].update(fields=["/items/*/not-found"]))
        self.invalid("does not exist")

    def test_container_projection_is_forbidden(self):
        self.change_usage("members", "members.directory.list", lambda u: u["overrides"]["responses"]["200"].update(fields=["/items"]))
        self.invalid("selects a container")

    def test_unmodified_error_response_inherits_endpoint(self):
        effective = self.effective(build_snapshot(self.root), "members", "members.detail.read")
        endpoint = self.read("catalog/endpoints/members.get.yaml")["spec"]
        self.assertEqual(effective["responses"]["404"], endpoint["responses"]["404"])

    def test_override_response_status_must_exist(self):
        self.change_usage("members", "members.detail.read", lambda u: u["overrides"]["responses"].update({"201": {"fields": ["/id"]}}))
        self.invalid("unknown endpoint response status")

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

    def test_required_json_body_inherits_without_override(self):
        endpoint = "catalog/endpoints/members.get.yaml"
        self.change(endpoint, lambda d: d["spec"]["request"].update(body={"required": True, "schema": {"type": "string"}}))
        snapshot = build_snapshot(self.root)
        for page, action in [("members", "members.detail.read"), ("member-detail", "members.contact.read")]:
            body = self.effective(snapshot, page, action)["request"]["body"]
            self.assertEqual(body, {"required": True, "schema": {"type": "string"}, "source": "input"})

    def test_pointer_escaping_preserves_wire_field_names(self):
        def add_field(d):
            d["spec"]["responses"]["200"]["schema"]["properties"]["test/~field"] = {"type": "string"}
        self.change("catalog/endpoints/members.get.yaml", add_field)
        self.change_usage("members", "members.detail.read", lambda u: u["overrides"]["responses"]["200"].update(fields=["/test~1~0field"]))
        build_snapshot(self.root)

    def test_action_has_no_request_or_response_contract(self):
        for field in ["request", "responses"]:
            with self.subTest(field=field):
                path = "catalog/actions/members.detail.read.yaml"
                self.change(path, lambda d: d["spec"].update({field: {}}))
                self.invalid("Additional properties")
                self.change(path, lambda d: d["spec"].pop(field))

    def test_page_action_without_overrides_inherits_entire_endpoint(self):
        self.change_usage("members", "members.detail.read", lambda u: u.pop("overrides"))
        snapshot = build_snapshot(self.root)
        effective = self.effective(snapshot, "members", "members.detail.read")
        endpoint = self.read("catalog/endpoints/members.get.yaml")["spec"]
        self.assertEqual(effective["responses"], endpoint["responses"])
        self.assertEqual(effective["method"], endpoint["method"])
        self.assertEqual(effective["path"], endpoint["path"])
        self.assertEqual(effective["request"]["parameters"][0]["source"], "input")
        action = next(r for r in snapshot["resources"] if r["kind"] == "Action" and r["metadata"]["name"] == "members.detail.read")
        self.assertEqual(action["spec"], {
            "service": "member-api",
            "method": "GET", "path": "/v1/members/{memberId}",
        })
        self.assertEqual(effective["service"], {"name": "member-api", "baseUrl": "https://members.example.invalid"})
        self.assertNotIn("server", effective)

    def test_same_action_has_independent_page_overrides(self):
        snapshot = build_snapshot(self.root)
        listing = self.effective(snapshot, "members", "members.detail.read")
        detail = self.effective(snapshot, "member-detail", "members.detail.read")
        self.assertEqual(listing["responses"]["200"]["fields"], ["/id", "/nickname"])
        self.assertEqual(detail["responses"]["200"]["fields"], ["/id", "/nickname", "/organizationCode"])
        listing["responses"]["200"]["fields"].append("/email")
        self.assertNotIn("/email", detail["responses"]["200"]["fields"])
        endpoint = next(r for r in snapshot["resources"] if r["kind"] == "Endpoint" and r["metadata"]["name"] == "members.get")
        self.assertNotIn("fields", endpoint["spec"]["responses"]["200"])

    def test_uses_relation_preserves_override_payload(self):
        snapshot = build_snapshot(self.root)
        edge = next(r for r in snapshot["relations"] if r["from"] == "Page/members" and r["to"] == "Action/members.directory.list")
        usage = self.read("catalog/pages/members.yaml")["spec"]["actions"][0]
        self.assertEqual(edge["overrides"], usage["overrides"])

    def test_duplicate_action_with_different_overrides_is_ambiguous(self):
        self.change("catalog/pages/members.yaml", lambda d: d["spec"]["actions"].append({"action": "members.detail.read"}))
        self.invalid("duplicate action usage")

    def test_missing_page_action_reference(self):
        self.change_usage("members", "members.detail.read", lambda u: u.update(action="missing"))
        self.invalid("missing reference Action/missing")

    def test_empty_override_payloads_are_rejected(self):
        for overrides in [{}, {"request": {"parameters": []}}, {"responses": {}}]:
            with self.subTest(overrides=overrides):
                self.change_usage("members", "members.detail.read", lambda u: u.update(overrides=overrides))
                self.invalid("non-empty")

    def test_redundant_input_source_is_omitted_in_yaml(self):
        self.change_usage("members", "members.directory.list", lambda u: u["overrides"]["request"]["parameters"][0].update(source="input"))
        self.invalid("not one of")

    def test_endpoint_route_cannot_be_overridden_by_page(self):
        self.change_usage("members", "members.detail.read", lambda u: u["overrides"].update(path="/other"))
        self.invalid("Additional properties")

    def test_endpoint_change_updates_all_derived_usages(self):
        self.change("catalog/endpoints/members.get.yaml", lambda d: d["spec"]["request"]["parameters"][0]["schema"].update(minLength=5))
        snapshot = build_snapshot(self.root)
        for usage in snapshot["pageActionUsages"]:
            if usage["endpoint"] == "members.get":
                self.assertEqual(usage["effective"]["request"]["parameters"][0]["schema"]["minLength"], 5)

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
