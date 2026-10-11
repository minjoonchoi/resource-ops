from catalog_test_base import *


class CatalogTests(Fixture):
    def test_duplicate_yaml_keys(self):
        path = self.root / "pages/members.yaml"
        path.write_text(path.read_text() + "spec: {}\n")
        self.invalid("duplicate YAML key")

    def test_action_rejects_endpoint_id_reference(self):
        self.change("actions/members.detail.read.yaml", lambda d: d["spec"].update(endpoint="members.get"))
        self.invalid("not of type 'object'")

    def test_action_rejects_inline_service_details(self):
        self.change("actions/members.detail.read.yaml", lambda d: d["spec"]["endpoint"].update(
            service={"name": "member-api", "baseUrl": "https://members.example.invalid"}))
        self.invalid("not of type 'string'")

    def test_action_service_must_be_registered(self):
        self.change("actions/members.detail.read.yaml", lambda d: d["spec"]["endpoint"].update(service="missing"))
        self.invalid("actions/members.detail.read.yaml.*spec.endpoint.service: unregistered service")

    def test_action_method_must_match_registered_endpoint(self):
        self.change("actions/members.detail.read.yaml", lambda d: d["spec"]["endpoint"].update(method="POST"))
        self.invalid("no registered Endpoint.*POST /v1/members")

    def test_action_path_must_match_registered_endpoint(self):
        self.change("actions/members.detail.read.yaml", lambda d: d["spec"]["endpoint"].update(path="/v2/members/{memberId}"))
        self.invalid("no registered Endpoint.*GET /v2/members")

    def test_action_path_parameter_names_must_match_exactly(self):
        self.change("actions/members.detail.read.yaml", lambda d: d["spec"]["endpoint"].update(path="/v1/members/{id}"))
        self.invalid("spec.endpoint.path must exactly match.*memberId.*including path parameter names")

    def test_unpaged_action_still_requires_valid_direct_specification(self):
        self.change("pages/member-detail.yaml", lambda d: d["spec"].update(actions=[u for u in d["spec"]["actions"] if u["action"] != "members.contact.read"]))
        self.change("actions/members.contact.read.yaml", lambda d: d["spec"]["endpoint"].update(method="DELETE"))
        self.invalid("members.contact.read.yaml.*no registered Endpoint.*DELETE")

    def test_unknown_fields_do_not_silently_change_meaning(self):
        self.change("pages/members.yaml", lambda d: d["spec"].update(actionz=[]))
        self.invalid("Additional properties")

    def test_page_parent_cycle(self):
        self.change("pages/members.yaml", lambda d: d["spec"].update(parent="member-detail"))
        self.invalid("parent cycle")

    def test_unmodified_required_parameter_keeps_native_contract(self):
        self.change_usage("members", "members.directory.list", lambda u: u.pop("request"))
        effective = self.effective(build_snapshot(self.root), "members", "members.directory.list")
        parameter = next(p for p in effective["request"]["parameters"] if p["name"] == "organizationCode")
        self.assertNotIn("rules", effective["request"])
        self.assertTrue(parameter["required"])

    def test_scope_rules_preserve_the_endpoint_contract(self):
        effective = self.effective(build_snapshot(self.root), "members", "members.directory.list")
        params = {p["name"]: p for p in effective["request"]["parameters"]}
        self.assertEqual(effective["request"]["rules"]["query"]["organizationCode"],
                         {"source": "scope", "name": "organization-codes"})
        self.assertEqual(params["size"]["schema"]["maximum"], 100)
        self.assertNotIn("value", params["size"])
        self.assertFalse(params["page"]["required"])

    def test_unknown_request_parameter(self):
        self.change_usage("members", "members.directory.list", lambda u: u['request']['query'].update(
            unknown={'source': 'subject', 'field': 'nickname'}))
        self.invalid("unknown endpoint query parameter")

    def test_response_field_must_exist(self):
        self.change_usage("members", "members.directory.list", lambda u: u['response'].update(fields={'items': {'not-found': True}}))
        self.invalid("does not exist")

    def test_container_projection_is_forbidden(self):
        self.change_usage("members", "members.directory.list", lambda u: u['response'].update(fields={'items': True}))
        self.invalid("select individual leaves")

    def test_action_has_no_request_or_response_contract(self):
        for field in ["request", "responses"]:
            with self.subTest(field=field):
                path = "actions/members.detail.read.yaml"
                self.change(path, lambda d: d["spec"].update({field: {}}))
                self.invalid("Additional properties")
                self.change(path, lambda d: d["spec"].pop(field))

    def test_same_action_has_independent_page_rules(self):
        snapshot = build_snapshot(self.root)
        listing = self.effective(snapshot, "members", "members.detail.read")
        detail = self.effective(snapshot, "member-detail", "members.detail.read")
        self.assertEqual(listing["response"]["fields"], {"id": True, "nickname": True})
        self.assertEqual(detail["response"]["fields"], {"id": True, "nickname": True, "organizationCode": True})
        listing["response"]["fields"]["email"] = True
        self.assertNotIn("email", detail["response"]["fields"])
        endpoint = next(r for r in snapshot["resources"] if r["kind"] == "Endpoint" and r["metadata"]["name"] == endpoint_name("member-api", "GET", DETAIL))
        self.assertNotIn("fields", endpoint["spec"]["operation"]["responses"]["200"])

    def test_uses_relation_preserves_page_rules(self):
        snapshot = build_snapshot(self.root)
        edge = next(r for r in snapshot["relations"] if r["from"] == "Page/members" and r["to"] == "Action/members.directory.list")
        usage = self.read("pages/members.yaml")["spec"]["actions"][0]
        self.assertEqual(edge["request"], usage["request"])
        self.assertEqual(edge["response"], usage["response"])

    def test_duplicate_action_with_different_rules_is_ambiguous(self):
        self.change("pages/members.yaml", lambda d: d["spec"]["actions"].append({"action": "members.detail.read"}))
        self.invalid("duplicate action usage")

    def test_missing_page_action_reference(self):
        self.change_usage("members", "members.detail.read", lambda u: u.update(action="missing"))
        self.invalid("missing reference Action/missing")

    def test_legacy_overrides_and_endpoint_changes_are_rejected(self):
        original = self.read('pages/members.yaml')
        for key, value in [('overrides', {}), ('responses', {'200': {'fields': ['/id']}}), ('path', '/other')]:
            with self.subTest(key=key):
                self.change_usage('members', 'members.detail.read', lambda u: u.update({key: value}))
                self.invalid('Additional properties')
                self.write('pages/members.yaml', original)

    def test_renaming_is_an_explicit_identity_change(self):
        self.change("pages/members.yaml", lambda d: d["metadata"].update(name="renamed"))
        self.invalid("kind/name must match")

    def test_config_marker_must_match_version(self):
        self.change("resource-catalog.yaml", lambda d: d["resource-ops"].update({"api-version": "wrong/v1"}))
        self.invalid("Config Server marker")

    def test_valid_snapshot_and_relations(self):
        snapshot = build_snapshot(self.root)
        self.assertEqual(len(snapshot['resources']), 8)
        self.assertEqual(len(snapshot['relations']), 10)
        self.assertEqual(len(snapshot['page-action-usages']), 4)
        self.assertIn({'from': 'Action/members.contact.read', 'type': 'invokes',
                       'to': 'Endpoint/' + endpoint_name('member-api', 'GET', DETAIL)}, snapshot['relations'])
        for r in snapshot['resources']:
            if r['kind'] in ('Service', 'Endpoint'):
                self.assertEqual(r['metadata']['organization'], 'member-team')
        self.assertEqual(snapshot, build_snapshot(self.root))

    def test_native_response_and_body_are_preserved(self):
        self.change_usage('members', 'members.detail.read', lambda u: u.pop('response'))
        body = {'required': True, 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Member'}}}}
        self.change_api(lambda d: d['paths'][DETAIL]['get'].update(requestBody=body))
        effective = self.effective(build_snapshot(self.root))
        self.assertEqual(effective['responses']['200']['content']['application/json']['schema'], {'$ref': '#/schemas/Member'})
        self.assertEqual(effective['request']['body']['content']['application/json']['schema'], {'$ref': '#/schemas/Member'})
        self.assertTrue(effective['request']['body']['required'])
        self.assertNotIn('rules', effective['request'])

    def test_server_change_propagates_without_action_edits(self):
        before = build_snapshot(self.root)
        servers = [{'url': 'https://new.example.invalid'}, {'url': 'https://backup.example.invalid'}]
        self.change_api(lambda d: d.update(servers=servers))
        after = build_snapshot(self.root)
        self.assertEqual([r for r in before['resources'] if r['kind'] == 'Action'],
                         [r for r in after['resources'] if r['kind'] == 'Action'])
        for usage in after['page-action-usages']:
            self.assertEqual(usage['effective']['service']['servers'], servers)
        self.assertNotEqual(before['content-sha256'], after['content-sha256'])

    def test_operation_and_path_server_security_parameter_inheritance(self):
        def edit(d):
            item = d['paths'][DETAIL]
            item['parameters'] = [{'name': 'version', 'in': 'query', 'schema': {'type': 'integer'}}]
            item['servers'] = [{'url': 'https://path.example.invalid'}]
            item['get']['parameters'].append({'name': 'version', 'in': 'query', 'schema': {'type': 'string'}})
            item['get']['servers'] = [{'url': 'https://operation.example.invalid'}]
            d['components']['securitySchemes'] = {'bearer': {'type': 'http', 'scheme': 'bearer'}}
            d['security'] = [{'bearer': []}]
        self.change_api(edit)
        effective = self.effective(build_snapshot(self.root))
        self.assertEqual(effective['service']['servers'], [{'url': 'https://operation.example.invalid'}])
        self.assertEqual(effective['security'], [{'bearer': []}])
        self.assertEqual(next(p for p in effective['request']['parameters'] if p['name'] == 'version')['schema']['type'], 'string')

    def test_consumer_can_validate_only_generated_yaml(self):
        before = build_snapshot(self.root)
        shutil.rmtree(self.root / 'openapi')
        self.assertEqual(before, build_snapshot(self.root, verify_sources=False))

    def test_service_matching_is_scoped_even_when_urls_match(self):
        api = self.read(SOURCE)
        api['paths'] = {LIST: api['paths'][LIST]}
        self.write('openapi/other-team/other-api.json', api)
        generate(self.root)
        self.change('actions/members.contact.read.yaml', lambda d: d['spec']['endpoint'].update(service='other-api'))
        self.invalid("no registered Endpoint for service 'other-api'")

    def test_name_reference_does_not_use_display_title(self):
        self.change('actions/members.detail.read.yaml', lambda d: d['spec']['endpoint'].update(service='display-title'))
        self.invalid('unregistered service')

    def test_response_default_and_no_content_are_inherited(self):
        self.change_api(lambda d: d['paths'][DETAIL]['get']['responses'].update(
            {'204': {'description': 'empty'}, 'default': {'description': 'error'}}))
        response = self.effective(build_snapshot(self.root))['responses']
        self.assertEqual(response['204'], {})
        self.assertEqual(response['default'], {})

    def test_projection_requires_single_json_content(self):
        self.change_api(lambda d: d['paths'][DETAIL]['get']['responses']['200']['content'].update(
            {'text/plain': {'schema': {'type': 'string'}}}))
        self.invalid('exactly one JSON media type')

    def test_projection_fails_closed_on_composition(self):
        self.change_api(lambda d: d['components']['schemas'].update(Member={
            'oneOf': [{'type': 'object', 'properties': {'id': {'type': 'string'}}},
                      {'type': 'object', 'properties': {'nickname': {'type': 'string'}}}]}))
        self.invalid('unambiguous schema')

    def test_recursive_schema_is_preserved_and_finite_projection_works(self):
        self.change_api(lambda d: d['components']['schemas']['Member']['properties'].update(
            manager={'$ref': '#/components/schemas/Member'}))
        self.change_usage('members', 'members.detail.read', lambda u: u['response'].update(fields={'manager': {'id': True}}))
        self.assertEqual(self.effective(build_snapshot(self.root))['response']['fields'], {'manager': {'id': True}})

    def test_field_names_are_literal_and_not_flattened(self):
        self.change_api(lambda d: d['components']['schemas']['Member']['properties'].update({'a/b': {'type': 'string'}, 'a~b': {'type': 'string'}}))
        self.change_usage('members', 'members.detail.read', lambda u: u['response'].update(fields={'a/b': True, 'a~b': True}))
        build_snapshot(self.root)
