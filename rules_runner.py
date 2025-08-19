#!/usr/bin/env python3

import sys
import json
import os
import argparse
from pathlib import Path
from typing import Dict, List
from dotenv import load_dotenv
from concurrent.futures import ProcessPoolExecutor

load_dotenv()

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from rules_generator import extract_rules_for_html, extract_rules_for_pdf
    from pin_table import extract_pin_tables
    from identify import identify_file
else:
    from .rules_generator import extract_rules_for_html, extract_rules_for_pdf
    from .pin_table import extract_pin_tables
    from .identify import identify_file

OUT_DIR = Path('POWERBOM-2/output')

def run_one(file_path: Path) -> Dict[str, str]:
    try:
        if file_path.suffix.lower() not in {'.html', '.htm', '.pdf'}:
            return {"file": file_path.name, "status": "skipped", "reason": "unsupported extension"}

        # Check if corresponding JSON output already exists
        out_path = OUT_DIR / f"{file_path.stem}.json"
        if out_path.exists():
            return {"file": file_path.name, "status": "skipped", "reason": "output already exists", "out": str(out_path)}

        pin_tables = extract_pin_tables(file_path)
        pin_table = []
        if pin_tables:
            pkg = next(iter(pin_tables))
            pin_table = pin_tables[pkg]

        if not pin_table:
            return {"file": file_path.name, "status": "skipped", "reason": "no pin table"}

        # Get device name from identify function
        identification = identify_file(file_path)
        device_name = identification.get("device_name") or file_path.stem

        rules = (
            extract_rules_for_html(file_path, pin_table)
            if file_path.suffix.lower() in {'.html', '.htm'}
            else extract_rules_for_pdf(file_path, pin_table)
        )
        out = {
            device_name: {
                "filename": file_path.name,
                "pin": pin_table,
                "checklist": rules,
                "footnote": "",
            }
        }
        out_path = OUT_DIR / f"{file_path.stem}.json"
        out_path.write_text(json.dumps(out, indent=2), encoding='utf-8')
        return {"file": file_path.name, "status": "ok", "out": str(out_path)}
    except Exception as exc:
        return {"file": file_path.name, "status": "error", "error": str(exc)}


def main():
    parser = argparse.ArgumentParser(description="Run rules extraction over files in parallel.")
    parser.add_argument("targets", nargs="*", help="Optional explicit files to process")
    default_workers = max(1, (os.cpu_count() or 2) - 1)
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=default_workers,
        help=f"Number of parallel workers (default: {default_workers})",
    )
    args = parser.parse_args()

    src = Path('POWERBOM-2')
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = [Path(t) for t in args.targets] if args.targets else list(src.glob('*.html')) + list(src.glob('*.htm')) + list(src.glob('*.pdf'))

    results: List[Dict[str, str]] = []
    if not files:
        print(json.dumps({"done": True, "out": str(OUT_DIR), "count": 0, "ok": 0, "skipped": 0, "errors": 0}))
        return

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        for res in executor.map(run_one, files):
            results.append(res)

    ok = sum(1 for r in results if r.get("status") == "ok")
    skipped = sum(1 for r in results if r.get("status") == "skipped")
    errors = [r for r in results if r.get("status") == "error"]

    summary = {
        "done": True,
        "out": str(OUT_DIR),
        "count": len(files),
        "ok": ok,
        "skipped": skipped,
        "errors": len(errors),
        "results": results,
    }
    print(json.dumps(summary))

if __name__ == '__main__':
    main()
