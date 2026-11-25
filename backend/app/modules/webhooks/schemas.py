"""Modelos de la API de webhooks (spec 047, plan §5); todos con ``extra="forbid"``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from app.modules.webhooks.catalog import MAX_URL_LENGTH, validate_url

EventType = Literal["match_scheduled", "result_confirmed", "walkover_declared", "sanction_generated"]
DeliveryEventType = Literal[EventType, "webhook_test"]
DeliveryStatus = Literal["pending", "delivered", "failed", "rejected", "discarded"]


def _url(value: str) -> str:
    return validate_url(value)


def _types(value: list[str]) -> list[str]:
    return sorted(set(value))


class CreateWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=MAX_URL_LENGTH)
    event_types: list[EventType] = Field(min_length=1, max_length=4)

    _check_url = field_validator("url")(_url)
    _check_types = field_validator("event_types")(_types)


class UpdateWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, max_length=MAX_URL_LENGTH)
    event_types: list[EventType] | None = Field(default=None, min_length=1, max_length=4)
    is_active: StrictBool | None = None

    @field_validator("url")
    @classmethod
    def check_url(cls, value: str | None) -> str | None:
        return None if value is None else validate_url(value)

    @field_validator("event_types")
    @classmethod
    def check_types(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _types(value)

    @model_validator(mode="after")
    def at_least_one_value(self) -> UpdateWebhookRequest:
        if not self.model_fields_set:
            raise ValueError("Indica al menos un campo")
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Los campos enviados no pueden ser null")
        return self


class WebhookItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    url: str
    event_types: list[EventType]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CreatedWebhook(WebhookItem):
    secret: str


class WebhookSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: str


class WebhookTestDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_id: UUID


class WebhookDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    event_type: DeliveryEventType
    created_at: datetime
    attempts: int
    last_status_code: int | None
    status: DeliveryStatus
