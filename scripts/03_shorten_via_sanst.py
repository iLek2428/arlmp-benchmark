"""
03_shorten_via_sanst.py
-----------------------
For each resolved URL, create a short link via the san.st API and
record the metadata endpoint URL.
Input:  data/resolved_urls.jsonl
Output: data/shortened_urls.jsonl
        Adds fields: short_url, metadata_url, sanst_id

Dry-run mode: set DRY_RUN=1 to skip actual API calls
"""

import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

IN_PATH  = Path("data/resolved_urls.jsonl")
OUT_PATH = Path("data/shortened_urls.jsonl")

SANST_API_URL = "https://api.san.st/api/v1/links"
REQUEST_DELAY = 0.3   # seconds between API calls
DRY_RUN       = os.environ.get("DRY_RUN", "") == "1"


def shorten(destination_url: str) -> dict:
    """
    Call san.st API to create a short link (public endpoint, no auth).
    Returns dict with keys: short_url, metadata_url, sanst_id, error, dry_run
    """
    if DRY_RUN:
        import hashlib
        fake_id = hashlib.md5(destination_url.encode()).hexdigest()[:8]
        return {
            "short_url":    f"https://san.st/{fake_id}",
            "metadata_url": f"https://api.san.st/api/v1/links/{fake_id}/metadata",
            "sanst_id":     fake_id,
            "error":        None,
            "dry_run":      True,
        }

    payload = json.dumps({"destination": destination_url}).encode("utf-8")
    req = urllib.request.Request(
        SANST_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent":   "ARLMP-research/1.0",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        return {
            "short_url":    data.get("short_url", ""),
            "metadata_url": data.get("metadata_url", ""),
            "sanst_id":     data.get("id", ""),
            "error":        None,
            "dry_run":      False,
        }
    except urllib.error.HTTPError as e:
        return {"short_url": "", "metadata_url": "", "sanst_id": "",
                "error": f"HTTPError {e.code}", "dry_run": False}
    except Exception as e:
        return {"short_url": "", "metadata_url": "", "sanst_id": "",
                "error": str(e), "dry_run": False}


def main():
    if DRY_RUN:
        print("[INFO] DRY_RUN=1 — skipping actual API calls, generating placeholder IDs\n")

    items = []
    with open(IN_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))

    print(f"Loaded {len(items)} resolved URLs")

    success = 0
    failed  = 0

    with open(OUT_PATH, "w", encoding="utf-8") as out:
        for idx, item in enumerate(items):
            if idx % 100 == 0:
                print(f"  Shortening {idx}/{len(items)}...")

            time.sleep(REQUEST_DELAY)

            destination = item["http"]["final_url"]
            result      = shorten(destination)

            if result["error"]:
                print(f"  [WARN] {destination[:60]} → {result['error']}")
                failed += 1
            else:
                success += 1

            item["sanst"]            = result
            item["shortened_at_utc"] = datetime.now(timezone.utc).isoformat()

            out.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"\nShortened: {success}")
    print(f"Failed:    {failed}")
    print(f"Saved → {OUT_PATH}")


if __name__ == "__main__":
    main()
