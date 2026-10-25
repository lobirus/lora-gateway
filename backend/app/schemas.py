from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10)


class ProviderIn(BaseModel):
    name: str
    slug: str | None = None
    kind: str = "openai_compatible"
    api_base: str | None = None
    api_key: str | None = None
    enabled: bool = False
    description: str | None = None


class ProviderPatch(BaseModel):
    name: str | None = None
    api_base: str | None = None
    api_key: str | None = None  # "" clears the key
    enabled: bool | None = None
    description: str | None = None


class ModelIn(BaseModel):
    provider_id: int
    model_name: str
    upstream_id: str
    display_name: str | None = None
    input_price_per_m: float = 0
    output_price_per_m: float = 0
    context_window: int | None = None
    enabled: bool = True
    tags: list[str] | None = None
    max_output_tokens: int | None = Field(default=None, ge=1, le=2_000_000)
    default_max_tokens: int | None = Field(default=None, ge=1, le=2_000_000)
    supports_reasoning: bool | None = None
    supports_vision: bool | None = None
    reasoning_efforts: list[Literal["off", "low", "medium", "high"]] | None = None


class ModelPatch(BaseModel):
    model_name: str | None = None
    upstream_id: str | None = None
    display_name: str | None = None
    input_price_per_m: float | None = None
    output_price_per_m: float | None = None
    context_window: int | None = None
    enabled: bool | None = None
    tags: list[str] | None = None
    max_output_tokens: int | None = Field(default=None, ge=1, le=2_000_000)
    default_max_tokens: int | None = Field(default=None, ge=1, le=2_000_000)
    supports_reasoning: bool | None = None
    supports_vision: bool | None = None
    reasoning_efforts: list[Literal["off", "low", "medium", "high"]] | None = None


class AliasIn(BaseModel):
    name: str
    target_model_id: int | None = None
    description: str | None = None


class AliasPatch(BaseModel):
    target_model_id: int | None = None
    description: str | None = None


class KeyIn(BaseModel):
    name: str
    max_budget: float | None = None
    budget_duration: str | None = None  # e.g. 30d, 7d, 1h
    rpm_limit: int | None = None
    tpm_limit: int | None = None
    models: list[str] | None = None
    expires_days: int | None = None


class KeyPatch(BaseModel):
    max_budget: float | None = None
    budget_duration: str | None = None
    rpm_limit: int | None = None
    tpm_limit: int | None = None
    models: list[str] | None = None
    clear_budget: bool = False


class TestIn(BaseModel):
    prompt: str = "Reply with exactly: pong"
    max_tokens: int = 64
