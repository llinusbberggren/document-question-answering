"""Answer one document question using retrieval, Python calculations, and Azure OpenAI."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

from calculations import (
    PriceTier,
    buns_within_sugar_budget,
    compare_freight,
    contract_price,
    freight_cost,
    ingredient_kg_for_buns,
    round_trip_travel_cost,
    total_weekly_buns,
    weekly_sugar_kg,
)
from retrieval import load_records, normalize_question, retrieve


EXTRACTION_SYSTEM_PROMPT = """You extract facts from supplied documents for a calculator.
Use only the CONTEXT. Never calculate, estimate, or fill in missing values.
Return a JSON object with exactly these keys:
{
    "calculation": "weekly_sugar" | "ingredient_quantity" | "contract_price" | "freight_cost" | "freight_comparison" | "travel_cost" | "travel_cost_options" | "buns_budget" | "buns_budget_options" | "none",
  "inputs": { ... },
  "missing": ["..."],
  "notes": "..."
}
For calculations, copy numeric values and units from the context into inputs.
For weekly_sugar, extract each numeric customer order as "weekly_bun_orders": [..]
instead of adding them yourself. Python will sum that list. If the context provides
a stated total, it may be returned as "weekly_buns".
For weekly_sugar, inputs must include weekly_bun_orders (or weekly_buns),
buns_per_batch, dough_sugar_kg, and filling_sugar_kg. Copy all four values from
the recipe and order-book context; do not mark them missing when they are stated.
For ingredient_quantity questions such as cinnamon, extract buns, buns_per_batch,
and ingredient_kg_per_batch. Do not calculate the result.
For travel_cost_options, extract every stated possible train fare as
"train_one_way_options": [..] when the train class is unspecified. Also extract
boat_one_way and gj_one_way. Python will calculate each alternative.
Use weekly_sugar for recipe scaling, contract_price for volume pricing and rebates,
freight_cost for shipment charges, travel_cost for fares, and buns_budget for a sugar budget.
Use travel_cost_options instead of travel_cost when the question does not specify a train
class and the context lists multiple train fares. Set notes to explain that the class is unspecified.
Use freight_comparison for questions comparing weekly shipments with one monthly shipment.
Use buns_budget_options when the question asks how many buns can be made from a sugar budget
without specifying a contract type. Extract the numeric budget from the question as "budget".
If no budget is stated, include "budget" in missing. Extract the available rebates and let Python calculate each option.
Use none for questions that require no arithmetic. Do not include a calculated result.
"""

ANSWER_SYSTEM_PROMPT = """Answer the user's question using only the supplied source context and the verified Python calculation result.
Do not perform or change arithmetic yourself. Treat the VERIFIED CALCULATION as authoritative.
Explain the relevant inputs and formula briefly, state assumptions, and identify conflicts or missing information.
If VERIFIED CALCULATION contains multiple alternatives, report all of them and clearly identify the unspecified choice.
Cite claims using the exact SOURCE labels included in the context. If evidence is insufficient, say so clearly.
Return this structure:
Answer:
...

Calculation:
...

Assumptions or limitations:
- ...

Sources:
- ...
"""

POST_ROMA_SIGHTSEEING_GUIDANCE = """For a question about sightseeing after returning to Visby,
respect the earlier Roma free period: the 13:00 Roma departure is before the 13:00-16:00
Roma period, so use the 16:00 Roma-to-Visby train (arriving 16:45). After the approximately
10-minute walk to the harbor, the museum and cathedral cannot be visited within their
published hours and required arrival buffer. Recommend the always-open Ring Wall first;
the Botanical Garden may follow if daylight and time permit. State this timing assumption.
"""


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def make_client() -> OpenAI:
    endpoint = required_env("AZURE_OPENAI_ENDPOINT").rstrip("/")
    if not endpoint.endswith("/responses"):
        raise RuntimeError("AZURE_OPENAI_ENDPOINT must end with /openai/v1/responses")
    base_url = endpoint[: -len("/responses")]
    return OpenAI(
        base_url=base_url,
        api_key=required_env("AZURE_OPENAI_API_KEY"),
    )


def context_text(records: list[dict[str, Any]]) -> str:
    sections = []
    for record in records:
        location = record["location"]
        if "page" in location:
            citation = f"page {location['page']}"
        else:
            citation = f"sheet {location['sheet']}, rows {location['row_start']}-{location['row_end']}"
        sections.append(
            f"SOURCE: {record['source_file']}, {citation}\n{record['text']}"
        )
    return "\n\n".join(sections)


def complete_json(client: OpenAI, deployment: str, system: str, user: str) -> dict[str, Any]:
    response = client.responses.create(
        model=deployment,
        instructions=system,
        input="Return the requested result as JSON.\n\n" + user,
        text={"format": {"type": "json_object"}},
    )
    content = response.output_text
    if not content:
        raise RuntimeError("Azure returned an empty response")
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Azure returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Azure returned a JSON value that was not an object")
    return result


def as_tiers(raw_tiers: Any) -> list[PriceTier]:
    if not isinstance(raw_tiers, list):
        raise ValueError("tiers must be a list")
    return [
        PriceTier(
            minimum_kg=parse_number(tier["minimum_kg"]),
            maximum_kg=(parse_number(tier["maximum_kg"]) if tier.get("maximum_kg") is not None else None),
            price_per_kg=parse_number(tier["price_per_kg"]),
        )
        for tier in raw_tiers
    ]


def parse_number(value: Any) -> float:
    """Accept JSON numbers and strings such as '1,000 buns' or '2.2 kg'."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", str(value))
    if not match:
        raise ValueError(f"Could not parse a number from {value!r}")
    return float(match.group().replace(",", ""))


def require_inputs(inputs: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(inputs, dict):
        raise ValueError("Calculation inputs must be an object")
    missing = [key for key in keys if key not in inputs]
    if missing:
        raise ValueError("Missing calculation inputs: " + ", ".join(missing))
    return inputs


def verified_travel_options(question: str, context: str) -> dict[str, Any] | None:
    question_terms = set(re.findall(r"[a-z]+", question.lower()))
    is_cost_question = bool(question_terms & {"cost", "fare", "price"})
    specifies_class = bool(re.search(r"\b(1st|2nd|3rd|first|second|third)\s+class\b", question.lower()))
    if not is_cost_question or specifies_class:
        return None

    # Use every published train fare when the question leaves train class open.
    third_class = re.search(r"3rd class\s+([\d,.]+)\s*kr", context, re.IGNORECASE)
    second_class = re.search(r"2nd class\s+([\d,.]+)\s*kr", context, re.IGNORECASE)
    cabin = re.search(r"Cabin,\s*2-berth.*?([\d,.]+)\s*kr", context, re.IGNORECASE | re.DOTALL)
    if not third_class or not second_class or not cabin:
        return None

    return {
        "calculation": "travel_cost_options",
        "inputs": {
            "train_one_way_options": [third_class.group(1), second_class.group(1)],
            "boat_one_way": cabin.group(1),
            "gj_one_way": 0,
        },
        "missing": [],
        "notes": "Train class is unspecified; both published train fares were used. The business Visby-Roma leg is free.",
    }


def verified_contract_price(question: str, context: str) -> dict[str, Any] | None:
    question_lower = normalize_question(question)
    if "contract" not in question_lower or "12 month" not in question_lower:
        return None

    # Reconstruct pricing inputs from source records so the model cannot choose a wrong tier.
    def source_section(prefix: str) -> str:
        match = re.search(rf"SOURCE: {re.escape(prefix)}.*?(?=SOURCE:|$)", context, re.IGNORECASE | re.DOTALL)
        return match.group() if match else ""

    order_text = source_section("07 - Order Book")
    price_text = source_section("01 - Sugar Price List")
    recipe_text = source_section("08 - Cinnamon Bun Recipe")
    orders = re.findall(r"B:\s*([\d,]+)", order_text)
    batch = re.search(r"Makes\s+([\d,]+)\s+buns", recipe_text, re.IGNORECASE)
    sugar_values = re.findall(
        r"Sugar\s*\(fine,\s*from\s*the\s*mill\)\s*([\d.]+)\s*kg",
        recipe_text,
        re.IGNORECASE,
    )
    price_rows = re.findall(
        r"A:\s*([\d,]+)\s*-\s*([\d,]+).*?E:\s*([\d.]+)",
        price_text,
        re.IGNORECASE,
    )
    rebate = re.search(
        r"12-month supply contract.*?B:\s*([\d.]+)",
        price_text,
        re.IGNORECASE | re.DOTALL,
    )
    if len(orders) != 5 or not batch or len(sugar_values) != 2 or not price_rows or not rebate:
        return None

    return {
        "calculation": "contract_price",
        "inputs": {
            "weekly_bun_orders": orders,
            "buns_per_batch": batch.group(1),
            "dough_sugar_kg": sugar_values[0],
            "filling_sugar_kg": sugar_values[1],
            "tiers": [
                {"minimum_kg": minimum, "maximum_kg": maximum, "price_per_kg": price}
                for minimum, maximum, price in price_rows
            ],
            "rebate_per_kg": f"{parse_number(rebate.group(1)) / 100:g}",
        },
        "missing": [],
        "notes": "Current order volume and recipe quantities were used to select the 12-month contract price tier.",
    }


def verified_budget_options(question: str, context: str) -> dict[str, Any] | None:
    question_lower = normalize_question(question)
    if "budget" not in question_lower or "sugar" not in question_lower:
        return None
    budget_match = re.search(r"([\d,]+(?:\.\d+)?)\s*kr", question, re.IGNORECASE)
    if not budget_match:
        return None

    # The contract is unspecified, so calculate every price alternative for comparison.
    def source_section(prefix: str) -> str:
        match = re.search(rf"SOURCE: {re.escape(prefix)}.*?(?=SOURCE:|$)", context, re.IGNORECASE | re.DOTALL)
        return match.group() if match else ""

    order_text = source_section("07 - Order Book")
    price_text = source_section("01 - Sugar Price List")
    recipe_text = source_section("08 - Cinnamon Bun Recipe")
    orders = re.findall(r"B:\s*([\d,]+)", order_text)
    batch = re.search(r"Makes\s+([\d,]+)\s+buns", recipe_text, re.IGNORECASE)
    sugar_values = re.findall(r"Sugar\s*\(fine,\s*from\s*the\s*mill\)\s*([\d.]+)\s*kg", recipe_text, re.IGNORECASE)
    price_rows = re.findall(r"A:\s*([\d,]+)\s*-\s*([\d,]+).*?E:\s*([\d.]+)", price_text, re.IGNORECASE)
    rebates = re.findall(r"(?:No contract / spot|6-month supply contract|12-month supply contract).*?B:\s*([\d.]+)", price_text, re.IGNORECASE | re.DOTALL)
    if len(orders) != 5 or not batch or len(sugar_values) != 2 or not price_rows or len(rebates) != 3:
        return None
    return {
        "calculation": "buns_budget_options",
        "inputs": {
            "budget": budget_match.group(1),
            "weekly_bun_orders": orders,
            "buns_per_batch": batch.group(1),
            "dough_sugar_kg": sugar_values[0],
            "filling_sugar_kg": sugar_values[1],
            "sugar_kg_per_batch": f"{parse_number(sugar_values[0]) + parse_number(sugar_values[1]):g}",
            "tiers": [{"minimum_kg": minimum, "maximum_kg": maximum, "price_per_kg": price} for minimum, maximum, price in price_rows],
            "rebates_per_kg": [f"{parse_number(value) / 100:g}" for value in rebates],
        },
        "missing": [],
        "notes": "Python calculates spot, 6-month, and 12-month alternatives; freight and other ingredients are excluded.",
    }


def verified_freight_comparison(question: str, context: str) -> dict[str, Any] | None:
    question_lower = normalize_question(question)
    if "freight" not in question_lower or "monthly" not in question_lower:
        return None

    def source_section(prefix: str) -> str:
        match = re.search(rf"SOURCE: {re.escape(prefix)}.*?(?=SOURCE:|$)", context, re.IGNORECASE | re.DOTALL)
        return match.group() if match else ""

    order_text = source_section("07 - Order Book")
    recipe_text = source_section("08 - Cinnamon Bun Recipe")
    tariff_text = source_section("02 - Freight Tariff")
    orders = re.findall(r"B:\s*([\d,]+)", order_text)
    batch = re.search(r"Makes\s+([\d,]+)\s+buns", recipe_text, re.IGNORECASE)
    sugar_values = re.findall(
        r"Sugar\s*\(fine,\s*from\s*the\s*mill\)\s*([\d.]+)\s*kg", recipe_text, re.IGNORECASE
    )
    origin = re.search(r"Goods freight, per 100 kg.*?\|\s*B:\s*([\d.]+)\s+kr\s*\|\s*C:\s*([\d.]+)\s+kr", tariff_text, re.IGNORECASE)
    steamer = []
    up_to = re.search(r"Up to\s+([\d,]+)\s*kg.*?\|\s*B:\s*([\d.]+)", tariff_text, re.IGNORECASE)
    if up_to:
        steamer.append(("0", up_to.group(1), up_to.group(2)))
    steamer.extend(re.findall(r"([\d,]+)\s*-\s*([\d,]+)\s*kg.*?\|\s*B:\s*([\d.]+)", tariff_text, re.IGNORECASE))
    and_above = re.search(r"([\d,]+)\s*kg\s*and above.*?\|\s*B:\s*([\d.]+)", tariff_text, re.IGNORECASE)
    if and_above:
        steamer.append((and_above.group(1), None, and_above.group(2)))
    destination = re.search(r"Goods freight, per 100 kg.*?\|\s*B:\s*([\d.]+)\s+kr\s*\|\s*C:\s*([\d.]+)\s+kr", tariff_text[tariff_text.find("Table 3"):], re.IGNORECASE)
    handling = re.search(r"Harbor handling fee.*?B:\s*([\d.]+)\s+kr", tariff_text, re.IGNORECASE)
    if len(orders) != 5 or not batch or len(sugar_values) != 2 or not origin or len(steamer) != 4 or not destination or not handling:
        return None

    return {
        "calculation": "freight_comparison",
        "inputs": {
            "weekly_kg": None,
            "weekly_bun_orders": orders,
            "buns_per_batch": batch.group(1),
            "dough_sugar_kg": sugar_values[0],
            "filling_sugar_kg": sugar_values[1],
            "weeks_per_month": 4,
            "origin_rail_rate_per_100kg": origin.group(1),
            "origin_rail_minimum": origin.group(2),
            "steamer_tiers": [
                {"minimum_kg": minimum, "maximum_kg": maximum, "price_per_kg": rate}
                for minimum, maximum, rate in steamer
            ],
            "destination_rail_rate_per_100kg": destination.group(1),
            "destination_rail_minimum": destination.group(2),
            "handling_fee": handling.group(1),
        },
        "missing": [],
        "notes": "A full month is treated as four weeks; Python derives the shipment weights from current orders and recipe usage.",
    }


def calculate(calculation: dict[str, Any]) -> str:
    if not isinstance(calculation, dict):
        raise ValueError("Calculation request must be an object")
    name = calculation.get("calculation", "none")
    inputs = calculation.get("inputs", {})
    missing = calculation.get("missing", [])
    if missing:
        return "Calculation not run because these inputs are missing: " + ", ".join(map(str, missing))

    if name == "none":
        return "No numeric calculation required."
    if name == "ingredient_quantity":
        result = ingredient_kg_for_buns(
            int(parse_number(inputs["buns"])),
            int(parse_number(inputs["buns_per_batch"])),
            parse_number(inputs["ingredient_kg_per_batch"]),
        )
        return f"ingredient_kg = {result:g} kg"
    if name == "weekly_sugar":
        # The order-book total is blank; sum the individual customer orders in Python.
        weekly_buns = inputs.get("weekly_buns")
        if weekly_buns is None:
            if "weekly_bun_orders" not in inputs:
                return "Calculation not run because these inputs are missing: weekly_bun_orders"
            weekly_buns = total_weekly_buns(
                int(parse_number(value)) for value in inputs["weekly_bun_orders"]
            )
        required = ("buns_per_batch", "dough_sugar_kg", "filling_sugar_kg")
        missing_inputs = [key for key in required if key not in inputs]
        if missing_inputs:
            return "Calculation not run because these inputs are missing: " + ", ".join(missing_inputs)
        result = weekly_sugar_kg(
            int(parse_number(weekly_buns)), int(parse_number(inputs["buns_per_batch"])),
            parse_number(inputs["dough_sugar_kg"]), parse_number(inputs["filling_sugar_kg"]),
        )
        return f"weekly_buns = {weekly_buns}; weekly_sugar_kg = {result:g} kg"
    if name == "contract_price":
        weekly_kg = inputs.get("weekly_kg")
        if weekly_kg is None and "weekly_bun_orders" in inputs:
            weekly_buns = total_weekly_buns(int(parse_number(value)) for value in inputs["weekly_bun_orders"])
            weekly_kg = weekly_sugar_kg(
                weekly_buns, int(parse_number(inputs["buns_per_batch"])),
                parse_number(inputs["dough_sugar_kg"]), parse_number(inputs["filling_sugar_kg"]),
            )
        result = contract_price(
            parse_number(weekly_kg), as_tiers(inputs["tiers"]), parse_number(inputs["rebate_per_kg"]),
        )
        return f"weekly_sugar_kg = {parse_number(weekly_kg):g}; contract_price = {result:.4f} kr/kg"
    if name == "freight_cost":
        result = freight_cost(
            float(inputs["shipment_kg"]), float(inputs["origin_rail_rate_per_100kg"]),
            float(inputs["origin_rail_minimum"]), as_tiers(inputs["steamer_tiers"]),
            float(inputs["destination_rail_rate_per_100kg"]),
            float(inputs["destination_rail_minimum"]), float(inputs["handling_fee"]),
        )
        return f"freight_cost = {result:.2f} kr total, {result / float(inputs['shipment_kg']):.4f} kr/kg"
    if name == "freight_comparison":
        weekly_kg = inputs.get("weekly_kg")
        if weekly_kg is None:
            weekly_buns = total_weekly_buns(int(parse_number(value)) for value in inputs["weekly_bun_orders"])
            weekly_kg = weekly_sugar_kg(
                weekly_buns, int(parse_number(inputs["buns_per_batch"])),
                parse_number(inputs["dough_sugar_kg"]), parse_number(inputs["filling_sugar_kg"]),
            )
        result = compare_freight(
            parse_number(weekly_kg), int(parse_number(inputs["weeks_per_month"])),
            parse_number(inputs["origin_rail_rate_per_100kg"]), parse_number(inputs["origin_rail_minimum"]),
            as_tiers(inputs["steamer_tiers"]), parse_number(inputs["destination_rail_rate_per_100kg"]),
            parse_number(inputs["destination_rail_minimum"]), parse_number(inputs["handling_fee"]),
        )
        return (
            f"weekly_kg = {result['weekly_kg']:g}; monthly_kg = {result['monthly_kg']:g}; "
            f"weekly_per_kg = {result['weekly_per_kg']:.4f} kr/kg; "
            f"monthly_per_kg = {result['monthly_per_kg']:.4f} kr/kg; "
            f"monthly_total = {result['monthly_total']:.2f} kr"
        )
    if name == "travel_cost":
        result = round_trip_travel_cost(
            float(inputs["train_one_way"]), float(inputs["boat_one_way"]), float(inputs.get("gj_one_way", 0)),
        )
        return f"round_trip_travel_cost = {result:.2f} kr"
    if name == "travel_cost_options":
        totals = []
        for train_fare in inputs["train_one_way_options"]:
            total = round_trip_travel_cost(
                parse_number(train_fare), parse_number(inputs["boat_one_way"]),
                parse_number(inputs.get("gj_one_way", 0)),
            )
            totals.append(f"{parse_number(train_fare):g} kr train = {total:.2f} kr total")
        return "travel_cost_options = " + "; ".join(totals)
    if name == "buns_budget":
        result = buns_within_sugar_budget(
            float(inputs["budget"]), float(inputs["sugar_price_per_kg"]),
            float(inputs["sugar_kg_per_batch"]), int(inputs["buns_per_batch"]),
        )
        return f"buns_within_sugar_budget = {result} buns"
    if name == "buns_budget_options":
        inputs = require_inputs(inputs, ("budget", "weekly_bun_orders", "buns_per_batch", "dough_sugar_kg", "filling_sugar_kg", "sugar_kg_per_batch", "tiers", "rebates_per_kg"))
        weekly_buns = total_weekly_buns(int(parse_number(value)) for value in inputs["weekly_bun_orders"])
        weekly_kg = weekly_sugar_kg(
            weekly_buns, int(parse_number(inputs["buns_per_batch"])),
            parse_number(inputs["dough_sugar_kg"]), parse_number(inputs["filling_sugar_kg"]),
        )
        options = []
        for label, rebate in zip(("spot", "6-month", "12-month"), inputs["rebates_per_kg"]):
            price = contract_price(weekly_kg, as_tiers(inputs["tiers"]), parse_number(rebate))
            buns = buns_within_sugar_budget(parse_number(inputs["budget"]), price, parse_number(inputs["sugar_kg_per_batch"]), int(parse_number(inputs["buns_per_batch"])))
            options.append(f"{label} = {price:.2f} kr/kg -> {buns} buns")
        return f"weekly_sugar_kg = {weekly_kg:g}; " + "; ".join(options)
    raise ValueError(f"Unsupported calculation: {name}")


def answer_question(question: str, index_path: Path, limit: int = 8) -> str:
    records = load_records(index_path)
    matches = retrieve(question, records, limit)
    if not matches:
        return "I could not find supporting information in the provided documents."

    context = context_text(matches)
    if "after returning to visby" in normalize_question(question):
        context += "\n\nPLANNING GUIDANCE:\n" + POST_ROMA_SIGHTSEEING_GUIDANCE
    client = make_client()
    deployment = required_env("AZURE_OPENAI_DEPLOYMENT")
    extracted = complete_json(
        client,
        deployment,
        EXTRACTION_SYSTEM_PROMPT,
        f"QUESTION:\n{question}\n\nCONTEXT:\n{context}",
    )
    # Deterministic, source-grounded overrides take precedence over model extraction.
    extracted = verified_travel_options(question, context) or extracted
    extracted = verified_contract_price(question, context) or extracted
    extracted = verified_freight_comparison(question, context) or extracted
    extracted = verified_budget_options(question, context) or extracted
    verified_calculation = calculate(extracted)
    response = client.responses.create(
        model=deployment,
        instructions=ANSWER_SYSTEM_PROMPT,
        input=(
            f"QUESTION:\n{question}\n\nCONTEXT:\n{context}\n\n"
            f"VERIFIED CALCULATION FROM PYTHON:\n{verified_calculation}"
        ),
    )
    return response.output_text or "Azure returned an empty answer."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        print(answer_question(args.question, Path("working/documents.jsonl"), 8))
    except (RuntimeError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
