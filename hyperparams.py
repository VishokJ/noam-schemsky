#!/usr/bin/env python3

import os


def current_org() -> str:
    return (os.environ.get("ORG") or "generic").strip().lower()


COMMON = {
    "MODEL": os.environ.get("LLM_MODEL", "gpt-5"),
    "PDF_MAX_PAGES": int(os.environ.get("PDF_MAX_PAGES", "0")),
    "RETRIEVAL_K": int(os.environ.get("RETRIEVAL_K", "20")),
    "EVIDENCE_TOP_N": int(os.environ.get("EVIDENCE_TOP_N", "150")),
    "PIN_TABLE_TOPN": int(os.environ.get("PIN_TABLE_TOPN", "25")),
}


ORG = {
    "generic": {
        "PRIORITY_CATS": [
            "Absolute Maximum Ratings",
            "Electrical Characteristics", 
            "Pin Descriptions",
            "Power Supply Requirements",
            "Application Information",
            "Component Requirements",
        ],
        "SECTION_KEYWORDS": {},
        "PROMPT_PREFIX": "",
    },
    "st": {
        "PRIORITY_CATS": [
            "Absolute Maximum Ratings",
            "Electrical Characteristics",
            "Pin Descriptions",
            "Power Supply Requirements", 
            "Application Information",
            "Component Requirements",
        ],
        "SECTION_KEYWORDS": {
            "Pin Descriptions": ["pin description", "pin functions", "terminal"],
            "Electrical Characteristics": ["electrical characteristics", "viL", "viH", "voH", "voL", "current"],
            "Application Information": ["application information", "typical application", "electrical connections"],
            "Power Supply": ["vdd", "vdda", "vdd_io", "decouple", "capacit"],
        },
        "PROMPT_PREFIX": "For STMicroelectronics PDFs, emphasize electrical connections, decoupling caps, and typical application circuits.",
    },
}


def get(name: str, default=None):
    org = current_org()
    if name in COMMON:
        return COMMON[name]
    if org in ORG and name in ORG[org]:
        return ORG[org][name]
    if name in ORG.get("generic", {}):
        return ORG["generic"][name]
    return default


