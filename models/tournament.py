"""Pydantic models describing tournaments fetched from TenUp."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl


class Tournament(BaseModel):
    """Normalised representation of a TenUp tournament entry."""

    source: Literal["tenup"] = "tenup"
    external_id: str = Field(..., description="TenUp identifier when available")
    title: str
    discipline: Literal["PADEL"] = "PADEL"
    category: Literal["H", "F", "MIXTE"]
    level: Optional[str] = None
    start_date: str = Field(..., description="Tournament start date (ISO YYYY-MM-DD)")
    end_date: str = Field(..., description="Tournament end date (ISO YYYY-MM-DD)")
    city: Optional[str] = None
    postal_code: Optional[str] = None
    region: Optional[str] = None
    club_name: Optional[str] = None
    price: Optional[float] = None
    registration_url: HttpUrl
    details_url: HttpUrl
    inscriptions_open: Optional[bool] = None
    slots_total: Optional[int] = None
    slots_taken: Optional[int] = None
    created_at: str = Field(..., description="Creation timestamp in ISO format")

    model_config = {
        "extra": "ignore",
    }
