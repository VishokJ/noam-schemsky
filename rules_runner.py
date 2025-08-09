#!/usr/bin/env python3

import sys
import json
from pathlib import Path
from typing import Dict, List

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from NEW.rules_generator import extract_rules_for_html, extract_rules_for_pdf
    from NEW.pin_table import extract_pin_tables
else:
    from .rules_generator import extract_rules_for_html, extract_rules_for_pdf
    from .pin_table import extract_pin_tables

OUT_DIR = Path('TEST/output')

def run_one(file_path: Path):
    if file_path.suffix.lower() in {'.html', '.htm', '.pdf'}:
        pin_tables = extract_pin_tables(file_path)
        pin_table = []
        if pin_tables:
            pkg = next(iter(pin_tables))
            pin_table = pin_tables[pkg]
        rules = extract_rules_for_html(file_path, pin_table) if file_path.suffix.lower() in {'.html','.htm'} else extract_rules_for_pdf(file_path, pin_table)
        out = {
            file_path.stem: {
                "filename": file_path.name,
                "pin": pin_table if pin_table else [["Pin Number","Pin Name","Signal Name","Direction","Type","Description"]],
                "checklist": rules,
                "footnote": ""
            }
        }
        out_path = OUT_DIR / f"{file_path.stem}.json"
        out_path.write_text(json.dumps(out, indent=2), encoding='utf-8')

if __name__ == '__main__':
    src = Path('TEST')
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = sys.argv[1:] if len(sys.argv) > 1 else []
    files = [Path(t) for t in targets] if targets else list(src.glob('*.html')) + list(src.glob('*.htm')) + list(src.glob('*.pdf'))
    for p in files:
        run_one(p)
    print(json.dumps({"done": True, "out": str(OUT_DIR), "count": len(files)}))
