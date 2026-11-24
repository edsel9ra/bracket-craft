from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.modules.notifications.catalog import CHANNELS, NOTIFICATION_TYPES

NotificationType = Literal["match_scheduled", "result_confirmed", "walkover_declared", "sanction_generated"]
Channel = Literal["inbox", "email"]
PAIRS = len(NOTIFICATION_TYPES) * len(CHANNELS)


class NotificationQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class NotificationSanction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_name: str | None
    team_name: str | None
    matches_suspended: int


class NotificationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    type: NotificationType
    created_at: AwareDatetime
    read_at: AwareDatetime | None
    tournament_id: UUID
    tournament_name: str
    match_id: UUID | None
    home_team_name: str | None
    away_team_name: str | None
    match_count: int | None
    sanction: NotificationSanction | None


class NotificationPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[NotificationItem]
    unread_count: int
    total: int
    limit: int
    offset: int


class NotificationPreferenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: NotificationType
    channel: Channel
    enabled: StrictBool


class NotificationPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[NotificationPreferenceItem] = Field(min_length=PAIRS, max_length=PAIRS)

    @model_validator(mode="after")
    def every_pair_once(self) -> NotificationPreferences:
        if len({(item.type, item.channel) for item in self.items}) != PAIRS:
            raise ValueError("Debe indicar cada tipo y canal exactamente una vez")
        return self
