#!/usr/bin/env python3

import os
import json
import argparse
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class PinsResponse(BaseModel):
    pins: List[str]


def normalize_pin_table(pin_table: List[List[str]]) -> Tuple[Set[str], Set[str], Dict[str, str]]:
    """Extract allowed pin names and numbers from the pin table.

    Returns:
    - allowed_pin_names: set of pin names (column 2) lowercased
    - allowed_pin_numbers: set of pin numbers (column 1) lowercased
    - number_to_name: mapping from pin number to pin name (original casing)
    """
    allowed_pin_names: Set[str] = set()
    allowed_pin_numbers: Set[str] = set()
    number_to_name: Dict[str, str] = {}

    if not pin_table or len(pin_table) < 2:
        return allowed_pin_names, allowed_pin_numbers, number_to_name

    # Assume first row is header; data rows start at index 1
    for row in pin_table[1:]:
        if not row:
            continue
        pin_number = str(row[0]).strip() if len(row) > 0 else ""
        pin_name = str(row[1]).strip() if len(row) > 1 else ""
        if pin_number:
            allowed_pin_numbers.add(pin_number.lower())
        if pin_name:
            allowed_pin_names.add(pin_name.lower())
        if pin_number and pin_name:
            number_to_name[pin_number.lower()] = pin_name

    return allowed_pin_names, allowed_pin_numbers, number_to_name


def build_rule_prompt(rule_text: str, pin_table: List[List[str]]) -> str:
    """Build the prompt for selecting associated pins for a given rule."""
    lines: List[str] = []
    header = pin_table[0] if pin_table else []
    header_str = ", ".join([str(h).strip() for h in header]) if header else "Pin, Name, Type, Description"
    lines.append(f"Pin table columns: {header_str}")

    # Include the full pin table with all columns
    for row in pin_table[1:]:
        parts = [str(c).strip() for c in row]
        lines.append(" | ".join(parts))

    table_block = "\n".join(lines)

    prompt = f"""
You are an expert hardware design engineer. Given a design rule and the device pin table, identify which pins from the pin table are directly relevant to implementing or verifying the rule.

Return only the pin names from the pin table's Name column. If the rule refers to a pin by number, map it to the corresponding pin name. If no pins are relevant, return an empty list. Do not invent pins that are not present in the pin table.

RULE:
{rule_text}

PIN TABLE (first rows):
{table_block}

Provide the result as a list of pin names in the exact structured format requested.
"""
    return prompt


def select_pins_for_rule(client: OpenAI, rule_text: str, pin_table: List[List[str]]) -> List[str]:
    """Use LLM to select pins associated with a rule, then validate against the pin table."""
    try:
        prompt = build_rule_prompt(rule_text, pin_table)
        completion = client.beta.chat.completions.parse(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert hardware design engineer mapping rules to valid pins from a given pin table.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format=PinsResponse,
            max_completion_tokens=400,
        )

        parsed = completion.choices[0].message.parsed if completion.choices else None
        model_pins: List[str] = parsed.pins if parsed else []
    except Exception as exc:
        # On any API or parsing error, return empty
        print(f"LLM error while selecting pins: {exc}")
        model_pins = []

    # Validate and normalize pins to exact names from the pin table
    allowed_names, allowed_numbers, number_to_name = normalize_pin_table(pin_table)

    # Build name set (lowercased) for quick membership
    name_set_lower = allowed_names
    number_set_lower = allowed_numbers

    normalized: List[str] = []
    seen: Set[str] = set()

    # Build a mapping from lowercased name to canonical name to preserve original casing
    name_to_canonical: Dict[str, str] = {}
    for row in pin_table[1:]:
        if len(row) > 1 and str(row[1]).strip():
            original = str(row[1]).strip()
            name_to_canonical[original.lower()] = original

    for raw_pin in model_pins:
        candidate = str(raw_pin).strip()
        candidate_lower = candidate.lower()

        canonical_name: str = ""
        if candidate_lower in name_set_lower:
            canonical_name = name_to_canonical.get(candidate_lower, candidate)
        elif candidate_lower in number_set_lower:
            # Map number to its pin name if available
            mapped_name = number_to_name.get(candidate_lower)
            if mapped_name:
                canonical_name = mapped_name

        if canonical_name and canonical_name not in seen:
            seen.add(canonical_name)
            normalized.append(canonical_name)

    return normalized


def process_file(json_path: Path, client: OpenAI) -> Dict[str, Any]:
    """Process a single JSON file, adding a pins list to each rule."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"file": json_path.name, "status": "error", "error": f"read failed: {exc}"}

    if not isinstance(data, dict) or not data:
        return {"file": json_path.name, "status": "error", "error": "unexpected JSON structure"}

    # Expect a single top-level key
    top_key = next(iter(data))
    payload = data.get(top_key, {})
    pin_table: List[List[str]] = payload.get("pin", [])
    rules: List[Dict[str, Any]] = payload.get("checklist", [])

    if not isinstance(pin_table, list) or not isinstance(rules, list):
        return {"file": json_path.name, "status": "error", "error": "missing pin/checklist fields"}

    updated = 0
    for rule in rules:
        rule_text = str(rule.get("rule", "")).strip()
        if not rule_text:
            rule["pins"] = []
            continue
        pins = select_pins_for_rule(client, rule_text, pin_table)
        rule["pins"] = pins
        updated += 1

    # Write back
    try:
        json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        return {"file": json_path.name, "status": "error", "error": f"write failed: {exc}"}

    return {"file": json_path.name, "status": "ok", "updated": updated}


def main():
    parser = argparse.ArgumentParser(
        description="Add pins to each rule in TEST/output JSONs using GPT-5, following rules_generator pattern."
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=str(Path("TEST/output").resolve()),
        help="Directory containing JSON outputs to fix",
    )
    args = parser.parse_args()

    target_dir = Path(args.dir)
    if not target_dir.exists() or not target_dir.is_dir():
        print(json.dumps({"done": False, "error": f"Directory not found: {target_dir}"}))
        return

    client = OpenAI(api_key=OPENAI_API_KEY)

    json_files = sorted(target_dir.glob("*.json"))
    results: List[Dict[str, Any]] = []
    for jf in json_files:
        res = process_file(jf, client)
        results.append(res)

    ok = sum(1 for r in results if r.get("status") == "ok")
    errors = [r for r in results if r.get("status") == "error"]
    updated_rules = sum(int(r.get("updated", 0)) for r in results if r.get("status") == "ok")

    print(
        json.dumps(
            {
                "done": True,
                "dir": str(target_dir),
                "files": len(json_files),
                "ok": ok,
                "errors": len(errors),
                "updated_rules": updated_rules,
                "results": results,
            }
        )
    )


if __name__ == "__main__":
    main()


