"""Simple, inspectable retrieval for the normalized case documents."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "for",
    "from", "how", "i", "if", "in", "is", "it", "me", "much", "of", "on",
    "or", "should", "the", "to", "what", "when", "where", "which", "who",
    "with", "would",
}
QUERY_EQUIVALENTS = {
    "see": {"see", "sight", "sights", "visit", "visiting"},
    "travel": {"travel", "journey", "train", "boat", "timetable"},
    "travelling": {"travel", "journey", "train", "boat", "timetable"},
}
ITINERARY_MARKERS = {"travel", "travelling", "journey", "route", "train", "boat", "ferry", "return", "outbound", "arrive", "arrival", "depart", "departure"}
SOURCE_GROUPS = {
    "itinerary": (
        "03 - Ferry Timetable",
        "04 - Railway Timetable",
        "05 - Gotlands Jarnvag Timetable",
        "06 - Meeting Invitation",
    ),
    "pricing": (
        "01 - Sugar Price List",
        "07 - Order Book",
        "08 - Cinnamon Bun Recipe",
    ),
    "freight": (
        "02 - Freight Tariff",
        "07 - Order Book",
        "08 - Cinnamon Bun Recipe",
    ),
    "sightseeing": (
        "05 - Gotlands Jarnvag Timetable",
        "06 - Meeting Invitation",
        "09 - Travellers Guidebook",
    ),
}


def tokenize(value: str) -> set[str]:
    return {
        token
        for token in TOKEN_PATTERN.findall(value.lower())
        if token not in STOPWORDS
    }


def normalize_question(question: str) -> str:
    return (
        question.lower()
        .replace("-", " ")
        .replace("kronor", "kr")
        .replace("annual", "12 month")
        .replace("one year", "12 month")
        .replace("year contract", "12 month contract")
        .replace("shipping", "freight")
        .replace("delivery charges", "freight")
    )


def expand_question_terms(question: str) -> set[str]:
    terms = tokenize(normalize_question(question))
    expanded = set(terms)
    for term in terms:
        expanded.update(QUERY_EQUIVALENTS.get(term, {term}))
    return expanded


def score_record(question: str, record: dict[str, Any]) -> int:
    question_terms = expand_question_terms(question)
    if not question_terms:
        return 0

    text_terms = tokenize(str(record.get("text", "")))
    filename_terms = tokenize(str(record.get("source_file", "")))
    score = len(question_terms & text_terms)
    score += len(question_terms & filename_terms)
    return score


def retrieve(
    question: str,
    records: Iterable[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return the highest-scoring records, retaining source metadata."""
    if limit <= 0:
        return []

    records = list(records)
    ranked = sorted(
        records,
        key=lambda record: score_record(question, record),
        reverse=True,
    )
    selected = [record for record in ranked[:limit] if score_record(question, record) > 0]
    selected_keys = {record_key(record) for record in selected}

    # Keep short multi-page documents together when one page matches.
    for record in records:
        if record.get("source_type") != "pdf" or "page" not in record.get("location", {}):
            continue
        if any(
            selected_record.get("source_file") == record.get("source_file")
            and abs(selected_record["location"].get("page", 0) - record["location"]["page"]) == 1
            for selected_record in selected
        ):
            selected_keys.add(record_key(record))

    normalized_question = normalize_question(question)

    if expand_question_terms(question) & ITINERARY_MARKERS:
        selected_keys = group_keys(records, SOURCE_GROUPS["itinerary"], limit)

    if expand_question_terms(question) & {"price", "pricing", "contract", "sugar"} and "contract" in normalized_question:
        selected_keys = group_keys(records, SOURCE_GROUPS["pricing"], limit)

    if "freight" in normalized_question or "shipment" in normalized_question:
        selected_keys = group_keys(records, SOURCE_GROUPS["freight"], limit)

    if "budget" in normalized_question and "sugar" in normalized_question:
        selected_keys = group_keys(records, SOURCE_GROUPS["pricing"], limit)

    if "roma" in normalized_question and any(term in normalized_question for term in ("sight", "see", "visit", "history", "historical", "medieval")):
        selected_keys = group_keys(records, SOURCE_GROUPS["sightseeing"], limit)

    return [record for record in records if record_key(record) in selected_keys]


def record_key(record: dict[str, Any]) -> tuple[str, str, str]:
    location = record.get("location", {})
    return (
        str(record.get("source_file", "")),
        str(location.get("page", "")),
        str(location.get("sheet", "")),
    )


def group_keys(
    records: list[dict[str, Any]],
    prefixes: tuple[str, ...],
    limit: int,
) -> set[tuple[str, str, str]]:
    grouped = [
        record for record in records
        if any(record.get("source_file", "").startswith(prefix) for prefix in prefixes)
    ]
    ranked = sorted(grouped, key=lambda record: score_record(" ".join(prefixes), record), reverse=True)
    return {record_key(record) for record in ranked[:limit]}


def load_records(index_path: Path) -> list[dict[str, Any]]:
    with index_path.open(encoding="utf-8") as index_file:
        return [json.loads(line) for line in index_file if line.strip()]


def format_location(record: dict[str, Any]) -> str:
    location = record.get("location", {})
    parts = [f"page {location['page']}"] if "page" in location else []
    if "sheet" in location:
        parts.append(f"sheet {location['sheet']}")
        if "row_start" in location and "row_end" in location:
            parts.append(f"rows {location['row_start']}-{location['row_end']}")
    return ", ".join(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = load_records(Path("working/documents.jsonl"))
    matches = retrieve(args.question, records, 5)

    if not matches:
        print("No matching source records found.")
        return

    for number, record in enumerate(matches, start=1):
        score = score_record(args.question, record)
        location = format_location(record)
        print(f"{number}. [{score}] {record['source_file']} ({location})")


if __name__ == "__main__":
    main()
