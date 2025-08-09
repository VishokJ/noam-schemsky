from typing import List, Dict, Any

REQUIRED_KEYS = ["group", "rule", "pins", "essential"]

def is_rule_dict(d: Dict[str, Any]) -> bool:
    if not isinstance(d, dict):
        return False
    for k in REQUIRED_KEYS:
        if k not in d:
            return False
    if not isinstance(d["group"], str) or not d["group"].strip():
        return False
    if not isinstance(d["rule"], str) or len(d["rule"].strip()) < 8:
        return False
    if not isinstance(d["pins"], list):
        return False
    if not isinstance(d["essential"], bool):
        return False
    return True

def normalize_rule(d: Dict[str, Any]) -> Dict[str, Any]:
    d2 = {
        "group": str(d.get("group", "")).strip(),
        "rule": " ".join(str(d.get("rule", "")).split()).strip(),
        "pins": [str(p).strip() for p in (d.get("pins") or []) if str(p).strip()],
        "essential": bool(d.get("essential", False)),
    }
    return d2

def dedup_rules(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for r in rules:
        key = (r["group"].lower(), r["rule"].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out
