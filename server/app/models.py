"""Shared enums and request bodies (api-spec.md)."""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Level(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


LEVEL_ORDER = {Level.GREEN: 0, Level.AMBER: 1, Level.RED: 2}
LEVELS = [Level.GREEN, Level.AMBER, Level.RED]


def raise_level(level: Level, steps: int = 1) -> Level:
    return LEVELS[min(LEVEL_ORDER[level] + steps, 2)]


# ---- Settings (api-spec §9; spec §10.1 Constraints) ----

class Thresholds(BaseModel):
    amber_rate_mmh: float = Field(10, ge=0, le=100)
    red_rate_mmh: float = Field(30, ge=0, le=100)
    amber_p: float = Field(0.4, ge=0, le=1)
    red_p: float = Field(0.7, ge=0, le=1)
    wet_ground_mm24h: float = Field(50, ge=0, le=500)

    @model_validator(mode="after")
    def amber_below_red(self):
        if self.amber_rate_mmh >= self.red_rate_mmh:
            raise ValueError("amber_rate_mmh must be less than red_rate_mmh")
        if self.amber_p >= self.red_p:
            raise ValueError("amber_p must be less than red_p")
        return self


# ---- Automation (docs/automation-control.md): admin owns every Telegram announcement ----

Mode = Literal["auto", "approval", "off"]  # send · hold in "Needs approval" · don't announce
Event = Literal["amber", "red", "all_clear"]
EVENTS = ("amber", "red", "all_clear")
HHMM = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"


class EventModes(BaseModel):
    amber: Mode = "auto"
    red: Mode = "auto"
    all_clear: Mode = "auto"


class QuietHours(BaseModel):
    """MYT window in which auto-sends for the listed events are held for approval instead."""
    enabled: bool = False
    start: str = Field("23:00", pattern=HHMM)
    end: str = Field("06:00", pattern=HHMM)
    events: list[Event] = Field(default_factory=lambda: ["amber", "all_clear"])

    @model_validator(mode="after")
    def check(self):
        if self.start == self.end:
            raise ValueError("quiet hours start and end must differ")
        self.events = sorted(set(self.events), key=EVENTS.index)
        return self


class Automation(BaseModel):
    enabled: bool = True  # False = paused until an admin resumes
    paused_until: datetime | None = None  # timed pause
    modes: EventModes = EventModes()
    quiet_hours: QuietHours = QuietHours()
    zone_overrides: dict[str, Literal["approval", "off"]] = Field(default_factory=dict)
    use_ai_text: bool = True
    send_dms: bool = True
    auto_expires_min: int = Field(120, ge=15, le=1440)

    @model_validator(mode="after")
    def utc(self):
        if self.paused_until is not None and self.paused_until.tzinfo is None:
            self.paused_until = self.paused_until.replace(tzinfo=timezone.utc)
        return self


class EventModesPatch(BaseModel):
    amber: Mode | None = None
    red: Mode | None = None
    all_clear: Mode | None = None


class QuietHoursPatch(BaseModel):
    enabled: bool | None = None
    start: str | None = Field(None, pattern=HHMM)
    end: str | None = Field(None, pattern=HHMM)
    events: list[Event] | None = None


class AutomationPatch(BaseModel):
    enabled: bool | None = None
    modes: EventModesPatch | None = None
    quiet_hours: QuietHoursPatch | None = None
    zone_overrides: dict[str, Literal["approval", "off"]] | None = None  # replaces the whole map
    use_ai_text: bool | None = None
    send_dms: bool | None = None
    auto_expires_min: int | None = Field(None, ge=15, le=1440)
    cooldown_min: int | None = Field(None, ge=0, le=1440)
    all_clear_after_min: int | None = Field(None, ge=0, le=1440)
    pause_minutes: int | None = Field(None, ge=1, le=10080)  # timed pause
    resume: bool | None = None  # clears any pause


class AppSettings(BaseModel):
    thresholds: Thresholds = Thresholds()
    cooldown_min: int = Field(30, ge=0, le=1440)
    amber_requires_approval: bool = False  # legacy; mirrors automation.modes.amber == "approval"
    all_clear_after_min: int = Field(30, ge=0, le=1440)
    pipeline_enabled: bool = True
    automation: Automation = Automation()

    @model_validator(mode="before")
    @classmethod
    def legacy_amber(cls, data):
        if isinstance(data, dict) and data.get("automation") is None:
            data = {k: v for k, v in data.items() if k != "automation"}
            if data.get("amber_requires_approval"):
                data["automation"] = {"modes": {"amber": "approval"}}
        return data

    @model_validator(mode="after")
    def mirror_amber(self):
        self.amber_requires_approval = self.automation.modes.amber == "approval"
        return self


class SettingsPatch(BaseModel):
    thresholds: Thresholds | None = None
    cooldown_min: int | None = Field(None, ge=0, le=1440)
    amber_requires_approval: bool | None = None
    all_clear_after_min: int | None = Field(None, ge=0, le=1440)
    pipeline_enabled: bool | None = None


# ---- Me ----

class SyncBody(BaseModel):
    email: str | None = None
    full_name: str | None = None


class ProfilePatch(BaseModel):
    full_name: str | None = Field(None, max_length=120)
    language: Literal["en", "ms"] | None = None
    onboarded: bool | None = None


class SubscriptionIn(BaseModel):
    zone_id: str
    min_level: Level = Level.AMBER


class SubscriptionsPut(BaseModel):
    subscriptions: list[SubscriptionIn] = Field(default_factory=list, max_length=100)


# ---- Zones ----

class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)
    state: str | None = None
    district: str | None = None
    met_location_id: str | None = None
    match_terms: list[str] = Field(default_factory=list)
    lat: float = Field(ge=1.0, le=7.5)
    lon: float = Field(ge=99.0, le=105.0)
    radius_m: int = Field(2500, ge=500, le=20000)
    polygon: dict | None = None
    active: bool = True


class ZonePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    slug: str | None = Field(None, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=80)
    state: str | None = None
    district: str | None = None
    met_location_id: str | None = None
    match_terms: list[str] | None = None
    lat: float | None = Field(None, ge=1.0, le=7.5)
    lon: float | None = Field(None, ge=99.0, le=105.0)
    radius_m: int | None = Field(None, ge=500, le=20000)
    polygon: dict | None = None
    active: bool | None = None


# ---- Warnings ----

class WarningIn(BaseModel):
    zone_id: str
    level: Level
    message_en: str | None = Field(None, max_length=600)
    message_ms: str | None = Field(None, max_length=600)
    expires_in_min: int = Field(120, ge=5, le=1440)


class WarningTextPatch(BaseModel):
    message_en: str | None = Field(None, max_length=600)
    message_ms: str | None = Field(None, max_length=600)


class RoleBody(BaseModel):
    role: Literal["user", "admin"]


# ---- Reports ----

class ReportIn(BaseModel):
    type: Literal["daily", "event", "custom"] = "custom"
    zone_ids: list[str] = Field(default_factory=list)
    period_start: datetime
    period_end: datetime

    @model_validator(mode="after")
    def period_order(self):
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start")
        return self


# ---- Agent / internal ----

class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    conversation_id: str | None = None


class IngestBody(BaseModel):
    backfill_ts: datetime | None = None
    # "synthetic" replays the committed storm fixture (implementation-plan D2).
    fixture: Literal["synthetic"] | None = None
