from app.graph_mapper import EdgeSpec, NodeSpec, map_structured_fields


def test_empty_company_produces_zero_nodes():
    nodes, edges = map_structured_fields("Acme", meta={}, dm={}, checks={})
    assert nodes == []
    assert edges == []


def test_only_dm_name_set_produces_only_person_node_and_edge():
    nodes, edges = map_structured_fields("Acme", meta={}, dm={"name": "Jane Doe"}, checks={})
    assert nodes == [NodeSpec("Person", "Jane Doe", attrs={})]
    assert edges == [EdgeSpec(("Person", "Jane Doe"), ("Company", "Acme"), "WORKS_AT")]


def test_dm_name_and_title_carries_title_in_attrs():
    nodes, _ = map_structured_fields("Acme", meta={}, dm={"name": "Jane Doe", "title": "CEO"}, checks={})
    assert nodes == [NodeSpec("Person", "Jane Doe", attrs={"title": "CEO"})]


def test_category_produces_theme_node_and_edge():
    nodes, edges = map_structured_fields("Acme", meta={"category": "HVAC & IAQ"}, dm={}, checks={})
    assert nodes == [NodeSpec("Theme", "HVAC & IAQ")]
    assert edges == [EdgeSpec(("Company", "Acme"), ("Theme", "HVAC & IAQ"), "HAS_CATEGORY")]


def test_country_produces_location_node_and_edge():
    nodes, edges = map_structured_fields("Acme", meta={"country": "US"}, dm={}, checks={})
    assert nodes == [NodeSpec("Location", "US")]
    assert edges == [EdgeSpec(("Company", "Acme"), ("Location", "US"), "LOCATED_IN")]


def test_ticked_checks_produce_one_theme_per_distinct_group_no_duplicates():
    checks = {
        "setup.icp.employees": True,
        "setup.icp.revenue": True,  # same group as above — should not double up
        "ops.leadership.ceo": True,
        "ops.leadership.cfo": False,  # unticked — must not appear at all
    }
    nodes, edges = map_structured_fields("Acme", meta={}, dm={}, checks=checks)
    theme_names = sorted(n.name for n in nodes)
    assert theme_names == ["ops.leadership", "setup.icp"]
    assert len(edges) == 2
    assert all(e.rel_type == "TOUCHES_AREA" for e in edges)


def test_blank_whitespace_fields_are_treated_as_absent():
    nodes, edges = map_structured_fields("Acme", meta={"category": "   ", "country": ""}, dm={"name": "  "}, checks={})
    assert nodes == []
    assert edges == []


def test_full_company_produces_all_node_types():
    nodes, edges = map_structured_fields(
        "Acme",
        meta={"category": "Plumbing", "country": "US"},
        dm={"name": "Jane Doe", "title": "CEO"},
        checks={"setup.icp.employees": True},
    )
    types = sorted(n.type for n in nodes)
    assert types == ["Location", "Person", "Theme", "Theme"] or types == sorted(["Theme", "Location", "Person", "Theme"])
    assert len(nodes) == 4  # Theme(category), Location, Person, Theme(group)
    assert len(edges) == 4


def test_calling_twice_with_identical_input_is_deterministic_and_idempotent_at_spec_level():
    args = dict(meta={"category": "Plumbing"}, dm={"name": "Jane Doe"}, checks={"a.b": True})
    first = map_structured_fields("Acme", **args)
    second = map_structured_fields("Acme", **args)
    assert first == second  # same specs every time -> downstream upsert stays idempotent
