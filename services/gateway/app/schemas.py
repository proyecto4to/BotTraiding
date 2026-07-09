"""Pydantic request/response schemas for the gateway config API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# -- markets -----------------------------------------------------------------


class MarketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    asset_class: str
    enabled: bool
    trading_hours: dict
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MarketUpdate(BaseModel):
    """PATCH body for a market: config-only fields (enable/disable + hours).

    Identity fields (name/code/asset_class) are seeded by migration and not
    editable through the API.
    """

    enabled: bool | None = None
    trading_hours: dict | None = None


# -- symbols -----------------------------------------------------------------


class SymbolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    market_id: str
    ticker: str
    name: str | None = None
    is_active: bool
    created_at: datetime | None = None


class SymbolCreate(BaseModel):
    market_id: str
    ticker: str = Field(min_length=1, max_length=50)
    name: str | None = Field(default=None, max_length=255)


class SymbolUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


# -- per-user market settings -------------------------------------------------


class UserMarketSettingIn(BaseModel):
    market_id: str
    enabled: bool


class UserMarketOut(BaseModel):
    """A market as seen by one user: global flag + the user's own toggle.

    effective_enabled = market.enabled AND user_enabled; a user can never
    activate a market an admin disabled globally.
    """

    market_id: str
    name: str
    code: str
    asset_class: str
    market_enabled: bool
    user_enabled: bool
    effective_enabled: bool
