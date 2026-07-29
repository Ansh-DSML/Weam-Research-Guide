"""Structured-field -> graph mapping. No LLM call, no network, no cost — this always runs on
every save and gives immediate graph value even for a company with zero free text.

Produces *specs* (what should exist), not database writes — graph_pipeline.py resolves specs
into actual node ids and calls graph_crud to persist them. Keeping this pure (no DB session)
makes it trivially unit-testable.
"""

from dataclasses import dataclass, field

COMPANY_NODE_TYPE = "Company"


@dataclass(frozen=True)
class NodeSpec:
    type: str
    name: str
    attrs: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EdgeSpec:
    src: tuple[str, str]  # (type, name)
    dst: tuple[str, str]
    rel_type: str
    attrs: dict = field(default_factory=dict)


def map_structured_fields(company_name: str, meta: dict, dm: dict, checks: dict) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    company_ref = (COMPANY_NODE_TYPE, company_name)
    nodes: list[NodeSpec] = []
    edges: list[EdgeSpec] = []

    category = (meta or {}).get("category", "").strip()
    if category:
        theme_ref = ("Theme", category)
        nodes.append(NodeSpec("Theme", category))
        edges.append(EdgeSpec(company_ref, theme_ref, "HAS_CATEGORY"))

    country = (meta or {}).get("country", "").strip()
    if country:
        location_ref = ("Location", country)
        nodes.append(NodeSpec("Location", country))
        edges.append(EdgeSpec(company_ref, location_ref, "LOCATED_IN"))

    dm_name = (dm or {}).get("name", "").strip()
    if dm_name:
        person_ref = ("Person", dm_name)
        dm_title = (dm or {}).get("title", "").strip()
        nodes.append(NodeSpec("Person", dm_name, attrs={"title": dm_title} if dm_title else {}))
        edges.append(EdgeSpec(person_ref, company_ref, "WORKS_AT"))

    touched_groups = sorted({
        key.rsplit(".", 1)[0]
        for key, checked in (checks or {}).items()
        if checked and "." in key
    })
    for group_path in touched_groups:
        theme_ref = ("Theme", group_path)
        nodes.append(NodeSpec("Theme", group_path))
        edges.append(EdgeSpec(company_ref, theme_ref, "TOUCHES_AREA"))

    return nodes, edges
