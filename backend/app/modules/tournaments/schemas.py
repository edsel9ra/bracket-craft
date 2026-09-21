from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


StageType = Literal[
    "round_robin",
    "single_elimination",
    "custom_group",
    "swiss",
    "double_elimination",
]


class CreateStageRequest(BaseModel):
    version_id: UUID
    name: str = Field(min_length=2, max_length=50)
    stage_type: StageType
    stage_order: int = Field(ge=1)


class CreateTournamentTeamRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    short_code: str = Field(min_length=2, max_length=10, pattern=r"^[A-Za-z0-9_-]+$")
    logo_url: str | None = Field(default=None, max_length=2048)
    stage_id: UUID | None = None
    group_id: UUID | None = None

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, value: str | None) -> str | None:
        if value is not None and not value.lower().startswith(("http://", "https://")):
            raise ValueError("logo_url debe usar http o https")
        return value


class BulkTournamentTeamItem(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    short_code: str = Field(min_length=2, max_length=10, pattern=r"^[A-Za-z0-9_-]+$")
    logo_url: str | None = Field(default=None, max_length=2048)

    @field_validator("logo_url")
    @classmethod
    def validate_logo_url(cls, value: str | None) -> str | None:
        if value is not None and not value.lower().startswith(("http://", "https://")):
            raise ValueError("logo_url debe usar http o https")
        return value


class BulkTournamentTeamRequest(BaseModel):
    teams: list[BulkTournamentTeamItem] = Field(min_length=1, max_length=200)
    stage_id: UUID | None = None
    group_id: UUID | None = None


class CreateRosterPlayerRequest(BaseModel):
    team_id: UUID
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    document_type: str = Field(default="internal", min_length=2, max_length=10)
    national_id: str = Field(min_length=3, max_length=100)
    issuing_country: str = Field(default="COL", min_length=2, max_length=3)
    birth_date: date
    dorsal_number: int = Field(ge=1, le=999)
    photo_url: str | None = Field(default=None, max_length=2048)
    photo_consent: bool = False

    @field_validator("issuing_country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        return value.upper()

    @field_validator("birth_date")
    @classmethod
    def validate_birth_date(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("birth_date no puede estar en el futuro")
        return value

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, value: str | None) -> str | None:
        return value

    @model_validator(mode="after")
    def reject_client_photo_url(self) -> "CreateRosterPlayerRequest":
        if self.photo_url is not None:
            raise ValueError("Las fotografías deben cargarse mediante el endpoint de fotos")
        return self


class RosterPlayerResponse(BaseModel):
    roster_id: UUID
    player_id: UUID
    team_id: UUID
    first_name: str
    last_name: str
    dorsal_number: int
    photo_url: str | None = None
    photo_consent: bool
    is_active: bool


class UpdatePhotoConsentRequest(BaseModel):
    photo_consent: bool


class BulkRosterPlayerResponse(BaseModel):
    count: int
    players: list[RosterPlayerResponse]
    warnings: list[str]


class CreateMatchRequest(BaseModel):
    version_id: UUID
    stage_id: UUID
    group_id: UUID | None = None
    home_team_id: UUID | None = None
    away_team_id: UUID | None = None
    matchday: int | None = Field(default=None, ge=1)
    match_date: datetime

    @field_validator("match_date")
    @classmethod
    def validate_match_date_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("match_date debe incluir zona horaria")
        return value


class GenerateSingleEliminationRequest(BaseModel):
    version_id: UUID
    stage_id: UUID
    start_date: datetime
    round_interval_days: int = Field(default=7, ge=1, le=365)
    match_interval_hours: int = Field(default=2, ge=1, le=168)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    replace_existing: bool = False
    legs: Literal[1, 2] = 2
    group_count: int | None = Field(default=None, ge=2, le=64)
    use_group_heads: bool = False
    head_team_ids: list[UUID] = Field(default_factory=list, max_length=64)
    swiss_rounds: int = Field(default=8, ge=1, le=64)
    swiss_round: int = Field(default=1, ge=1, le=64)
    swiss_home_target: int | None = Field(default=None, ge=0, le=64)
    swiss_away_target: int | None = Field(default=None, ge=0, le=64)

    @field_validator("start_date")
    @classmethod
    def validate_start_date_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("start_date debe incluir zona horaria")
        return value


class GenerateSingleEliminationResponse(BaseModel):
    version_id: UUID
    stage_id: UUID
    stage_type: StageType
    seed: int
    bracket_size: int | None = None
    round_count: int
    match_count: int
    bye_count: int
    group_count: int = 0
    round_number: int | None = None


class TournamentCreateResponse(BaseModel):
    id: UUID
    version_id: UUID
    status: str


class VersionSummaryResponse(BaseModel):
    id: UUID
    version_number: int
    status: str
    published_at: datetime | None = None
    created_at: datetime
    rules_config: dict[str, Any] | None = None


class CreateDraftVersionRequest(BaseModel):
    source_version_id: UUID | None = None


class VersionDetailResponse(VersionSummaryResponse):
    rules_config: dict[str, Any]


class StageSummaryResponse(BaseModel):
    id: UUID
    tournament_version_id: UUID
    name: str
    stage_type: StageType
    stage_order: int
    version_status: str | None = None


class TournamentTeamSummaryResponse(BaseModel):
    team_id: UUID
    name: str
    short_code: str
    logo_url: str | None = None
    status: str
    registered_at: datetime
    stage_ids: list[UUID] = Field(default_factory=list)


class TournamentTeamCreateResponse(BaseModel):
    team_id: UUID
    tournament_id: UUID


class BulkTournamentTeamResponse(BaseModel):
    count: int
    teams: list[TournamentTeamCreateResponse]


class TournamentMatchSummaryResponse(BaseModel):
    id: UUID
    tournament_version_id: UUID
    stage_id: UUID
    group_id: UUID | None = None
    bracket_code: str | None = None
    matchday: int | None = None
    match_date: datetime | None = None
    home_team_id: UUID | None = None
    home_team_name: str | None = None
    away_team_id: UUID | None = None
    away_team_name: str | None = None
    status: str
    home_score: int | None = None
    away_score: int | None = None
    winner_team_id: UUID | None = None


class TournamentSummaryResponse(BaseModel):
    id: UUID
    name: str
    season: str
    start_date: date
    status: str
    created_at: datetime | None = None
    draft_version_id: UUID | None = None


class PublishVersionResponse(BaseModel):
    version_id: UUID
    status: str


class PublicTournamentSummaryResponse(BaseModel):
    id: UUID
    name: str
    season: str
    start_date: date
    status: str


class PublicStageResponse(BaseModel):
    id: UUID
    name: str
    stage_type: StageType
    stage_order: int


class PublicTournamentResponse(PublicTournamentSummaryResponse):
    stages: list[PublicStageResponse] = Field(default_factory=list)


class PublicStandingResponse(BaseModel):
    tournament_id: UUID
    stage_id: UUID
    stage_name: str
    stage_order: int
    group_id: UUID | None = None
    group_name: str | None = None
    team_id: UUID
    team_name: str
    short_code: str
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int
    fair_play_points: int
    rank: int
    calculated_at: datetime | None = None


class PublicLineupPlayerResponse(BaseModel):
    player_id: UUID
    first_name: str
    last_name: str
    dorsal_number: int | None = None
    role: Literal["starter", "substitute"]
    position_slot: str | None = None
    photo_url: str | None = None


class PublicTeamLineupResponse(BaseModel):
    team_id: UUID
    team_name: str
    formation_code: str | None = None
    starters: list[PublicLineupPlayerResponse] = Field(default_factory=list)
    substitutes: list[PublicLineupPlayerResponse] = Field(default_factory=list)


class PublicMatchLineupResponse(BaseModel):
    home: PublicTeamLineupResponse | None = None
    away: PublicTeamLineupResponse | None = None


class PublicMatchResponse(BaseModel):
    id: UUID
    tournament_id: UUID
    stage_id: UUID
    stage_name: str
    stage_order: int
    group_id: UUID | None = None
    group_name: str | None = None
    bracket_code: str | None = None
    matchday: int | None = None
    match_date: datetime | None = None
    home_team_id: UUID | None = None
    home_team_name: str | None = None
    home_team_short_code: str | None = None
    away_team_id: UUID | None = None
    away_team_name: str | None = None
    away_team_short_code: str | None = None
    home_score_regular: int | None = None
    away_score_regular: int | None = None
    home_score: int | None = None
    away_score: int | None = None
    home_penalties: int | None = None
    away_penalties: int | None = None
    winner_team_id: UUID | None = None
    status: str
    resolution_type: str | None = None
    lineup: PublicMatchLineupResponse | None = None
