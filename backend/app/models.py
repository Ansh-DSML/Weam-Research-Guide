import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)

    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    checks: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    notes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    buckets: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    dm: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Lets the graph extraction pipeline (Phase 2) skip re-running the paid LLM extraction
    # when the free-text fields haven't actually changed since last time — e.g. ticking a
    # checkbox shouldn't burn a Groq API call.
    last_extracted_text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (UniqueConstraint("company_id", "type", "name", name="uq_node_company_type_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    attrs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Edge(Base):
    __tablename__ = "edges"
    __table_args__ = (
        UniqueConstraint("company_id", "src_id", "dst_id", "rel_type", name="uq_edge_company_src_dst_rel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    src_id: Mapped[int] = mapped_column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    dst_id: Mapped[int] = mapped_column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    rel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    attrs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
