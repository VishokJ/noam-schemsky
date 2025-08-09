import warnings
warnings.filterwarnings("ignore")

import sys
import re
import json
from pathlib import Path
from typing import List, Dict

from bs4 import BeautifulSoup
import pdfplumber

CANONICAL_HEADERS = [
    "Pin Number", "Pin Name", "Signal Name", "Direction", "Type", "Description"
]

def extract_html_tables(html: str) -> List[List[List[str]]]:
    soup = BeautifulSoup(html, "html.parser")
    tables = []
    
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if cells and any(cell.strip() for cell in cells):
                rows.append(cells)
        
        if len(rows) >= 2:
            max_cols = max(len(row) for row in rows)
            normalized_rows = []
            for row in rows:
                while len(row) < max_cols:
                    row.append("")
                normalized_rows.append(row[:max_cols])
            tables.append(normalized_rows)
    
    return tables

def extract_pdf_tables(pdf_path: Path) -> List[List[List[str]]]:
    tables = []
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                try:
                    page_tables = page.extract_tables()
                    if page_tables:
                        for table in page_tables:
                            if table and len(table) >= 3:
                                clean_table = []
                                for row in table:
                                    if row:
                                        clean_row = []
                                        for cell in row:
                                            if cell is None:
                                                clean_row.append("")
                                            else:
                                                cell_text = str(cell).strip()
                                                cell_text = ' '.join(cell_text.split())
                                                clean_row.append(cell_text)
                                        
                                        if sum(1 for c in clean_row if c.strip()) >= 2:
                                            clean_table.append(clean_row)
                                
                                if len(clean_table) >= 3:
                                    max_cols = max(len(row) for row in clean_table)
                                    if max_cols >= 3:
                                        normalized_table = []
                                        for row in clean_table:
                                            while len(row) < max_cols:
                                                row.append("")
                                            normalized_table.append(row[:max_cols])
                                        tables.append(normalized_table)
                except Exception:
                    continue
    except Exception:
        pass
    
    return tables

def score_table_for_pins(table: List[List[str]]) -> int:
    if not table or len(table) < 3:
        return 0
    
    headers = [h.lower() for h in table[0]]
    score = 0
    
    strong_keywords = ["pin", "ball", "terminal"]
    moderate_keywords = ["signal", "function", "description", "type", "direction", "name"]
    
    for header in headers:
        for keyword in strong_keywords:
            if keyword in header:
                score += 20
        for keyword in moderate_keywords:
            if keyword in header:
                score += 10
    
    first_col_data = [row[0].strip() for row in table[1:] if row and row[0].strip()]
    pin_like_count = 0
    
    for cell in first_col_data[:10]:
        if cell.isdigit():
            pin_like_count += 1
        elif re.match(r'^[A-Z]\d+$', cell):
            pin_like_count += 1
        elif cell.upper() in ['VDD', 'VSS', 'GND', 'VCC', 'NC', 'AVDD', 'DVDD']:
            pin_like_count += 1
    
    score += pin_like_count * 8
    
    electrical_keywords = ["min", "max", "typical", "units", "conditions", "parameter"]
    electrical_count = sum(1 for h in headers for kw in electrical_keywords if kw in h)
    if electrical_count >= 2:
        score -= 30
    
    data_rows = len(table) - 1
    score += min(data_rows * 2, 40)
    
    if len(headers) >= 4:
        score += 15
    elif len(headers) >= 6:
        score += 25
    
    return score

def select_best_table(tables: List[List[List[str]]]) -> List[List[str]]:
    if not tables:
        return [CANONICAL_HEADERS]
    
    scored = [(score_table_for_pins(table), table) for table in tables]
    scored.sort(key=lambda x: x[0], reverse=True)
    
    if scored and scored[0][0] > 0:
        return scored[0][1]
    
    return [CANONICAL_HEADERS]

def normalize_table_headers(table: List[List[str]]) -> List[List[str]]:
    if not table:
        return [CANONICAL_HEADERS]
    
    headers = table[0]
    normalized_headers = []
    
    for header in headers:
        h_lower = header.lower().strip()
        
        if any(word in h_lower for word in ["pin", "number", "#"]) and "name" not in h_lower:
            normalized_headers.append("Pin Number")
        elif "name" in h_lower and any(word in h_lower for word in ["pin", "ball"]):
            normalized_headers.append("Pin Name")
        elif any(word in h_lower for word in ["signal", "function"]) and "description" not in h_lower:
            normalized_headers.append("Signal Name")
        elif any(word in h_lower for word in ["direction", "i/o", "io"]):
            normalized_headers.append("Direction")
        elif "type" in h_lower:
            normalized_headers.append("Type")
        elif any(word in h_lower for word in ["description", "function"]):
            normalized_headers.append("Description")
        else:
            normalized_headers.append(header)
    
    return [normalized_headers] + table[1:]

def extract_pin_tables(path: Path) -> Dict[str, List[List[str]]]:
    if path.suffix.lower() in {".html", ".htm"}:
        html = path.read_text(encoding="utf-8", errors="ignore")
        tables = extract_html_tables(html)
    elif path.suffix.lower() == ".pdf":
        tables = extract_pdf_tables(path)
    else:
        return {"DEFAULT_PACKAGE": [CANONICAL_HEADERS]}
    
    best_table = select_best_table(tables)
    
    normalized_table = normalize_table_headers(best_table)
    
    return {"DEFAULT_PACKAGE": normalized_table}

def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: pin_table.py <file.html|file.pdf>"}))
        sys.exit(1)
    
    p = Path(sys.argv[1])
    if not p.exists():
        print(json.dumps({"error": "file not found"}))
        sys.exit(2)
    
    result = extract_pin_tables(p)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()