import pytest

from app import crud


def test_create_get_roundtrip(db_session):
    company = crud.create_company(
        db_session,
        name="  Acme & Co  ",
        meta={"category": "HVAC & IAQ"},
        checks={"a.b": True},
    )
    assert company.name == "Acme & Co"  # trimmed, matching frontend .trim()

    fetched = crud.get_company(db_session, company.id)
    assert fetched.meta == {"category": "HVAC & IAQ"}
    assert fetched.checks == {"a.b": True}
    assert fetched.notes == {}
    assert fetched.buckets == {}
    assert fetched.dm == {}


def test_create_duplicate_name_raises(db_session):
    crud.create_company(db_session, name="Acme")
    with pytest.raises(crud.DuplicateNameError):
        crud.create_company(db_session, name="Acme")


def test_create_duplicate_name_after_trim_raises(db_session):
    crud.create_company(db_session, name="Acme")
    with pytest.raises(crud.DuplicateNameError):
        crud.create_company(db_session, name="  Acme  ")


def test_get_unknown_id_raises_not_found(db_session):
    with pytest.raises(crud.NotFoundError):
        crud.get_company(db_session, 999999)


def test_update_full_replace_no_field_bleed(db_session):
    company = crud.create_company(
        db_session,
        name="Acme",
        meta={"category": "HVAC & IAQ", "locations": "5"},
        checks={"a.b": True, "a.c": True},
        notes={"section1": "old note"},
        buckets={"p": [{"tag": "Fact", "text": "old finding"}]},
        dm={"name": "Old DM"},
    )

    updated = crud.update_company(
        db_session,
        company.id,
        meta={"category": "Plumbing"},
        checks={"a.b": True},
        notes={},
        buckets={},
        dm={},
    )

    assert updated.meta == {"category": "Plumbing"}
    assert "locations" not in updated.meta  # full replace, not merge — no stale field bleed
    assert updated.checks == {"a.b": True}
    assert updated.notes == {}
    assert updated.buckets == {}
    assert updated.dm == {}

    reloaded = crud.get_company(db_session, company.id)
    assert reloaded.meta == {"category": "Plumbing"}


def test_update_unknown_id_raises_not_found(db_session):
    with pytest.raises(crud.NotFoundError):
        crud.update_company(db_session, 999999, meta={}, checks={}, notes={}, buckets={}, dm={})


def test_rename_happy_path(db_session):
    company = crud.create_company(db_session, name="Old Name")
    renamed = crud.rename_company(db_session, company.id, "New Name")
    assert renamed.name == "New Name"
    assert renamed.id == company.id


def test_rename_onto_existing_name_raises_duplicate(db_session):
    crud.create_company(db_session, name="Taken")
    other = crud.create_company(db_session, name="Free")
    with pytest.raises(crud.DuplicateNameError):
        crud.rename_company(db_session, other.id, "Taken")
    # original name must be untouched after the failed rename
    reloaded = crud.get_company(db_session, other.id)
    assert reloaded.name == "Free"


def test_rename_to_same_name_is_a_noop_not_a_conflict(db_session):
    company = crud.create_company(db_session, name="Same")
    renamed = crud.rename_company(db_session, company.id, "Same")
    assert renamed.name == "Same"


def test_rename_unknown_id_raises_not_found(db_session):
    with pytest.raises(crud.NotFoundError):
        crud.rename_company(db_session, 999999, "Whatever")


def test_list_companies_sorted_by_updated_at_desc(db_session):
    c1 = crud.create_company(db_session, name="First")
    c2 = crud.create_company(db_session, name="Second")
    # touch c1 again so it becomes most-recently-updated
    crud.update_company(db_session, c1.id, meta={"touched": True}, checks={}, notes={}, buckets={}, dm={})

    names_in_order = [c.name for c in crud.list_companies(db_session)]
    assert names_in_order[0] == "First"
    assert "Second" in names_in_order
    assert c2.id  # keep reference used, avoids unused-var lint noise


def test_unicode_and_special_chars_round_trip(db_session):
    name = "Acme & Co / Tëst Ünïcödé 株式会社"
    company = crud.create_company(
        db_session,
        name=name,
        meta={"notes": "emoji 🚀 and \"quotes\" and a newline\nhere"},
    )
    fetched = crud.get_company(db_session, company.id)
    assert fetched.name == name
    assert fetched.meta["notes"] == "emoji 🚀 and \"quotes\" and a newline\nhere"
