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

    def test_override_response_status_must_exist(self):
        self.change_usage("members", "members.detail.read", lambda u: u["overrides"]["responses"].update({"201": {"fields": ["/id"]}}))
        self.invalid("unknown endpoint response status")

    def test_action_has_no_request_or_response_contract(self):
        for field in ["request", "responses"]:
            with self.subTest(field=field):
                path = "actions/members.detail.read.yaml"
                self.change(path, lambda d: d["spec"].update({field: {}}))
                self.invalid("Additional properties")
                self.change(path, lambda d: d["spec"].pop(field))

    def test_same_action_has_independent_page_overrides(self):
        snapshot = build_snapshot(self.root)
        listing = self.effective(snapshot, "members", "members.detail.read")
        detail = self.effective(snapshot, "member-detail", "members.detail.read")
        self.assertEqual(listing["responses"]["200"]["fields"], ["/id", "/nickname"])
        self.assertEqual(detail["responses"]["200"]["fields"], ["/id", "/nickname", "/organizationCode"])
        listing["responses"]["200"]["fields"].append("/email")
        self.assertNotIn("/email", detail["responses"]["200"]["fields"])
        endpoint = next(r for r in snapshot["resources"] if r["kind"] == "Endpoint" and r["metadata"]["name"] == endpoint_name("member-api", "GET", DETAIL))
        self.assertNotIn("fields", endpoint["spec"]["operation"]["responses"]["200"])

    def test_uses_relation_preserves_override_payload(self):
        snapshot = build_snapshot(self.root)
        edge = next(r for r in snapshot["relations"] if r["from"] == "Page/members" and r["to"] == "Action/members.directory.list")
        usage = self.read("pages/members.yaml")["spec"]["actions"][0]
        self.assertEqual(edge["overrides"], usage["overrides"])

    def test_duplicate_action_with_different_overrides_is_ambiguous(self):
        self.change("pages/members.yaml", lambda d: d["spec"]["actions"].append({"action": "members.detail.read"}))
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

    def test_renaming_is_an_explicit_identity_change(self):
        self.change("pages/members.yaml", lambda d: d["metadata"].update(name="renamed"))
        self.invalid("kind/name must match")

    def test_config_marker_must_match_version(self):
        self.change("resource-catalog.yaml", lambda d: d["resourceOps"].update(apiVersion="wrong/v1"))
        self.invalid("Config Server marker")

    def test_valid_snapshot_and_relations(self):
        snapshot = build_snapshot(self.root)
        self.assertEqual(len(snapshot['resources']), 8)
        self.assertEqual(len(snapshot['relations']), 10)
        self.assertEqual(len(snapshot['pageActionUsages']), 4)
        self.assertIn({'from': 'Action/members.contact.read', 'type': 'invokes',
                       'to': 'Endpoint/' + endpoint_name('member-api', 'GET', DETAIL)}, snapshot['relations'])
        for r in snapshot['resources']:
            if r['kind'] in ('Service', 'Endpoint'):
                self.assertEqual(r['metadata']['organization'], 'member-team')
        self.assertEqual(snapshot, build_snapshot(self.root))

    def test_native_response_and_body_are_preserved(self):
        self.change_usage('members', 'members.detail.read', lambda u: u.pop('overrides'))
        body = {'required': True, 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Member'}}}}
        self.change_api(lambda d: d['paths'][DETAIL]['get'].update(requestBody=body))
        effective = self.effective(build_snapshot(self.root))
        self.assertEqual(effective['responses'], self.read(SOURCE)['paths'][DETAIL]['get']['responses'])
        self.assertEqual(effective['request']['body'], {**body, 'source': 'input'})
        self.assertEqual(effective['request']['parameters'][0]['source'], 'input')

    def test_server_change_propagates_without_action_edits(self):
        before = build_snapshot(self.root)
        servers = [{'url': 'https://new.example.invalid'}, {'url': 'https://backup.example.invalid'}]
        self.change_api(lambda d: d.update(servers=servers))
        after = build_snapshot(self.root)
        self.assertEqual([r for r in before['resources'] if r['kind'] == 'Action'],
                         [r for r in after['resources'] if r['kind'] == 'Action'])
        for usage in after['pageActionUsages']:
            self.assertEqual(usage['effective']['service']['servers'], servers)
        self.assertNotEqual(before['contentSha256'], after['contentSha256'])

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
        self.assertEqual(response['204'], {'description': 'empty'})
        self.assertEqual(response['default'], {'description': 'error'})

    def test_projection_requires_single_json_content(self):
        self.change_api(lambda d: d['paths'][DETAIL]['get']['responses']['200']['content'].update(
            {'text/plain': {'schema': {'type': 'string'}}}))
        self.invalid('exactly one JSON media type')

    def test_projection_fails_closed_on_composition(self):
        self.change_api(lambda d: d['components']['schemas'].update(Member={
            'oneOf': [{'type': 'object', 'properties': {'id': {'type': 'string'}}},
                      {'type': 'object', 'properties': {'nickname': {'type': 'string'}}}]}))
        self.invalid('unambiguous schema')

    def test_referenced_parameter_constant_is_validated(self):
        def edit(d):
            d['components']['schemas']['Size'] = {'type': 'integer', 'maximum': 10}
            d['paths'][LIST]['get']['parameters'][2]['schema'] = {'$ref': '#/components/schemas/Size'}
        self.change_api(edit)
        self.invalid('constant.*violates endpoint schema')

    def test_recursive_schema_is_preserved_and_finite_projection_works(self):
        self.change_api(lambda d: d['components']['schemas']['Member']['properties'].update(
            manager={'$ref': '#/components/schemas/Member'}))
        self.change_usage('members', 'members.detail.read', lambda u: u['overrides']['responses']['200'].update(fields=['/manager/id']))
        self.assertEqual(self.effective(build_snapshot(self.root))['responses']['200']['fields'], ['/manager/id'])

    def test_openapi31_nullable_constant(self):
        def edit(d):
            d['openapi'] = '3.1.0'
            d['paths'][LIST]['get']['parameters'][2]['schema'] = {'type': ['integer', 'null'], 'maximum': 100}
        self.change_api(edit)
        self.change_usage('members', 'members.directory.list', lambda u: u['overrides']['request']['parameters'][1].update(value=None))
        effective = self.effective(build_snapshot(self.root), 'members', 'members.directory.list')
        self.assertIsNone(next(p for p in effective['request']['parameters'] if p['name'] == 'size')['value'])

    def test_schema_pointer_escaping(self):
        self.change_api(lambda d: d['components']['schemas']['Member']['properties'].update({'a/b': {'type': 'string'}, 'a~b': {'type': 'string'}}))
        self.change_usage('members', 'members.detail.read', lambda u: u['overrides']['responses']['200'].update(fields=['/a~1b', '/a~0b']))
        build_snapshot(self.root)
