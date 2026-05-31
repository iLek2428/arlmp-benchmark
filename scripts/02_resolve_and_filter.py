"""
02_resolve_and_filter.py
------------------------
Resolve each sampled URL, record HTTP signals, query Google Safe Browsing API,
and assign programmatic ground truth labels per codebook/programmatic_rules.md.

Exclusion criteria (per codebook):
  - Timeout > 10 seconds
  - Final status 4xx or 5xx
  - No Content-Type header and empty body
  - Duplicate (same resolved domain+path after normalization)

Input:  data/sampled_urls.jsonl
Output: data/resolved_urls.jsonl  (≥1,000 non-excluded records)
        data/excluded_urls.jsonl  (excluded records with reason)

Set env var SAFE_BROWSING_API_KEY before running.
"""

import json
import os
import time
import hashlib
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────

IN_PATH       = Path("data/sampled_urls.jsonl")
OUT_RESOLVED  = Path("data/resolved_urls.jsonl")
OUT_EXCLUDED  = Path("data/excluded_urls.jsonl")

TIMEOUT_SEC        = 10
MAX_REDIRECTS      = 5
SAFE_BROWSING_KEY  = os.environ.get("SAFE_BROWSING_API_KEY", "")
SB_API_URL         = "https://safebrowsing.googleapis.com/v4/threatMatches:find"
SB_BATCH_SIZE      = 500   # Safe Browsing allows up to 500 URLs per request
REQUEST_DELAY_SEC  = 0.2   # polite crawl delay

MEDIA_HOSTS = {"youtube.com", "youtu.be", "vimeo.com", "soundcloud.com",
               "spotify.com", "twitch.tv", "dailymotion.com"}
ACADEMIC_TLDS = {".edu", ".ac.th", ".ac.uk", ".ac.jp", ".ac.au"}
ACADEMIC_HOSTS = {"arxiv.org", "doi.org", "pubmed.ncbi.nlm.nih.gov",
                  "researchgate.net", "semanticscholar.org"}
FILE_EXTS = {".pdf", ".zip", ".docx", ".xlsx", ".exe", ".dmg",
             ".pkg", ".csv", ".pptx", ".tar"}
DOWNLOAD_MIME = {"application/pdf", "application/zip", "application/octet-stream",
                 "application/msword", "application/vnd.ms-excel",
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


# ── HTTP resolution ────────────────────────────────────────────────────────────

def resolve_url(url: str) -> dict:
    """
    Follow redirects and record HTTP signals.
    Returns a dict with keys:
      final_url, status, content_type, body_size, redirect_depth,
      redirect_chain, resolved_domain, error
    """
    result = {
        "final_url": url,
        "status": None,
        "content_type": "",
        "body_size": 0,
        "redirect_depth": 0,
        "redirect_chain": [url],
        "resolved_domain": "",
        "error": None,
    }
    try:
        opener = urllib.request.build_opener(
            urllib.request.HTTPRedirectHandler()
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ARLMP-research/1.0 (academic benchmark)"}
        )
        with opener.open(req, timeout=TIMEOUT_SEC) as resp:
            result["status"]        = resp.status
            result["content_type"]  = resp.headers.get("Content-Type", "").split(";")[0].strip()
            body                    = resp.read(8192)   # read up to 8KB for type detection
            result["body_size"]     = int(resp.headers.get("Content-Length", len(body)))
            result["final_url"]     = resp.url
            result["resolved_domain"] = urllib.parse.urlparse(resp.url).netloc
    except urllib.error.HTTPError as e:
        result["status"] = e.code
        result["error"]  = f"HTTPError: {e.code}"
    except urllib.error.URLError as e:
        result["error"] = f"URLError: {e.reason}"
    except TimeoutError:
        result["error"] = "timeout"
    except Exception as e:
        result["error"] = str(e)

    # Count redirects by comparing original and final URL
    if result["final_url"] != url:
        result["redirect_depth"] = 1  # minimum; deep chains need custom handler

    return result


# ── Safe Browsing API ──────────────────────────────────────────────────────────

def query_safe_browsing(urls: list[str]) -> dict[str, str]:
    """
    Batch query Google Safe Browsing API v4.
    Returns {url: threat_type} for unsafe URLs; safe URLs are absent.
    """
    if not SAFE_BROWSING_KEY:
        print("  [WARN] SAFE_BROWSING_API_KEY not set. All URLs labeled 'benign'.")
        return {}

    threats: dict[str, str] = {}
    for i in range(0, len(urls), SB_BATCH_SIZE):
        batch = urls[i:i + SB_BATCH_SIZE]
        payload = {
            "client": {"clientId": "arlmp-benchmark", "clientVersion": "1.0"},
            "threatInfo": {
                "threatTypes": [
                    "MALWARE", "SOCIAL_ENGINEERING",
                    "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"
                ],
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": u} for u in batch],
            }
        }
        api_url = f"{SB_API_URL}?key={SAFE_BROWSING_KEY}"
        data    = json.dumps(payload).encode("utf-8")
        req     = urllib.request.Request(
            api_url, data=data,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
            for match in result.get("matches", []):
                threat_url  = match.get("threat", {}).get("url", "")
                threat_type = match.get("threatType", "UNKNOWN")
                threats[threat_url] = threat_type
        except Exception as e:
            print(f"  [WARN] Safe Browsing batch {i//SB_BATCH_SIZE + 1} failed: {e}")
        time.sleep(0.1)
    return threats


# ── Ground truth labeling (per programmatic_rules.md) ────────────────────────

def assign_labels(item: dict, http: dict, sb_threats: dict) -> dict:
    url          = http["final_url"]
    ct           = http["content_type"].lower()
    status       = http["status"] or 0
    body_size    = http["body_size"]
    redir_depth  = http["redirect_depth"]
    domain       = http["resolved_domain"].lower()

    # Safety state
    if url in sb_threats or item["url"] in sb_threats:
        safety_status = "unsafe"
    elif status >= 400:
        safety_status = "stale_unreachable"
    elif "application/octet-stream" in ct and not any(
            url.lower().endswith(ext) for ext in FILE_EXTS):
        safety_status = "download_risk"
    else:
        safety_status = "benign"

    # Content class (priority order per codebook)
    if safety_status == "unsafe":
        content_class = "unsafe"
    elif status >= 400:
        content_class = "unreachable"
    elif "application/json" in ct or url.lower().endswith(".json"):
        content_class = "api_json"
    elif any(ct.startswith(m) for m in DOWNLOAD_MIME) or \
         any(url.lower().endswith(ext) for ext in FILE_EXTS):
        content_class = "file_download"
    elif "video/" in ct or "audio/" in ct or \
         any(h in domain for h in MEDIA_HOSTS):
        content_class = "media"
    elif any(domain.endswith(tld) for tld in ACADEMIC_TLDS) or \
         any(h in domain for h in ACADEMIC_HOSTS):
        content_class = "academic"
    elif redir_depth > 2:
        content_class = "redirect_chain"
    elif "text/html" in ct and body_size > 0:
        content_class = "webpage"
    else:
        content_class = "unknown"

    # Recommended action
    if safety_status == "unsafe":
        action = "block"
    elif content_class in ("file_download", "unreachable", "unknown"):
        action = "ask_confirmation"
    elif content_class == "redirect_chain" and redir_depth > 3:
        action = "ask_confirmation"
    elif content_class in ("api_json", "academic", "webpage", "media") and \
         safety_status == "benign" and body_size > 5000:
        action = "summarize"
    elif content_class in ("api_json", "academic", "webpage", "media") and \
         safety_status == "benign":
        action = "follow"
    else:
        action = "ask_confirmation"

    # Required structured fields (per codebook table)
    required_fields_map = {
        "webpage":        ["display_domain", "content_class", "safety_status", "last_verified"],
        "file_download":  ["display_domain", "content_class", "mime_type",
                           "safety_status", "requires_user_confirmation"],
        "media":          ["display_domain", "content_class", "safety_status"],
        "academic":       ["display_domain", "content_class", "safety_status", "last_verified"],
        "api_json":       ["display_domain", "content_class", "mime_type"],
        "redirect_chain": ["display_domain", "redirect_depth", "resolved_domain", "safety_status"],
        "unsafe":         ["display_domain", "safety_status", "requires_user_confirmation"],
        "unreachable":    ["display_domain", "safety_status"],
        "unknown":        ["display_domain", "safety_status"],
    }
    required_fields = required_fields_map.get(content_class, ["display_domain", "safety_status"])

    return {
        "content_class":    content_class,
        "action":           action,
        "safety_status":    safety_status,
        "required_fields":  required_fields,
    }


def should_exclude(http: dict) -> tuple[bool, str]:
    if http["error"] == "timeout":
        return True, "timeout"
    status = http["status"] or 0
    if 400 <= status < 600:
        return True, f"http_{status}"
    ct = http["content_type"]
    if not ct and http["body_size"] == 0:
        return True, "no_content_type_empty_body"
    return False, ""


def url_fingerprint(http: dict) -> str:
    """Normalized fingerprint for deduplication."""
    parsed = urllib.parse.urlparse(http["final_url"])
    normalized = parsed.netloc.lower() + parsed.path.rstrip("/").lower()
    return hashlib.md5(normalized.encode()).hexdigest()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not SAFE_BROWSING_KEY:
        print("[WARN] SAFE_BROWSING_API_KEY not set in environment.")
        print("       Safety labels will default to 'benign'.")
        print("       Set it with: export SAFE_BROWSING_API_KEY=your_key\n")

    items = []
    with open(IN_PATH, encoding="utf-8") as f:
        for line in f:
            items.append(json.loads(line.strip()))
    print(f"Loaded {len(items)} URLs from {IN_PATH}")

    # Pre-batch Safe Browsing query for all URLs at once
    all_urls = [item["url"] for item in items]
    print(f"Querying Safe Browsing API for {len(all_urls)} URLs...")
    sb_threats = query_safe_browsing(all_urls)
    print(f"  → {len(sb_threats)} URLs flagged as unsafe")

    resolved:  list[dict] = []
    excluded:  list[dict] = []
    seen_fingerprints: set[str] = set()

    for idx, item in enumerate(items):
        if idx % 100 == 0:
            print(f"  Resolving {idx}/{len(items)}...")
        time.sleep(REQUEST_DELAY_SEC)

        http = resolve_url(item["url"])

        # Exclusion checks
        exclude, reason = should_exclude(http)
        if exclude:
            item["exclude_reason"] = reason
            item["http"] = http
            excluded.append(item)
            continue

        # Deduplication
        fp = url_fingerprint(http)
        if fp in seen_fingerprints:
            item["exclude_reason"] = "duplicate"
            item["http"] = http
            excluded.append(item)
            continue
        seen_fingerprints.add(fp)

        # Ground truth labeling
        labels = assign_labels(item, http, sb_threats)

        resolved.append({
            **item,
            "http":             http,
            "ground_truth":     labels,
            "resolved_at_utc":  datetime.now(timezone.utc).isoformat(),
        })

        if len(resolved) >= 1000:
            print("  Reached 1,000 resolved URLs. Stopping.")
            break

    print(f"\nResolved: {len(resolved)}")
    print(f"Excluded: {len(excluded)}")

    # Stratum distribution
    strata = {}
    for r in resolved:
        s = r["ground_truth"]["content_class"]
        strata[s] = strata.get(s, 0) + 1
    print("\nContent class distribution:")
    for s, n in sorted(strata.items(), key=lambda x: -x[1]):
        print(f"  {s:20s}: {n}")

    with open(OUT_RESOLVED, "w", encoding="utf-8") as f:
        for r in resolved:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(OUT_EXCLUDED, "w", encoding="utf-8") as f:
        for e in excluded:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"\nSaved → {OUT_RESOLVED}")
    print(f"Saved → {OUT_EXCLUDED}")


if __name__ == "__main__":
    main()
