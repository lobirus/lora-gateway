from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
                        JSON, create_engine, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import settings

engine = create_engine(settings.gateway_db_url, pool_pre_ping=True, pool_size=5, max_overflow=5)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

ll_engine = create_engine(settings.litellm_db_url, pool_pre_ping=True, pool_size=3, max_overflow=3)


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32))  # together|openai|anthropic|openrouter|xai|zai|openai_compatible
    api_base: Mapped[str | None] = mapped_column(String(300), nullable=True)
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    models: Mapped[list["Model"]] = relationship(back_populates="provider", cascade="all, delete-orphan")


class Model(Base):
    __tablename__ = "models"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id", ondelete="CASCADE"), index=True)
    model_name: Mapped[str] = mapped_column(String(200), unique=True, index=True)  # public name clients use
    upstream_id: Mapped[str] = mapped_column(String(300))
    display_name: Mapped[str] = mapped_column(String(200))
    input_price_per_m: Mapped[float] = mapped_column(Float, default=0.0)
    output_price_per_m: Mapped[float] = mapped_column(Float, default=0.0)
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # capabilities (None = unknown -> heuristics); used by the Playground for defaults and guards
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)   # hard cap for max_tokens
    default_max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Playground default
    supports_reasoning: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    supports_vision: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # accepted Playground reasoning levels, e.g. ["off", "low", "high"]; None/[] = no control
    reasoning_efforts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    provider: Mapped[Provider] = relationship(back_populates="models")


class Alias(Base):
    __tablename__ = "aliases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    target_model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id", ondelete="SET NULL"), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    target: Mapped[Model | None] = relationship()


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    key_enc: Mapped[str] = mapped_column(Text)
    key_prefix: Mapped[str] = mapped_column(String(32))
    token_hash: Mapped[str] = mapped_column(String(128), index=True)
    max_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_duration: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    models: Mapped[list | None] = mapped_column(JSON, nullable=True)  # None/[] = all models
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# additive column migrations for existing installs (create_all never alters tables)
_MIGRATIONS = [
    "ALTER TABLE models ADD COLUMN IF NOT EXISTS max_output_tokens INTEGER",
    "ALTER TABLE models ADD COLUMN IF NOT EXISTS default_max_tokens INTEGER",
    "ALTER TABLE models ADD COLUMN IF NOT EXISTS supports_reasoning BOOLEAN",
    "ALTER TABLE models ADD COLUMN IF NOT EXISTS supports_vision BOOLEAN",
    "ALTER TABLE models ADD COLUMN IF NOT EXISTS reasoning_efforts JSON",
]


def init_db():
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        for stmt in _MIGRATIONS:
            c.execute(text(stmt))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
