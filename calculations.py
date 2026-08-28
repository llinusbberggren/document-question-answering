"""Deterministic calculations used when answering document questions."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Iterable


@dataclass(frozen=True)
class PriceTier:
    minimum_kg: float
    price_per_kg: float
    maximum_kg: float | None = None

    def __post_init__(self) -> None:
        if self.minimum_kg < 0 or self.price_per_kg < 0:
            raise ValueError("Price tier values cannot be negative")
        if self.maximum_kg is not None and self.maximum_kg < self.minimum_kg:
            raise ValueError("Price tier maximum cannot be below its minimum")

    def applies_to(self, weekly_kg: float) -> bool:
        return weekly_kg >= self.minimum_kg and (
            self.maximum_kg is None or weekly_kg <= self.maximum_kg
        )


def total_weekly_buns(orders: Iterable[int]) -> int:
    order_values = list(orders)
    if any(value < 0 for value in order_values):
        raise ValueError("Order quantities cannot be negative")
    return sum(order_values)


def weekly_sugar_kg(
    weekly_buns: int,
    buns_per_batch: int,
    dough_sugar_kg: float,
    filling_sugar_kg: float,
) -> float:
    """Calculate bulk fine sugar use, excluding decorative pearl sugar."""
    if weekly_buns < 0 or buns_per_batch <= 0:
        raise ValueError("Bun quantities must be non-negative and batch size positive")
    sugar_per_batch = dough_sugar_kg + filling_sugar_kg
    return weekly_buns / buns_per_batch * sugar_per_batch


def ingredient_kg_for_buns(
    buns: int,
    buns_per_batch: int,
    ingredient_kg_per_batch: float,
) -> float:
    if buns < 0 or buns_per_batch <= 0 or ingredient_kg_per_batch < 0:
        raise ValueError("Bun quantities and ingredient quantity must be valid")
    return buns / buns_per_batch * ingredient_kg_per_batch


def price_for_volume(weekly_kg: float, tiers: Iterable[PriceTier]) -> float:
    if weekly_kg < 0:
        raise ValueError("Weekly volume cannot be negative")
    for tier in tiers:
        if tier.applies_to(weekly_kg):
            return tier.price_per_kg
    raise ValueError(f"No price tier applies to {weekly_kg:g} kg per week")


def contract_price(
    weekly_kg: float,
    tiers: Iterable[PriceTier],
    rebate_per_kg: float,
) -> float:
    price = price_for_volume(weekly_kg, tiers) - rebate_per_kg
    if price < 0:
        raise ValueError("Contract rebate cannot make the price negative")
    return price


def freight_cost(
    shipment_kg: float,
    origin_rail_rate_per_100kg: float,
    origin_rail_minimum: float,
    steamer_tiers: Iterable[PriceTier],
    destination_rail_rate_per_100kg: float,
    destination_rail_minimum: float,
    handling_fee: float,
) -> float:
    """Calculate freight, excluding refundable deposits and optional insurance."""
    if shipment_kg <= 0:
        raise ValueError("Shipment weight must be positive")

    origin_rail = max(shipment_kg / 100 * origin_rail_rate_per_100kg, origin_rail_minimum)
    steamer_rate = price_for_volume(shipment_kg, steamer_tiers)
    steamer = shipment_kg / 100 * steamer_rate
    destination_rail = max(
        shipment_kg / 100 * destination_rail_rate_per_100kg,
        destination_rail_minimum,
    )
    return origin_rail + steamer + destination_rail + handling_fee


def compare_freight(
    weekly_kg: float,
    weeks_per_month: int,
    origin_rail_rate_per_100kg: float,
    origin_rail_minimum: float,
    steamer_tiers: Iterable[PriceTier],
    destination_rail_rate_per_100kg: float,
    destination_rail_minimum: float,
    handling_fee: float,
) -> dict[str, float]:
    if weekly_kg <= 0 or weeks_per_month <= 0:
        raise ValueError("Weekly weight and weeks per month must be positive")
    monthly_kg = weekly_kg * weeks_per_month
    weekly_shipment = freight_cost(
        weekly_kg, origin_rail_rate_per_100kg, origin_rail_minimum,
        steamer_tiers, destination_rail_rate_per_100kg,
        destination_rail_minimum, handling_fee,
    )
    monthly_shipment = freight_cost(
        monthly_kg, origin_rail_rate_per_100kg, origin_rail_minimum,
        steamer_tiers, destination_rail_rate_per_100kg,
        destination_rail_minimum, handling_fee,
    )
    weekly_total = weekly_shipment * weeks_per_month
    return {
        "weekly_kg": weekly_kg,
        "monthly_kg": monthly_kg,
        "weekly_total": weekly_total,
        "monthly_total": monthly_shipment,
        "weekly_per_kg": weekly_total / monthly_kg,
        "monthly_per_kg": monthly_shipment / monthly_kg,
    }


def round_trip_travel_cost(
    train_one_way: float,
    boat_one_way: float,
    gj_one_way: float = 0.0,
) -> float:
    if min(train_one_way, boat_one_way, gj_one_way) < 0:
        raise ValueError("Travel costs cannot be negative")
    return 2 * (train_one_way + boat_one_way + gj_one_way)


def buns_within_sugar_budget(
    budget: float,
    sugar_price_per_kg: float,
    sugar_kg_per_batch: float,
    buns_per_batch: int,
) -> int:
    if budget < 0 or sugar_price_per_kg <= 0 or sugar_kg_per_batch <= 0 or buns_per_batch <= 0:
        raise ValueError("Budget and quantities must be valid non-negative values")
    affordable_batches = floor(budget / (sugar_price_per_kg * sugar_kg_per_batch) + 1e-9)
    return affordable_batches * buns_per_batch
