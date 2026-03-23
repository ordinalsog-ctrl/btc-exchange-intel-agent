from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    network: Mapped[str] = mapped_column(String(32), index=True)
    address: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    entity_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id"))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)

    entity: Mapped[Entity | None] = relationship()
    labels: Mapped[list["AddressLabel"]] = relationship(back_populates="address_rel")


class AddressLabel(Base):
    __tablename__ = "address_labels"
    __table_args__ = (
        UniqueConstraint("address_id", "source_name", "raw_ref", name="uq_address_source_raw_ref"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    address_id: Mapped[int] = mapped_column(ForeignKey("addresses.id"), index=True)
    source_name: Mapped[str] = mapped_column(String(128))
    source_type: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str] = mapped_column(Text)
    evidence_type: Mapped[str] = mapped_column(String(64))
    proof_type: Mapped[str] = mapped_column(String(64))
    confidence_hint: Mapped[float] = mapped_column(Float)
    raw_ref: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)

    address_rel: Mapped[Address] = relationship(back_populates="labels")


class CollectorRun(Base):
    __tablename__ = "collector_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_name: Mapped[str] = mapped_column(String(128), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    items_found: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)


def build_engine(database_url: str):
    return create_engine(database_url, future=True)


def build_session_factory(database_url: str):
    engine = build_engine(database_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def init_db(database_url: str) -> None:
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
