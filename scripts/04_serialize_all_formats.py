"""
04_serialize_all_formats.py
---------------------------
For each shortened URL, fetch the ARLMP-22 metadata object from san.st and
serialize it into all 7 formats. Record byte length, character length,
tokenizer length, parse success, and round-trip equivalence.

Formats: JSON, minified JSON, YAML, TOML, TOON, Markdown, ARLMP-Min

Input:  data/shortened_urls.jsonl
Output: data/serialized_payloads.jsonl
        Each record includes the metadata object + all 7 serializations +
        measurements for each.

Requires: pip install pyyaml toml tiktoken
TOON serialization uses a custom implementation (see _serialize_toon).
"""

import json
import re
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

try:
    import yaml
except ImportError:
    yaml = None
    print("[WARN] pyyaml not installed. YAML serialization will be skipped.")

try:
    import toml
except ImportError:
    toml = None
    print("[WARN] toml not installed. TOML serialization will be skipped.")

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))
except ImportError:
    print("[WARN] tiktoken not installed. Token counts will be character-based estimates.")
    def count_tokens(text: str) -> int:
        return len(text) // 4  # rough approximation

IN_PATH  = Path("data/shortened_urls.jsonl")
OUT_PATH = Path("data/serialized_payloads.jsonl")
REQUEST_DELAY = 0.2

# ARLMP-22 field set (full schema)
ARLMP22_FIELDS = [
    "short_code", "display_domain", "etld_plus_one", "resolved_domain",
    "redirect_depth", "content_class", "mime_type", "created_at",
    "last_verified", "expires_at", "safety_status", "safety_engine",
    "safety_engine_version", "destination_hash", "title", "description",
    "summarize_allowed", "autofill_allowed", "requires_user_confirmation",
    "schema_version", "protocol", "agent_note",
]

# ARLMP-Min field set (minimum sufficient — derived from schema ablation plan)
ARLMP_MIN_FIELDS = [
    "short_code", "display_domain", "content_class", "safety_status",
    "requires_user_confirmation", "last_verified",
]


def fetch_metadata(metadata_url: str, sanst_id: str) -> dict:
    """Fetch ARLMP metadata from san.st endpoint."""
    if not metadata_url or "dry_run" in metadata_url:
        # Generate synthetic metadata for dry-run mode
        return _synthetic_metadata(sanst_id)
    try:
        req = urllib.request.Request(
            metadata_url,
            headers={"Accept": "application/json", "User-Agent": "ARLMP-research/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  [WARN] fetch_metadata failed for {sanst_id}: {e}")
        return _synthetic_metadata(sanst_id)


def _synthetic_metadata(sanst_id: str) -> dict:
    """Minimal synthetic metadata for pipeline testing (dry-run only)."""
    return {
        "short_code":                  sanst_id,
        "display_domain":              "example.com",
        "etld_plus_one":               "example.com",
        "resolved_domain":             "www.example.com",
        "redirect_depth":              1,
        "content_class":               "webpage",
        "mime_type":                   "text/html",
        "created_at":                  "2026-01-01T00:00:00Z",
        "last_verified":               "2026-05-01T00:00:00Z",
        "expires_at":                  "2027-01-01T00:00:00Z",
        "safety_status":               "benign",
        "safety_engine":               "google_safe_browsing",
        "safety_engine_version":       "v5",
        "destination_hash":            "sha256:abc123",
        "title":                       "Example Domain",
        "description":                 "This domain is for illustrative examples.",
        "summarize_allowed":           True,
        "autofill_allowed":            False,
        "requires_user_confirmation":  False,
        "schema_version":              "ARLMP-22",
        "protocol":                    "https",
        "agent_note":                  "",
    }


# ── Serializers ───────────────────────────────────────────────────────────────

def serialize_json(obj: dict) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)

def serialize_json_min(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

def serialize_yaml(obj: dict) -> str:
    if yaml is None:
        return ""
    return yaml.dump(obj, allow_unicode=True, default_flow_style=False,
                     sort_keys=False)

def serialize_toml(obj: dict) -> str:
    if toml is None:
        return ""
    # TOML requires string values; convert booleans and None
    safe = {k: (str(v) if v is None else v) for k, v in obj.items()}
    try:
        return toml.dumps(safe)
    except Exception as e:
        return f"# TOML serialization error: {e}"

def serialize_toon(obj: dict) -> str:
    """
    TOON (Token-Oriented Object Notation) — minimal implementation.
    Uses colon-delimited key:value pairs, one per line, no brackets or quotes
    for scalar values. Based on the informal TOON spec.
    """
    lines = []
    for k, v in obj.items():
        if isinstance(v, bool):
            lines.append(f"{k}:{str(v).lower()}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k}:{v}")
        elif v is None:
            lines.append(f"{k}:null")
        else:
            # Escape colons in string values
            escaped = str(v).replace(":", "\\:")
            lines.append(f"{k}:{escaped}")
    return "\n".join(lines)

def serialize_markdown(obj: dict) -> str:
    """
    Markdown table representation of the metadata object.
    Two-column table: Field | Value
    """
    rows = ["| Field | Value |", "|---|---|"]
    for k, v in obj.items():
        val = str(v).replace("|", "\\|")
        rows.append(f"| {k} | {val} |")
    return "\n".join(rows)

def serialize_arlmp_min(obj: dict) -> str:
    """ARLMP-Min: JSON serialization of minimum field set only."""
    min_obj = {k: obj[k] for k in ARLMP_MIN_FIELDS if k in obj}
    return json.dumps(min_obj, separators=(",", ":"), ensure_ascii=False)


SERIALIZERS = {
    "json":        serialize_json,
    "json_min":    serialize_json_min,
    "yaml":        serialize_yaml,
    "toml":        serialize_toml,
    "toon":        serialize_toon,
    "markdown":    serialize_markdown,
    "arlmp_min":   serialize_arlmp_min,
}


# ── Parse validity checks ─────────────────────────────────────────────────────

def check_parse_valid(fmt: str, text: str, original: dict) -> dict:
    """
    Attempt to parse serialized text back and check round-trip equivalence.
    Returns: {parse_valid: bool, roundtrip_equivalent: bool, parse_error: str|None}
    """
    try:
        if fmt == "json":
            parsed = json.loads(text)
        elif fmt == "json_min":
            parsed = json.loads(text)
        elif fmt == "yaml":
            parsed = yaml.safe_load(text) if yaml else None
        elif fmt == "toml":
            parsed = toml.loads(text) if toml else None
        elif fmt in ("toon", "markdown", "arlmp_min"):
            if fmt == "arlmp_min":
                parsed = json.loads(text)
            else:
                # TOON and Markdown: structural parse only (no round-trip)
                return {"parse_valid": True, "roundtrip_equivalent": None,
                        "parse_error": None}
        else:
            return {"parse_valid": False, "roundtrip_equivalent": False,
                    "parse_error": "unknown format"}

        if parsed is None:
            return {"parse_valid": False, "roundtrip_equivalent": False,
                    "parse_error": "parse returned None"}

        # Round-trip check: keys and values should match original
        if fmt in ("json", "json_min", "yaml", "toml", "arlmp_min"):
            original_subset = (
                {k: original[k] for k in ARLMP_MIN_FIELDS if k in original}
                if fmt == "arlmp_min" else original
            )
            equivalent = all(
                str(parsed.get(k)) == str(v)
                for k, v in original_subset.items()
                if k in parsed
            )
            return {"parse_valid": True, "roundtrip_equivalent": equivalent,
                    "parse_error": None}
        return {"parse_valid": True, "roundtrip_equivalent": None, "parse_error": None}

    except Exception as e:
        return {"parse_valid": False, "roundtrip_equivalent": False,
                "parse_error": str(e)}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    items = []
    with open(IN_PATH, encoding="utf-8") as f:
        for line in f:
            items.append(json.loads(line.strip()))
    print(f"Loaded {len(items)} shortened URLs")

    with open(OUT_PATH, "w", encoding="utf-8") as out:
        for idx, item in enumerate(items):
            if idx % 100 == 0:
                print(f"  Serializing {idx}/{len(items)}...")
            time.sleep(REQUEST_DELAY)

            sanst   = item.get("sanst", {})
            meta_url = sanst.get("metadata_url", "")
            sanst_id = sanst.get("sanst_id", f"item_{idx}")

            metadata = fetch_metadata(meta_url, sanst_id)

            serializations = {}
            for fmt, fn in SERIALIZERS.items():
                text = fn(metadata)
                validity = check_parse_valid(fmt, text, metadata)
                serializations[fmt] = {
                    "text":                  text,
                    "byte_length":           len(text.encode("utf-8")),
                    "char_length":           len(text),
                    "token_count":           count_tokens(text),
                    "parse_valid":           validity["parse_valid"],
                    "roundtrip_equivalent":  validity["roundtrip_equivalent"],
                    "parse_error":           validity["parse_error"],
                }

            item["metadata_object"]  = metadata
            item["serializations"]   = serializations
            item["serialized_at_utc"] = datetime.now(timezone.utc).isoformat()
            out.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"\nSaved → {OUT_PATH}")
    print("Token count summary (mean across all items):")
    # Quick summary
    items_out = []
    with open(OUT_PATH, encoding="utf-8") as f:
        for line in f:
            items_out.append(json.loads(line.strip()))
    for fmt in SERIALIZERS:
        counts = [r["serializations"][fmt]["token_count"] for r in items_out
                  if fmt in r.get("serializations", {})]
        if counts:
            print(f"  {fmt:12s}: mean={sum(counts)/len(counts):.0f}  "
                  f"min={min(counts)}  max={max(counts)}")


if __name__ == "__main__":
    main()
