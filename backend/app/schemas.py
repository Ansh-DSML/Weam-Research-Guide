import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_not_blank(v: str) -> str:
    if not v or not v.strip():
        raise ValueError("must not be blank")
    return v


class CompanyCreate(BaseModel):
    name: str
    meta: dict = Field(default_factory=dict)
    checks: dict = Field(default_factory=dict)
    notes: dict = Field(default_factory=dict)
    buckets: dict = Field(default_factory=dict)
    dm: dict = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        return _validate_not_blank(v)


class CompanyUpdate(BaseModel):
    meta: dict = Field(default_factory=dict)
    checks: dict = Field(default_factory=dict)
    notes: dict = Field(default_factory=dict)
    buckets: dict = Field(default_factory=dict)
    dm: dict = Field(default_factory=dict)


class CompanyRename(BaseModel):
    new_name: str

    @field_validator("new_name")
    @classmethod
    def new_name_not_blank(cls, v: str) -> str:
        return _validate_not_blank(v)


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    meta: dict
    checks: dict
    notes: dict
    buckets: dict
    dm: dict
    created_at: datetime.datetime
    updated_at: datetime.datetime


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    name: str
    attrs: dict
    source_refs: list


class EdgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    src_id: int
    dst_id: int
    rel_type: str
    attrs: dict
    source_refs: list


class GraphOut(BaseModel):
    nodes: list[NodeOut]
    edges: list[EdgeOut]
