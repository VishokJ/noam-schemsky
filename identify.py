#!/usr/bin/env python3

import sys
import re
import json
from pathlib import Path
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

REJECT = {"PDF", "HTML", "UTF-8", "UTF8", "ISO-8859-1", "ASCII"}
PROTO_REJECT = {"USB3.0", "USB3", "USB2.0", "LPDDR4", "DDR3", "DDR3L", "DDR4", "H.264", "WMV9", "ETHERNET", "CAN", "I2C", "SPI", "UART", "SD3.0", "MIPI", "PCIE", "SATA", "SD24", "MCLK", "SMCLK", "ACLK", "DVSS", "AVSS", "VREF", "VCORE", "NMI", "JTAG", "TCK", "TMS", "TDI", "TDO"}
SIG_RE = re.compile(r"^(UCA|USART|UART|SPI|I2C|I2S|CAN|TA|TB|TC|TIM|ADC|DAC|GPIO|PORT|P\d|SD|USB|ETH|CLK|MCLK|SMCLK|ACLK|JTAG|NMI)[A-Z0-9/._-]*$", re.I)
TOKEN_RE = re.compile(r"\b[A-Z][A-Z0-9\-\.]{3,}\b")
TI_LIT_RE = re.compile(r"\b(SL[A-Z]{1,2}[A-Z0-9]{3,})\b")
LONG_UPPER_ALNUM = re.compile(r"\b[A-Z0-9]{10,}\b")


def is_part_token(tok: str) -> bool:
    if tok in REJECT or tok.upper() in PROTO_REJECT:
        return False
    if not tok or len(tok) < 4 or len(tok) > 80:
        return False
    if not tok[0].isalpha():
        return False
    if sum(c.isdigit() for c in tok) == 0:
        return False
    if re.search(r"\d+\.\d+", tok):
        return False
    if SIG_RE.match(tok):
        return False
    if re.search(r"[\.+\-_]{4,}", tok):
        return False
    if re.match(r"^[A-Z0-9\-\.]+$", tok) is None:
        return False
    return True


def read_html(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_text_bits_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title else ""
    h_texts = []
    for tag in ["h1", "h2", "h3", "h4"]:
        for h in soup.find_all(tag):
            t = h.get_text(" ", strip=True)
            if t:
                h_texts.append(t)
    meta_names = []
    for m in soup.find_all("meta"):
        v = m.get("content") or m.get("name") or ""
        if v:
            meta_names.append(str(v).strip())
    body_sample = " ".join([p.get_text(" ", strip=True) for p in soup.find_all("p")[:50]])
    return {"title": title, "headings": h_texts, "meta": meta_names, "body": body_sample, "soup": soup}


def extract_text_bits_pdf(path: Path, max_pages: int = 10) -> dict:
    import pdfplumber
    title = ""
    headings: List[str] = []
    meta: List[str] = []
    body_parts: List[str] = []
    with pdfplumber.open(str(path)) as pdf:
        try:
            docinfo = pdf.metadata or {}
        except Exception:
            docinfo = {}
        for k, v in docinfo.items():
            if isinstance(v, str) and v:
                meta.append(v.strip())
        pages = pdf.pages[:max_pages]
        for i, page in enumerate(pages):
            try:
                txt = page.extract_text() or ""
            except Exception:
                txt = ""
            if i == 0 and not title:
                m = re.search(r"^[\s\S]{0,200}" , txt)
                if m:
                    title = m.group(0).strip()
            for line in txt.splitlines()[:10]:
                if 0 < len(line.strip()) < 120:
                    headings.append(line.strip())
            body_parts.append(txt)
    body = " ".join(body_parts)
    return {"title": title, "headings": headings, "meta": meta, "body": body}


def tokenize_candidates(text: str) -> list:
    tokens = TOKEN_RE.findall(text)
    out = []
    for tok in tokens:
        if is_part_token(tok):
            out.append(tok)
    return out


def score_parts(bits: dict) -> list:
    all_text = " \n ".join([bits.get("title", ""), " \n ".join(bits.get("headings", [])), " ".join(bits.get("meta", [])), bits.get("body", "")])
    title = bits.get("title", "")
    headings = " \n ".join(bits.get("headings", []))
    pool = tokenize_candidates(all_text)
    if not pool:
        return []
    freq: Dict[str, int] = {}
    for t in pool:
        freq[t] = freq.get(t, 0) + 1
    scores = []
    for t, f in freq.items():
        s = f
        if t in title:
            s += 5
        if t in headings:
            s += 3
        scores.append((s, t))
    scores.sort(reverse=True)
    return [t for _, t in scores]


def path_candidates(path: Path) -> list:
    parts: List[str] = []
    for comp in [path.parent, path.parent.parent, path.parent.parent.parent]:
        if not comp or not hasattr(comp, "name"):
            continue
        name = comp.name
        if not name or name in REJECT:
            continue
        if re.match(r"^[A-Z][A-Z0-9\-\.]{3,}$", name) and any(ch.isdigit() for ch in name):
            parts.append(name)
    name = path.stem
    if re.match(r"^[A-Z][A-Z0-9\-\.]{3,}$", name) and any(ch.isdigit() for ch in name):
        if name not in parts:
            parts.append(name)
    return parts


def find_packages(bits: dict) -> list:
    text = " \n ".join([bits.get("title", ""), " \n ".join(bits.get("headings", [])), bits.get("body", "")])
    pkgs = set()
    pat_words = ["QFN", "LQFP", "TQFP", "QFP", "BGA", "FBGA", "WLCSP", "SOIC", "SSOP", "DFN", "QFPN", "QPN", "LGA"]
    for w in pat_words:
        for m in re.finditer(rf"\b{w}[0-9]*\b", text):
            pkgs.add(m.group(0))
    for m in re.finditer(r"\b([A-Z]{2,5}[0-9]{2,4})\b", text):
        tok = m.group(1)
        if any(tok.startswith(p) for p in ["QF", "LQ", "TQ", "BG", "DF", "WL", "SO", "SS", "RGZ", "RGE", "ZEJ", "ZCZ", "ZFG", "ALW", "AMC"]):
            pkgs.add(tok)
    return sorted(pkgs)


ORDER_HEADER = re.compile(r"\b(order|ordering|orderable|order\s*code|order\s*number|orderable\s*device|device(\s*name)?|part\s*number|mpn|ordering\s*information|product\s*number)\b", re.I)


def part_candidates_from_html_tables(soup: BeautifulSoup) -> List[str]:
    parts: List[str] = []
    tables = soup.find_all("table")
    for table in tables:
        headers = []
        thead = table.find("thead")
        if thead:
            first = thead.find("tr")
            if first:
                headers = [th.get_text(" ", strip=True) for th in first.find_all(["th", "td"])]
        if not headers:
            first = table.find("tr")
            if first:
                headers = [th.get_text(" ", strip=True) for th in first.find_all(["th", "td"])]
        cap_ok = False
        cap = table.find("caption")
        if cap and ORDER_HEADER.search(cap.get_text(" ", strip=True) or ""):
            cap_ok = True
        prev_heading = table.find_previous(["h1", "h2", "h3", "h4"]) 
        prev_ok = bool(prev_heading and ORDER_HEADER.search(prev_heading.get_text(" ", strip=True) or ""))
        header_flags = [bool(ORDER_HEADER.search(h or "")) for h in headers]
        if not (any(header_flags) or cap_ok or prev_ok):
            pass
        rows = table.find_all("tr")
        for tr in rows[1:] if len(rows) > 1 else []:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            scan_cols = [i for i, f in enumerate(header_flags) if f] if any(header_flags) else list(range(len(cells)))
            for idx in scan_cols:
                if idx >= len(cells):
                    continue
                cell = cells[idx]
                for tok in TOKEN_RE.findall(cell):
                    if is_part_token(tok) and tok not in parts:
                        parts.append(tok)
    return parts


def part_candidates_from_ordering_sections(soup: BeautifulSoup) -> List[str]:
    parts: List[str] = []
    heads = [h for h in soup.find_all(["h1", "h2", "h3", "h4"]) if ORDER_HEADER.search(h.get_text(" ", strip=True) or "")]
    for h in heads:
        cur = h
        steps = 0
        while cur and steps < 50:
            cur = cur.find_next()
            steps += 1
            if not cur or isinstance(cur, str):
                continue
            text = cur.get_text(" ", strip=True)
            for tok in TOKEN_RE.findall(text):
                if is_part_token(tok) and tok not in parts:
                    parts.append(tok)
    return parts


def part_candidates_from_pdf_tables(path: Path, max_pages: int = 10) -> List[str]:
    parts: List[str] = []
    try:
        import camelot
    except Exception:
        return parts
    for flavor in ("lattice", "stream"):
        try:
            tables = camelot.read_pdf(str(path), pages=f"1-{max_pages}", flavor=flavor)
        except Exception:
            tables = []
        for t in tables or []:
            try:
                df = t.df
            except Exception:
                continue
            if df.shape[0] == 0:
                continue
            headers = [str(x) for x in list(df.iloc[0, :])]
            header_flags = [bool(ORDER_HEADER.search(h or "")) for h in headers]
            target_cols = [i for i, f in enumerate(header_flags) if f] if any(header_flags) else list(range(df.shape[1]))
            for _, row in df.iloc[1:, :].iterrows():
                for idx in target_cols:
                    if idx >= len(row):
                        continue
                    val = str(row.iloc[idx])
                    for tok in TOKEN_RE.findall(val):
                        if is_part_token(tok) and tok not in parts:
                            parts.append(tok)
    return parts


def derive_family_prefix(primary_candidates: List[str]) -> Optional[str]:
    if not primary_candidates:
        return None
    base = primary_candidates[0]
    m = re.match(r"^([A-Za-z]+)", base)
    if not m:
        return None
    return m.group(1).upper()


def extract_vendor_codes_text(text: str) -> List[str]:
    out: List[str] = []
    for m in TI_LIT_RE.finditer(text):
        code = m.group(1)
        if code not in out:
            out.append(code)
    # concatenated/vendor keys
    for m in LONG_UPPER_ALNUM.finditer(text):
        tok = m.group(0)
        if any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok):
            if tok not in out:
                out.append(tok)
    return out


def identify_file(path: Path) -> dict:
    if path.suffix.lower() in {".html", ".htm"}:
        bits = extract_text_bits_html(read_html(path))
        table_parts = part_candidates_from_html_tables(bits.get("soup"))
        sec_parts = part_candidates_from_ordering_sections(bits.get("soup"))
        vendor_codes = extract_vendor_codes_text(" \n ".join([bits.get("title","")," \n ".join(bits.get("headings",[])),bits.get("body","")]))
        table_parts = list(dict.fromkeys(table_parts + sec_parts + vendor_codes))
    elif path.suffix.lower() == ".pdf":
        bits = extract_text_bits_pdf(path)
        table_parts = part_candidates_from_pdf_tables(path)
        vendor_codes = extract_vendor_codes_text(" \n ".join([bits.get("title","")," \n ".join(bits.get("headings",[])),bits.get("body","")]))
        table_parts = list(dict.fromkeys(table_parts + vendor_codes))
    else:
        return {"file": str(path), "error": "unsupported"}
    parts_path = path_candidates(path)
    parts_text = score_parts(bits)
    merged: List[str] = []
    for t in parts_path + table_parts + parts_text:
        if t not in merged:
            merged.append(t)
    primary = merged[0] if merged else None
    packages = find_packages(bits)
    return {
        "file": str(path),
        "device_name": primary,
        "part_candidates": merged[:2000],
        "packages": packages[:20],
    }


def main():
    if len(sys.argv) == 2 and sys.argv[1] not in ("--batch",):
        p = Path(sys.argv[1])
        if not p.exists():
            print(json.dumps({"error": "file not found"}))
            sys.exit(2)
        result = identify_file(p)
        print(json.dumps(result, indent=2))
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--batch":
        src = Path(sys.argv[2])
        out = src / "output"
        out.mkdir(parents=True, exist_ok=True)
        files = [*src.glob("*.html"), *src.glob("*.htm"), *src.glob("*.pdf")]
        for f in files:
            res = identify_file(f)
            out_path = out / (f.name + ".json")
            out_path.write_text(json.dumps(res, indent=2), encoding="utf-8")
        print(json.dumps({"processed": len(files), "out": str(out)}))
        return
    print(json.dumps({"error": "usage: identify.py <file> | --batch <folder>"}))
    sys.exit(1)


if __name__ == "__main__":
    main()
