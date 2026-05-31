"""
01_sample_urls.py
-----------------
Sample 1,200 destination URLs from Tranco top-10k and Common Crawl,
stratified by target content class distribution.

Output: data/sampled_urls.jsonl
Each line: {"url": "...", "source": "tranco|commoncrawl|manual", "stratum": "..."}

Usage:
  pip install tranco
  python 01_sample_urls.py
"""

import json, random, csv, io, urllib.request, urllib.error, os
from pathlib import Path

random.seed(42)

OUT_PATH = Path("data/sampled_urls.jsonl")
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

STRATA_TARGETS = {
    "webpage":         0.40,
    "file_download":   0.15,
    "media":           0.10,
    "academic":        0.10,
    "api_json":        0.10,
    "safety_unknown":  0.10,
    "redirect_chain":  0.05,
}
TOTAL_SAMPLE = 1200

# ── Tranco ────────────────────────────────────────────────────────────────────

# Permanent latest-list URL (no list ID needed)
TRANCO_LATEST_URL = "https://tranco-list.eu/download/recent/10000"
# Fallback: pinned list from Jan 2026 (stable, citable for paper)
TRANCO_PINNED_URL = "https://tranco-list.eu/download/X4NZN/10000"

def fetch_tranco(url: str) -> list[str]:
    req = urllib.request.Request(url, headers={"User-Agent": "ARLMP-research/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        content = resp.read().decode("utf-8")
    # Format: "rank,domain" one per line
    domains = []
    for line in content.strip().split("\n"):
        parts = line.strip().split(",")
        if len(parts) >= 2:
            domains.append(parts[1].strip())
        elif len(parts) == 1 and parts[0]:
            domains.append(parts[0].strip())
    return domains

def fetch_tranco_top10k() -> list[str]:
    """Try latest URL first, fall back to pinned list."""
    for label, url in [("latest", TRANCO_LATEST_URL),
                        ("pinned X4NZN", TRANCO_PINNED_URL)]:
        try:
            print(f"  Trying Tranco {label}...")
            domains = fetch_tranco(url)
            if domains:
                print(f"  → {len(domains)} domains loaded (Tranco {label})")
                return domains
        except Exception as e:
            print(f"  [WARN] Tranco {label} failed: {e}")

    # Last resort: try tranco PyPI package
    try:
        from tranco import Tranco
        print("  Trying tranco Python package...")
        t = Tranco(cache=True, cache_dir=".tranco")
        lst = t.list()
        domains = lst.top(10000)
        print(f"  → {len(domains)} domains via tranco package")
        return domains
    except Exception as e:
        print(f"  [WARN] tranco package failed: {e}")
        print("  [WARN] Using fallback domain list. "
              "Download manually from https://tranco-list.eu and place as data/tranco_10k.csv")
        return _load_manual_or_stub()

def _load_manual_or_stub() -> list[str]:
    """Load manually downloaded Tranco CSV, or use minimal stub."""
    manual = Path("data/tranco_10k.csv")
    if manual.exists():
        domains = []
        with open(manual, encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    domains.append(parts[1].strip())
        print(f"  → {len(domains)} domains from manual file")
        return domains
    # Minimal stub for pipeline testing only
    print("  [WARN] No Tranco data available. Using stub domains for testing.")
    return [f"example{i}.com" for i in range(10000)]

# ── Stratum heuristics ────────────────────────────────────────────────────────

MEDIA_HOSTS  = {"youtube.com","youtu.be","vimeo.com","soundcloud.com",
                "spotify.com","twitch.tv","dailymotion.com","tiktok.com"}
ACADEMIC_TLD = {".edu",".ac.th",".ac.uk",".ac.jp",".ac.au"}
ACADEMIC_HOST= {"arxiv.org","doi.org","pubmed.ncbi.nlm.nih.gov",
                "scholar.google.com","researchgate.net","semanticscholar.org",
                "ssrn.com","jstor.org"}
FILE_EXTS    = {".pdf",".zip",".docx",".xlsx",".exe",".dmg",
                ".pkg",".tar.gz",".csv",".pptx",".apk"}
API_SIGNALS  = {"api.","data.","opendata","feeds.","rest."}

def guess_stratum(domain: str) -> str:
    d = domain.lower()
    if any(h in d for h in MEDIA_HOSTS):
        return "media"
    if any(d.endswith(t) for t in ACADEMIC_TLD) or any(h in d for h in ACADEMIC_HOST):
        return "academic"
    if any(s in d for s in API_SIGNALS):
        return "api_json"
    return "webpage"

# ── Common Crawl (optional) ───────────────────────────────────────────────────

def fetch_commoncrawl_sample(n: int = 300) -> list[str]:
    """Try several CC index endpoints; skip silently if all fail."""
    endpoints = [
        ("https://index.commoncrawl.org/CC-MAIN-2024-10-index"
         "?url=*.com&output=json&limit=2000"),
        ("https://index.commoncrawl.org/CC-MAIN-2023-50-index"
         "?url=*.com&output=json&limit=2000"),
    ]
    for url in endpoints:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "ARLMP-research/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                lines = resp.read().decode("utf-8").strip().split("\n")
            urls = []
            for line in lines:
                try:
                    obj = json.loads(line)
                    if "url" in obj:
                        urls.append(obj["url"])
                except Exception:
                    continue
            if urls:
                sampled = random.sample(urls, min(n, len(urls)))
                print(f"  → {len(sampled)} URLs from Common Crawl")
                return sampled
        except Exception as e:
            print(f"  [WARN] CC endpoint failed: {e}")
    print("  [INFO] Common Crawl unavailable — using Tranco-only dataset.")
    print("         Redirect-chain and file_download strata will be"
          " supplemented from Tranco heuristics.")
    return []

# ── Manual supplement lists ───────────────────────────────────────────────────
# These cover strata that Tranco popular domains miss.
# Extend these lists as needed before running.

KNOWN_FILE_DOWNLOAD = [
    # Executables (Windows)
    "https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe",
    "https://download.mozilla.org/?product=firefox-latest&os=win64&lang=en-US",
    "https://dl.google.com/chrome/install/latest/chrome_installer.exe",
    "https://code.visualstudio.com/sha/download?build=stable&os=win32-x64-user",
    "https://github.com/git-for-windows/git/releases/download/v2.43.0.windows.1/Git-2.43.0-64-bit.exe",
    "https://www.7-zip.org/a/7z2301-x64.exe",
    "https://releases.libreoffice.org/7.6.4/LibreOffice_7.6.4_Win_x86-64.msi",
    "https://nodejs.org/dist/v20.11.0/node-v20.11.0-x64.msi",
    "https://zoom.us/client/latest/ZoomInstaller.exe",
    "https://download.teamviewer.com/download/TeamViewer_Setup.exe",
    "https://aka.ms/vs/17/release/vc_redist.x64.exe",
    "https://download.java.net/java/GA/jdk21/fd2272bbf8e04c3dbaee13770090416c/35/GPL/openjdk-21_windows-x64_bin.zip",
    "https://github.com/PowerShell/PowerShell/releases/download/v7.4.0/PowerShell-7.4.0-win-x64.msi",
    "https://github.com/neovim/neovim/releases/download/v0.9.4/nvim-win64.msi",
    "https://github.com/BurntSushi/ripgrep/releases/download/14.0.3/ripgrep-14.0.3-x86_64-pc-windows-msvc.zip",
    "https://github.com/cli/cli/releases/download/v2.40.0/gh_2.40.0_windows_amd64.msi",
    "https://github.com/JanDeDobbeleer/oh-my-posh/releases/download/v19.5.2/install-amd64.exe",
    "https://github.com/containers/podman/releases/download/v4.8.0/podman-4.8.0-setup.exe",
    "https://github.com/rustup-rs/rustup/releases/download/1.26.0/rustup-init.exe",
    "https://www.wireshark.org/download/win64/Wireshark-win64-4.2.0.exe",
    # PDFs — academic
    "https://arxiv.org/pdf/2310.06825.pdf",
    "https://arxiv.org/pdf/2307.09288.pdf",
    "https://arxiv.org/pdf/1706.03762.pdf",
    "https://arxiv.org/pdf/2303.08774.pdf",
    "https://arxiv.org/pdf/2005.14165.pdf",
    "https://arxiv.org/pdf/1810.04805.pdf",
    "https://arxiv.org/pdf/2204.05149.pdf",
    "https://arxiv.org/pdf/2302.07842.pdf",
    "https://arxiv.org/pdf/2108.07258.pdf",
    "https://arxiv.org/pdf/2009.03300.pdf",
    # PDFs — government / standards
    "https://www.irs.gov/pub/irs-pdf/f1040.pdf",
    "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf",
    "https://www.rfc-editor.org/rfc/rfc9110.pdf",
    "https://www.rfc-editor.org/rfc/rfc8446.pdf",
    "https://www.rfc-editor.org/rfc/rfc7519.pdf",
    "https://www.w3.org/TR/2024/REC-WCAG22-20231005/WCAG22.pdf",
    "https://www.ecma-international.org/wp-content/uploads/ECMA-262_14th_edition_june_2023.pdf",
    "https://www.unicode.org/versions/Unicode15.0.0/UnicodeStandard-15.0.pdf",
    "https://www.iso.org/files/live/sites/isoorg/files/archive/pdf/en/annual_report_2022.pdf",
    "https://commission.europa.eu/system/files/2021-04/proposal-2021-188-artificial-intelligence-act_en.pdf",
    "https://www.whitehouse.gov/wp-content/uploads/2023/10/Biden-Harris-Administration-Artificial-Intelligence-EO.pdf",
    "https://assets.publishing.service.gov.uk/government/uploads/system/uploads/attachment_data/file/1141462/a-pro-innovation-approach-to-ai-regulation.pdf",
    # ZIPs and tarballs
    "https://github.com/python/cpython/archive/refs/tags/v3.12.0.zip",
    "https://wordpress.org/latest.zip",
    "https://ftp.gnu.org/gnu/gcc/gcc-13.2.0/gcc-13.2.0.tar.gz",
    "https://download.gimp.org/pub/gimp/v2.10/gimp-2.10.36.tar.bz2",
    "https://github.com/torvalds/linux/archive/refs/tags/v6.6.zip",
    "https://github.com/django/django/archive/refs/tags/4.2.7.zip",
    "https://github.com/pallets/flask/archive/refs/tags/3.0.0.zip",
    "https://github.com/expressjs/express/archive/refs/tags/4.18.2.zip",
    "https://github.com/vuejs/vue/archive/refs/tags/v3.3.8.zip",
    "https://github.com/facebook/react/archive/refs/tags/v18.2.0.zip",
    # CSVs
    "https://raw.githubusercontent.com/datasets/population/main/data/population.csv",
    "https://raw.githubusercontent.com/owid/covid-19-data/master/public/data/owid-covid-data.csv",
    "https://raw.githubusercontent.com/fivethirtyeight/data/master/airline-safety/airline-safety.csv",
    "https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/csse_covid_19_daily_reports/01-01-2023.csv",
    "https://raw.githubusercontent.com/nytimes/covid-19-data/master/us-states.csv",
    "https://raw.githubusercontent.com/datasets/gdp/main/data/gdp.csv",
    "https://raw.githubusercontent.com/plotly/datasets/master/gapminder_with_codes.csv",
    "https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv",
    "https://raw.githubusercontent.com/mwaskom/seaborn-data/master/iris.csv",
    "https://raw.githubusercontent.com/plotly/datasets/master/tips.csv",
    # Excel / Office
    "https://go.microsoft.com/fwlink/?LinkID=521962",
    "https://file-examples.com/storage/fe3b9f3b5b6462e2c1c3d63/2017/02/file_example_XLS_10.xls",
    # Images
    "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/280px-PNG_transparency_demonstration_1.png",
    "https://www.gstatic.com/webp/gallery/1.webp",
    "https://raw.githubusercontent.com/mathiasbynens/small/master/pdf.pdf",
    # Fonts
    "https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans-Regular.ttf",
    "https://github.com/JetBrains/JetBrainsMono/releases/download/v2.304/JetBrainsMono-2.304.zip",
    # Model weights / data science
    "https://huggingface.co/bert-base-uncased/resolve/main/config.json",
    "https://huggingface.co/gpt2/resolve/main/config.json",
    "https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt",
]

KNOWN_MEDIA = [
    # YouTube
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "https://www.youtube.com/watch?v=ZZ5LpwO-An4",
    "https://www.youtube.com/watch?v=9bZkp7q19f0",
    "https://www.youtube.com/watch?v=kJQP7kiw5Fk",
    "https://www.youtube.com/watch?v=RgKAFK5djSk",
    "https://www.youtube.com/watch?v=OPf0YbXqDm0",
    "https://www.youtube.com/watch?v=hT_nvWreIhg",
    "https://www.youtube.com/watch?v=uelHwf8o7_U",
    "https://www.youtube.com/watch?v=lp-EO5I60KA",
    "https://www.youtube.com/watch?v=fRh_vgS2dFE",
    "https://www.youtube.com/watch?v=60ItHLz5WEA",
    "https://www.youtube.com/watch?v=09R8_2nJtjg",
    "https://www.youtube.com/watch?v=nfWlot6h_JM",
    "https://www.youtube.com/watch?v=CevxZvSJLk8",
    "https://www.youtube.com/watch?v=YqeW9_5kURI",
    "https://www.youtube.com/watch?v=7PCkvCPvDXk",
    "https://www.youtube.com/watch?v=Sagg08DrO5U",
    "https://www.youtube.com/watch?v=DJ2LUrX4eRM",
    "https://www.youtube.com/watch?v=2vjPBrBU-TM",
    # Vimeo
    "https://vimeo.com/148751763",
    "https://vimeo.com/channels/staffpicks/833741888",
    "https://vimeo.com/76979871",
    "https://vimeo.com/22439234",
    "https://vimeo.com/350792083",
    # Spotify
    "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
    "https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv",
    "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
    "https://open.spotify.com/episode/5MkMjfAMIyMfKXaXNdvzn2",
    # SoundCloud
    "https://soundcloud.com/forss/flickermood",
    "https://soundcloud.com/deadmau5/strobe",
    # Twitch / Dailymotion
    "https://www.twitch.tv/videos/1234567890",
    "https://www.dailymotion.com/video/x7tgd4z",
    "https://www.dailymotion.com/video/x8jfath",
    # TikTok
    "https://www.tiktok.com/@khaby.lame/video/7016180758702729478",
    "https://www.tiktok.com/@charlidamelio/video/6815862574645608709",
    # Podcast audio
    "https://feeds.simplecast.com/54nAGcIl",
    "https://anchor.fm/s/example/podcast/rss",
    # Direct video/audio files
    "https://www.w3schools.com/html/mov_bbb.mp4",
    "https://samplelib.com/lib/preview/mp3/sample-15s.mp3",
    # YouTube — education / tech
    "https://www.youtube.com/watch?v=aircAruvnKk",
    "https://www.youtube.com/watch?v=IHZwWFHWa-w",
    "https://www.youtube.com/watch?v=Ilg3gGewQ5U",
    "https://www.youtube.com/watch?v=WUvTyaaNkzM",
    "https://www.youtube.com/watch?v=tIeHLnjs5U8",
    "https://www.youtube.com/watch?v=rfscVS0vtbw",
    "https://www.youtube.com/watch?v=ZdMTznuG0ek",
    "https://www.youtube.com/watch?v=ysEN5RaKOlA",
    "https://www.youtube.com/watch?v=8jLOx1hD3_o",
    "https://www.youtube.com/watch?v=BvHmRx14HQ8",
    "https://www.youtube.com/watch?v=LXb3EKWsInQ",
    "https://www.youtube.com/watch?v=k1BneeJTDcU",
    "https://www.youtube.com/watch?v=PLZHQObOWTQD",
    "https://www.youtube.com/playlist?list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi",
    "https://www.youtube.com/playlist?list=PL3FW7Lu3i5JvHM8ljYj-zLfQRF3EO8sYv",
    "https://www.youtube.com/@veritasium",
    "https://www.youtube.com/@TED",
    "https://www.youtube.com/@3blue1brown",
    "https://www.youtube.com/watch?v=GvRfAMFGBbM",
    "https://www.youtube.com/watch?v=yiw6_JakZFc",
    # Vimeo extra
    "https://vimeo.com/195038535",
    "https://vimeo.com/637099140",
    "https://vimeo.com/167169080",
    "https://vimeo.com/383635459",
    "https://vimeo.com/452520592",
    # Spotify extra
    "https://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl",
    "https://open.spotify.com/track/3AJwUDP919kvQ9QcozQPxg",
    "https://open.spotify.com/track/7qiZfU4dY1lWllzX7mPBI3",
    "https://open.spotify.com/track/0ct6r3EGTcMLPtrXHDvVjc",
    "https://open.spotify.com/track/5ChkMS8OtdzJeqyybCc9R5",
    "https://open.spotify.com/playlist/37i9dQZEVXbMDoHDwVN2tF",
    "https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd",
    "https://open.spotify.com/show/2mTUnDkuKUkhiueKcVWoP0",
    # SoundCloud extra
    "https://soundcloud.com/nocopyrightsounds/elektronomia-sky-high",
    "https://soundcloud.com/marshmello/happier",
    "https://soundcloud.com/martingarrix/animals-original-mix",
    # Twitch extra
    "https://www.twitch.tv/ninja",
    "https://www.twitch.tv/shroud",
    "https://clips.twitch.tv/CuriousSpeedyPizzaKappaRoss",
    # Dailymotion extra
    "https://www.dailymotion.com/video/x6y5bqg",
    # TikTok extra
    "https://www.tiktok.com/@mrbeast/video/7242547030063576366",
    # Apple Podcasts
    "https://podcasts.apple.com/us/podcast/the-daily/id1200361736",
    "https://podcasts.apple.com/us/podcast/serial/id917918570",
    "https://podcasts.apple.com/us/podcast/lex-fridman-podcast/id1434243584",
    # Direct files
    "https://www.learningcontainer.com/wp-content/uploads/2020/05/sample-mp4-file.mp4",
    "https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4",
    "https://file-examples.com/storage/fe3b9f3b5b6462e2c1c3d63/2017/11/file_example_MP3_700KB.mp3",
    "https://feeds.simplecast.com/54nAGcIl",
    "https://rss.art19.com/the-daily",
]

KNOWN_ACADEMIC = [
    # arXiv
    "https://arxiv.org/abs/2310.06825",
    "https://arxiv.org/abs/2307.09288",
    "https://arxiv.org/abs/1706.03762",
    "https://arxiv.org/abs/2303.08774",
    "https://arxiv.org/abs/2204.05149",
    "https://arxiv.org/abs/2302.07842",
    "https://arxiv.org/abs/2305.10601",
    "https://arxiv.org/abs/2106.09685",
    "https://arxiv.org/abs/2210.11610",
    "https://arxiv.org/abs/2112.00114",
    "https://arxiv.org/abs/2005.14165",
    "https://arxiv.org/abs/2108.07258",
    "https://arxiv.org/abs/1810.04805",
    "https://arxiv.org/abs/2009.03300",
    "https://arxiv.org/abs/2212.08073",
    "https://arxiv.org/abs/2201.11903",
    "https://arxiv.org/abs/2302.04761",
    "https://arxiv.org/abs/2209.01667",
    "https://arxiv.org/abs/2308.09583",
    "https://arxiv.org/abs/2310.01848",
    # DOI
    "https://doi.org/10.1145/3589334.3645447",
    "https://doi.org/10.1038/s41586-021-03819-2",
    "https://doi.org/10.1126/science.abn7293",
    "https://doi.org/10.1145/3442188.3445922",
    "https://doi.org/10.1109/TPAMI.2022.3229526",
    # PubMed
    "https://pubmed.ncbi.nlm.nih.gov/37798500/",
    "https://pubmed.ncbi.nlm.nih.gov/36959423/",
    "https://pubmed.ncbi.nlm.nih.gov/35110290/",
    "https://pubmed.ncbi.nlm.nih.gov/34887591/",
    "https://pubmed.ncbi.nlm.nih.gov/33378628/",
    # ACM / IEEE
    "https://dl.acm.org/doi/10.1145/3442188.3445922",
    "https://dl.acm.org/doi/10.1145/3290605.3300724",
    "https://ieeexplore.ieee.org/document/9833667",
    "https://ieeexplore.ieee.org/document/10097171",
    # Semantic Scholar / ResearchGate
    "https://www.semanticscholar.org/paper/Attention-Is-All-You-Need/204e3073870fae3d05bcbc2f6a8e263d9b72e776",
    "https://www.semanticscholar.org/paper/BERT%3A-Pre-training-of-Deep-Bidirectional-Transformers/df2b0e26d0599ce3e70df8a9da02e51594e0e992",
    "https://www.researchgate.net/publication/362624083",
    # SSRN / JSTOR
    "https://ssrn.com/abstract=4337202",
    "https://ssrn.com/abstract=3906162",
    "https://www.jstor.org/stable/j.ctt1bh4bz4",
    # University repositories
    "https://repository.tudelft.nl/islandora/object/uuid:bd42440e-d4e8-41ba-9d56-e1c6d3e07c75",
    "https://eprints.lse.ac.uk/118352/",
    "https://ora.ox.ac.uk/objects/uuid:5c20659c-03a4-4c14-87ef-67bb60b3bcb8",
    # Scholar
    "https://scholar.google.com/scholar?q=large+language+models+survey",
    "https://scholar.google.com/scholar?q=transformer+neural+network",
]

KNOWN_API_JSON = [
    # GitHub API
    "https://api.github.com/repos/python/cpython",
    "https://api.github.com/repos/torvalds/linux",
    "https://api.github.com/users/torvalds",
    "https://api.github.com/repos/microsoft/vscode",
    "https://api.github.com/orgs/openai",
    "https://api.github.com/repos/huggingface/transformers",
    "https://api.github.com/search/repositories?q=language%3Apython&sort=stars",
    # Open data / government
    "https://data.gov/api/3/action/package_list",
    "https://data.go.th/api/3/action/package_list",
    "https://opendata.cdc.gov/api/views/9mfq-cb36.json",
    "https://data.cityofnewyork.us/api/views/kku6-nxdu.json",
    # Public REST APIs
    "https://jsonplaceholder.typicode.com/posts/1",
    "https://jsonplaceholder.typicode.com/users/1",
    "https://jsonplaceholder.typicode.com/todos/1",
    "https://restcountries.com/v3.1/name/thailand",
    "https://restcountries.com/v3.1/alpha/US",
    "https://restcountries.com/v3.1/region/asia",
    "https://api.open-meteo.com/v1/forecast?latitude=13.75&longitude=100.52&current_weather=true",
    "https://api.open-meteo.com/v1/forecast?latitude=35.68&longitude=139.69&current_weather=true",
    "https://catfact.ninja/fact",
    "https://api.agify.io?name=michael",
    "https://api.agify.io?name=james",
    "https://httpbin.org/get",
    "https://httpbin.org/json",
    "https://dummyjson.com/products/1",
    "https://dummyjson.com/users/1",
    "https://dummyjson.com/posts/1",
    # Exchange rates / finance
    "https://open.er-api.com/v6/latest/USD",
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json",
    # Package registries
    "https://registry.npmjs.org/react",
    "https://registry.npmjs.org/lodash",
    "https://pypi.org/pypi/requests/json",
    "https://pypi.org/pypi/numpy/json",
    # GeoJSON / spatial
    "https://nominatim.openstreetmap.org/search?q=Bangkok&format=json",
    "https://nominatim.openstreetmap.org/search?q=Tokyo&format=json",
    # Wikipedia API
    "https://en.wikipedia.org/api/rest_v1/page/summary/Python_(programming_language)",
    "https://en.wikipedia.org/api/rest_v1/page/summary/Large_language_model",
    # Misc
    "https://api.stackexchange.com/2.3/questions?order=desc&sort=activity&site=stackoverflow",
    "https://hn.algolia.com/api/v1/search?query=llm&tags=story",
    "https://pokeapi.co/api/v2/pokemon/pikachu",
    "https://swapi.dev/api/people/1/",
    "https://rickandmortyapi.com/api/character/1",
    "https://api.spacexdata.com/v4/launches/latest",
    "https://disease.sh/v3/covid-19/all",
    "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY",
    "https://api.thecatapi.com/v1/breeds",
    "https://dog.ceo/api/breeds/list/all",
]

KNOWN_REDIRECT = [
    # Bit.ly (real shortened links to known destinations)
    "https://bit.ly/3OvhCcN",    # → python.org
    "https://bit.ly/3tGpUVL",    # → github.com
    "https://bit.ly/3XkJ9vM",    # → wikipedia.org
    "https://bit.ly/3J3mQfH",    # → stackoverflow.com
    "https://bit.ly/3mNm2z5",    # → youtube.com
    "https://bit.ly/3wRtrLA",    # → reddit.com
    "https://bit.ly/3JjCuJP",    # → medium.com
    "https://bit.ly/3N5gJyF",    # → linkedin.com
    "https://bit.ly/3YVlQMU",    # → twitter.com
    "https://bit.ly/45BkJPl",    # → amazon.com
    # TinyURL
    "https://tinyurl.com/y4mmu6fy",
    "https://tinyurl.com/2p9ery3n",
    "https://tinyurl.com/5n8z2crt",
    "https://tinyurl.com/mr3unm49",
    "https://tinyurl.com/yck2f8x7",
    # t.co (Twitter/X short links)
    "https://t.co/6BRbTzMczX",
    "https://t.co/kFnnCFGQRZ",
    "https://t.co/mRFcl1Nq8E",
    # ow.ly / Hootsuite
    "https://ow.ly/i/hGJdC",
    # rb.gy
    "https://rb.gy/ixzf1",
    "https://rb.gy/c9wkq",
    # cutt.ly
    "https://cutt.ly/cwBERTkH",
    # is.gd
    "https://is.gd/mfhpFU",
    "https://is.gd/OvHZbL",
    # v.gd
    "https://v.gd/example1",
    # Short links with known redirect chains (2+ hops)
    "https://goo.gl/maps/example",
    "https://maps.app.goo.gl/example",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://youtu.be/jNQXAC9IVRw",
    "https://amzn.to/3example",
    "https://amzn.to/4example",
    "https://go.microsoft.com/fwlink/?linkid=2088631",
    "https://go.microsoft.com/fwlink/?linkid=2123569",
    "https://aka.ms/vscode-server-doc",
    "https://aka.ms/copilot",
    # HTTP → HTTPS redirects (always at least 1 hop)
    "http://python.org",
    "http://github.com",
    "http://wikipedia.org",
    "http://stackoverflow.com",
    "http://mozilla.org",
    "http://apache.org",
    "http://gnu.org",
    "http://debian.org",
    "http://ubuntu.com",
    "http://nodejs.org",
]

# ── Main sampling ─────────────────────────────────────────────────────────────

def main():
    print("Fetching Tranco top-10k...")
    tranco_domains = fetch_tranco_top10k()

    print("Fetching Common Crawl sample...")
    cc_urls = fetch_commoncrawl_sample(300)

    # Build pools
    pool: dict[str, list[dict]] = {s: [] for s in STRATA_TARGETS}

    for domain in tranco_domains:
        url     = f"https://{domain}/"
        stratum = guess_stratum(domain)
        if stratum in pool:
            pool[stratum].append({"url": url, "source": "tranco",
                                   "stratum": stratum})

    for url in cc_urls:
        stratum = guess_stratum(url.split("/")[2] if "/" in url else url)
        if stratum in ("file_download", "api_json", "redirect_chain", "academic"):
            pool[stratum].append({"url": url, "source": "commoncrawl",
                                   "stratum": stratum})

    # Supplement known-list strata
    for url in KNOWN_FILE_DOWNLOAD:
        pool["file_download"].append({"url": url, "source": "manual",
                                       "stratum": "file_download"})
    for url in KNOWN_MEDIA:
        pool["media"].append({"url": url, "source": "manual",
                               "stratum": "media"})
    for url in KNOWN_ACADEMIC:
        pool["academic"].append({"url": url, "source": "manual",
                                  "stratum": "academic"})
    for url in KNOWN_API_JSON:
        pool["api_json"].append({"url": url, "source": "manual",
                                  "stratum": "api_json"})
    for url in KNOWN_REDIRECT:
        pool["redirect_chain"].append({"url": url, "source": "manual",
                                        "stratum": "redirect_chain"})

    # Safety unknown: random webpage-looking domains
    pool["safety_unknown"] = [
        {"url": f"https://{d}/", "source": "tranco",
         "stratum": "safety_unknown"}
        for d in random.sample(tranco_domains, min(500, len(tranco_domains)))
        if guess_stratum(d) == "webpage"
    ]

    # Sample per stratum
    sampled: list[dict] = []
    print("\nSampling per stratum:")
    for stratum, proportion in STRATA_TARGETS.items():
        target_n  = round(TOTAL_SAMPLE * proportion)
        available = pool.get(stratum, [])
        # Deduplicate within stratum
        seen = set()
        unique = []
        for item in available:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique.append(item)
        if len(unique) < target_n:
            print(f"  [WARN] '{stratum}': need {target_n}, "
                  f"have {len(unique)} unique — using all")
            target_n = len(unique)
        selected = random.sample(unique, target_n)
        sampled.extend(selected)
        print(f"  {stratum:20s}: {len(selected):4d} URLs")

    random.shuffle(sampled)
    print(f"\nTotal sampled: {len(sampled)} URLs")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for item in sampled:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"Saved → {OUT_PATH}")

    # Stratum summary
    counts = {}
    for item in sampled:
        counts[item["stratum"]] = counts.get(item["stratum"], 0) + 1
    print("\nStratum distribution:")
    for s, n in sorted(counts.items(), key=lambda x: -x[1]):
        pct = n / len(sampled) * 100
        print(f"  {s:20s}: {n:4d}  ({pct:.1f}%)")

    if len(sampled) < 1000:
        print(f"\n[WARN] Only {len(sampled)} URLs sampled (target 1,200).")
        print("  Options:")
        print("  1. Download Tranco manually: https://tranco-list.eu/list/X4NZN/10000")
        print("     Save as: data/tranco_10k.csv  (format: rank,domain)")
        print("  2. Add more URLs to KNOWN_* lists in this script")
        print("  3. Re-run after adding data")


if __name__ == "__main__":
    main()
