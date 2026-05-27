from datetime import datetime, timezone
from playwright.sync_api import sync_playwright
from urllib.parse import urljoin, urlparse, urlunparse
import argparse
import csv
import json
import re
import sys
import time

UA_DESKTOP_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

SITE_JOBS = [
    {
        "site_key": "economic_times",
        "publisher": "Economic Times",
        "source": "Economic Times",
        "url": "https://economictimes.indiatimes.com/?from=mdr",
        "base_url": "https://economictimes.indiatimes.com/",
        "selectors": ["a[href]"],
        "allow_patterns": [r"/articleshow/\d+\.cms"],
        "exclude_patterns": [r"/\?from=mdr$", r"/photostory/", r"/videoshow/"],
    },
    {
        "site_key": "livemint",
        "publisher": "Mint",
        "source": "Mint",
        "url": "https://www.livemint.com/",
        "base_url": "https://www.livemint.com/",
        "selectors": ["a[href]"],
        "allow_patterns": [],
        "exclude_patterns": [r"^https://www\.livemint\.com/?$", r"/photos/", r"/videos/", r"/topic/"],
    },
    {
        "site_key": "cnbc_tv18",
        "publisher": "CNBC TV18",
        "source": "CNBC TV18",
        "url": "https://www.cnbctv18.com/",
        "base_url": "https://www.cnbctv18.com/",
        "selectors": ["a[href]"],
        "allow_patterns": [],
        "exclude_patterns": [r"^https://www\.cnbctv18\.com/?$", r"/photos/", r"/videos/", r"/live-tv/"],
    },
    {
        "site_key": "ndtv_profit",
        "publisher": "NDTV Profit",
        "source": "NDTV Profit",
        "url": "https://www.ndtvprofit.com/",
        "base_url": "https://www.ndtvprofit.com/",
        "selectors": ["a[href]"],
        "allow_patterns": [],
        "exclude_patterns": [r"^https://www\.ndtvprofit\.com/?$", r"/photos/", r"/videos/", r"/live-tv", r"/topic/"],
        "prefer_channel": "chrome",
    },
    {
        "site_key": "zee_biz",
        "publisher": "Zee Business",
        "source": "Zee Business",
        "url": "https://www.zeebiz.com/",
        "base_url": "https://www.zeebiz.com/",
        "selectors": ["a[href]"],
        "allow_patterns": [],
        "exclude_patterns": [r"^https://www\.zeebiz\.com/?$", r"/photos/", r"/videos/", r"/live-tv", r"/topic/"],
    },
]

BLOCK_TITLE_PATTERNS = [
    r"^\s*$",
    r"^advertisement$",
    r"^sponsored$",
    r"^follow us",
    r"^read epaper$",
    r"^subscribe",
    r"^newsletter$",
    r"^privacy policy$",
    r"^terms and conditions$",
    r"^latest news$",
    r"^markets$",
    r"^business$",
    r"^videos?$",
    r"^photos?$",
    r"^view all$",
    r"^view market dashboard$",
    r"^mark to market$",
    r"^ask mint money$",
    r"^ipl\s*2026\s*schedule$",
    r"^orange cap in ipl\s*2026$",
    r"^purple cap in ipl\s*2026$",
    r"^ipl\s*2026\s*points table$",
    r"^ifsc code finder$",
    r"^income tax calculator$",
    r"^gold rate today$",
    r"^gold rate in delhi$",
    r"^gold rate hyderabad$",
    r"^silver rate today$",
    r"^silver rate in delhi$",
    r"^silver rate in bangalore$",
    r"^us stock market$",
    r"^stock market live updates$",
    r"^us-iran war live updates$",
    r"^become a member$",
    r"^education & careers$",
    r"^india business leader awards$",
    r"^the growth summit$",
    r"^accelerate your cloud journey$",
    r"^accelerating to a connected future$",
    r"^financial services cloud symposium$",
    r"^ey entrepreneur of the year$",
    r"^wizards of finance$",
    r"^the thought league$",
    r"^us iran war news$",
    r"^donald trump news$",
    r"^adani enterprises ltd\.?$",
    r"^adani ports & special economic zone ltd\.?$",
    r"^apollo hospitals enterprise ltd\.?$",
    r"^asian paints ltd\.?$",
    r"^axis bank ltd\.?$",
    r"^global leadership summit$",
    r"^future female forward$",
    r"^us iran war$",
    r"^cnbc tv18 prime$",
]


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def add_stealth(ctx_or_page):
    if hasattr(ctx_or_page, "add_init_script"):
        ctx_or_page.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {get: () => false});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
            """
        )


def click_cookie_banners(page):
    selectors = [
        "button:has-text('Accept')",
        "button:has-text('I Agree')",
        "button:has-text('AGREE')",
        "button:has-text('Got it')",
        "button:has-text('Continue')",
        "#onetrust-accept-btn-handler",
        "#wzrk-confirm",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible():
                locator.click(timeout=1200)
                time.sleep(0.2)
                break
        except Exception:
            pass


def clean_headline(text):
    title = re.sub(r"\s+", " ", text or "").strip()
    title = re.sub(r"<[^>]+>", " ", title)
    title = re.sub(r"^(Article image for:\s*|Link for\s+|Photo:\s*|Image:\s*)", "", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def canonicalize_url(link, job):
    parsed = urlparse(link)
    clean_path = re.sub(r"/+", "/", parsed.path or "/")
    canonical = parsed._replace(query="", fragment="", path=clean_path)
    canonical_url = urlunparse(canonical)
    if job["publisher"] == "Economic Times":
        match = re.search(r"/articleshow/(\d+)\.cms", clean_path, re.I)
        if match:
            return f"{job['base_url'].rstrip('/')}/articleshow/{match.group(1)}.cms"
    return canonical_url


def dedupe_key(job, link):
    if job["publisher"] == "Economic Times":
        match = re.search(r"/articleshow/(\d+)\.cms", link, re.I)
        if match:
            return f"{job['site_key']}:{match.group(1)}"
    return link


def extract_anchors(page, selectors=None):
    return page.evaluate(
        """
        ({ selectors }) => {
          const out = [];
          const seen = new Set();
          const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
          const allAnchors = selectors && selectors.length
            ? selectors.flatMap((selector) => Array.from(document.querySelectorAll(selector)))
            : Array.from(document.querySelectorAll('a[href]'));
          allAnchors.forEach((a) => {
            const href = a.href || a.getAttribute('href') || '';
            let title = norm(a.getAttribute('title') || a.getAttribute('aria-label') || '');
            if (!title) {
              title = norm(a.textContent || '');
            }
            if (!href || !title) return;
            const key = href + '|' + title;
            if (seen.has(key)) return;
            seen.add(key);
            out.push({ href, title });
          });
          return out;
        }
        """,
        {"selectors": selectors or []},
    )


def is_valid_candidate(link, title, job):
    lower_title = title.lower()
    parsed = urlparse(link)
    path = parsed.path.rstrip("/")
    if parsed.scheme not in ("http", "https"):
        return False
    if any(re.search(pattern, link, re.I) for pattern in job["exclude_patterns"]):
        return False
    if job["allow_patterns"] and not any(re.search(pattern, link, re.I) for pattern in job["allow_patterns"]):
        return False
    if any(re.search(pattern, lower_title, re.I) for pattern in BLOCK_TITLE_PATTERNS):
        return False
    if len(title) < 10 or len(title.split()) < 3:
        return False
    if "taboola" in link.lower():
        return False
    if any(
        fragment in link.lower()
        for fragment in (
            "/contact",
            "/terms",
            "/privacy",
            "/author/",
            "/photo-gallery/",
            "/code-of-ethics",
            "/live-tv",
            "/livetv",
        )
    ):
        return False
    if parsed.netloc and urlparse(job["base_url"]).netloc not in parsed.netloc:
        return False
    if path in ("", "/"):
        return False
    return True


def normalize_rows(job, candidates):
    rows = []
    seen_links = set()
    for item in candidates:
        raw_link = urljoin(job["base_url"], item["href"])
        link = canonicalize_url(raw_link, job)
        title = clean_headline(item["title"])
        key = dedupe_key(job, link)
        if key in seen_links:
            continue
        if not is_valid_candidate(link, title, job):
            continue
        seen_links.add(key)
        rows.append(
            {
                "publisher": job["publisher"],
                "source": job["source"],
                "source_url": job["url"],
                "rank": len(rows) + 1,
                "headline": title,
                "link": link,
            }
        )
    return rows


def render_html(rows):
    data_json = json.dumps(rows, ensure_ascii=False)
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Business Frontpages Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {{
    --paper: #eef0eb; --paper-deep: #dfe5dc; --ink: #171c16; --muted: #5b675e;
    --line: rgba(23, 28, 22, 0.12); --panel: rgba(255,255,255,0.78);
    --accent: #0f5f57; --accent-soft: rgba(15,95,87,0.12);
    --shadow: 0 18px 42px rgba(54, 70, 58, 0.12); --display: Georgia, "Times New Roman", serif;
    --body: "Avenir Next", "Segoe UI", sans-serif;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; color: var(--ink); font-family: var(--body);
    background:
      radial-gradient(circle at top left, rgba(15,95,87,0.12), transparent 24%),
      radial-gradient(circle at 85% 10%, rgba(165,119,53,0.12), transparent 22%),
      linear-gradient(180deg, #f3f6f0 0%, var(--paper) 54%, var(--paper-deep) 100%);
  }}
  a {{ color: inherit; text-decoration: none; }}
  .page {{ width: min(1420px, calc(100% - 28px)); margin: 0 auto; padding: 22px 0 40px; }}
  .hero {{
    padding: 26px; border-radius: 28px;
    background: linear-gradient(135deg, rgba(18,33,30,0.98), rgba(18,85,76,0.94) 48%, rgba(74,116,68,0.9) 100%);
    color: #fff9f2; box-shadow: var(--shadow);
  }}
  .eyebrow {{
    display: inline-flex; padding: 8px 12px; border-radius: 999px; text-transform: uppercase;
    letter-spacing: 0.12em; font-size: 12px; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.12);
  }}
  .hero h1 {{ margin: 14px 0 0; font: 700 clamp(40px, 6vw, 70px)/0.94 var(--display); letter-spacing: -0.05em; }}
  .metrics, .summary {{ display: grid; gap: 12px; margin-top: 20px; }}
  .metrics {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
  .summary {{ grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 16px; }}
  .metric, .summary-card {{
    padding: 16px 18px; border-radius: 18px; border: 1px solid rgba(255,255,255,0.18);
    background: rgba(255,255,255,0.08); box-shadow: 0 10px 24px rgba(82, 62, 42, 0.08);
  }}
  .summary-card {{ background: var(--panel); border-color: rgba(255,255,255,0.66); }}
  .metric-label, .summary-card strong {{
    display: block; font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: rgba(255,249,242,0.72);
  }}
  .summary-card strong {{ color: var(--muted); margin-bottom: 6px; }}
  .metric-value, .summary-card span {{ display: block; margin-top: 6px; font-size: clamp(24px, 3vw, 34px); font-weight: 700; }}
  .controls {{
    margin-top: 18px; padding: 18px; border-radius: 28px; background: rgba(255,255,255,0.58);
    border: 1px solid rgba(255,255,255,0.6); box-shadow: 0 10px 28px rgba(86, 63, 42, 0.08);
  }}
  .toolbar {{ display: grid; grid-template-columns: 1.6fr repeat(2, minmax(180px, 1fr)) auto; gap: 12px; align-items: end; }}
  .field {{ display: grid; gap: 6px; }}
  .field span {{ font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }}
  input, select, button {{
    width: 100%; padding: 13px 14px; border-radius: 14px; border: 1px solid var(--line);
    background: rgba(255,255,255,0.82); color: var(--ink); font: inherit;
  }}
  button {{ width: auto; background: var(--accent); color: white; border-color: transparent; font-weight: 700; cursor: pointer; }}
  .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-top: 20px; align-items: start; }}
  .panel {{
    display: grid; gap: 12px; padding: 18px; border-radius: 22px; background: var(--panel);
    border: 1px solid rgba(255,255,255,0.66); box-shadow: 0 14px 34px rgba(82, 62, 42, 0.1); align-self: start;
  }}
  .panel-head {{ display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }}
  .panel h2 {{ margin: 0; font: 700 24px/1.08 var(--display); letter-spacing: -0.03em; }}
  .meta {{ display: flex; gap: 8px; flex-wrap: wrap; font-size: 12px; color: var(--muted); }}
  .story-list {{ margin: 0; padding-left: 18px; display: grid; gap: 0; }}
  .story-list li {{ line-height: 1.14; color: var(--muted); margin: 0; }}
  .story-list a {{ color: var(--ink); }}
  .empty {{
    grid-column: 1 / -1; padding: 34px 22px; border-radius: 22px; background: rgba(255,255,255,0.72);
    border: 1px dashed rgba(23,19,15,0.18); text-align: center; color: var(--muted);
  }}
  @media (max-width: 1180px) {{ .toolbar {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
  @media (max-width: 920px) {{ .metrics, .summary, .grid {{ grid-template-columns: 1fr; }} }}
  @media (max-width: 640px) {{ .page {{ width: min(100% - 18px, 1420px); }} .hero, .controls {{ padding: 18px; }} .toolbar {{ grid-template-columns: 1fr; }} button {{ width: 100%; }} }}
</style>
<div class="page">
  <section class="hero">
    <div class="eyebrow">Business Frontpages</div>
    <h1>Business Frontpages Dashboard</h1>
    <div class="metrics">
      <div class="metric"><span class="metric-label">Tracked Sources</span><span class="metric-value" id="metricSources">0</span></div>
      <div class="metric"><span class="metric-label">Stories In Snapshot</span><span class="metric-value" id="metricStories">0</span></div>
      <div class="metric"><span class="metric-label">Last Refresh</span><span class="metric-value" id="metricRefresh">-</span></div>
    </div>
  </section>
  <section class="controls">
    <div class="toolbar">
      <label class="field"><span>Search</span><input id="search" placeholder="Search headlines..."></label>
      <label class="field"><span>Publisher</span><select id="publisherSelect"></select></label>
      <label class="field"><span>Sort</span><select id="sort"><option value="rankAsc">Rank: low to high</option><option value="rankDesc">Rank: high to low</option><option value="alpha">Headline: A to Z</option></select></label>
      <button id="reload" type="button">Reset</button>
    </div>
    <div class="summary">
      <div class="summary-card"><strong>Visible Panels</strong><span id="visibleCount">0</span></div>
      <div class="summary-card"><strong>Publisher</strong><span id="activePublisher">All</span></div>
      <div class="summary-card"><strong>Sources</strong><span id="activeSources">-</span></div>
      <div class="summary-card"><strong>Search State</strong><span id="searchState">Everything</span></div>
    </div>
  </section>
  <main class="grid" id="grid"></main>
</div>
<script>
const RAW = {data_json};
const SOURCES = [...new Set(RAW.map(d => d.source))];
const PUBLISHERS = [...new Set(RAW.map(d => d.publisher))];
const state = {{ raw: RAW, filterText: "", sortMode: "rankAsc", publisher: "All" }};
function asc(a, b) {{ return a < b ? -1 : a > b ? 1 : 0; }}
function formatStamp(value) {{
  if (!value) return "-";
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return dt.toLocaleString("en-IN", {{ day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }});
}}
function applyFilters(rows) {{
  let result = rows.slice();
  if (state.publisher !== "All") result = result.filter(d => d.publisher === state.publisher);
  if (state.filterText) {{
    const q = state.filterText.toLowerCase();
    result = result.filter(d => (d.headline || "").toLowerCase().includes(q) || (d.source || "").toLowerCase().includes(q));
  }}
  switch (state.sortMode) {{
    case "rankAsc": result.sort((a, b) => a.rank - b.rank); break;
    case "rankDesc": result.sort((a, b) => b.rank - a.rank); break;
    case "alpha": result.sort((a, b) => asc(a.headline, b.headline)); break;
  }}
  return result;
}}
function bySource(rows) {{
  return SOURCES.map(source => ({{ source, rows: rows.filter(row => row.source === source) }})).filter(group => group.rows.length);
}}
function panelTemplate(group) {{
  const top = group.rows[0];
  const items = group.rows.map(row => `<li><a href="${{row.link}}" target="_blank" rel="noopener">#${{row.rank}} ${{row.headline}}</a></li>`).join("");
  return `<section class="panel">
    <div class="panel-head">
      <div>
        <h2><a href="${{top.source_url || '#'}}" target="_blank" rel="noopener">${{group.source}}</a></h2>
      </div>
      <div class="meta"><span>${{group.rows.length}} stories</span><span>${{formatStamp(top.collected_at_iso)}}</span></div>
    </div>
    <ol class="story-list">${{items}}</ol>
  </section>`;
}}
function renderPanels(rows) {{
  const root = document.querySelector("#grid");
  const groups = bySource(rows);
  if (!groups.length) {{
    root.innerHTML = `<div class="empty">No source matches this filter yet. Try another publisher or clear the search.</div>`;
    return;
  }}
  root.innerHTML = groups.map(panelTemplate).join("");
}}
function renderSummary(rows) {{
  document.querySelector("#visibleCount").textContent = String(bySource(rows).length);
  document.querySelector("#activePublisher").textContent = state.publisher;
  document.querySelector("#activeSources").textContent = String(bySource(rows).length);
  document.querySelector("#searchState").textContent = state.filterText ? `“${{state.filterText}}”` : "Everything";
}}
function renderHeroMetrics() {{
  document.querySelector("#metricSources").textContent = String(SOURCES.length);
  document.querySelector("#metricStories").textContent = String(RAW.length);
  const latest = RAW.reduce((acc, row) => (row.collected_at_iso || "") > acc ? (row.collected_at_iso || "") : acc, "");
  document.querySelector("#metricRefresh").textContent = formatStamp(latest);
}}
function fillSelect(id, values) {{
  document.querySelector(id).innerHTML = ["All", ...values].map(v => `<option value="${{v}}">${{v}}</option>`).join("");
}}
function render() {{
  const rows = applyFilters(state.raw);
  renderPanels(rows);
  renderSummary(rows);
}}
document.querySelector("#search").addEventListener("input", ev => {{ state.filterText = ev.target.value || ""; render(); }});
document.querySelector("#publisherSelect").addEventListener("change", ev => {{ state.publisher = ev.target.value; render(); }});
document.querySelector("#sort").addEventListener("change", ev => {{ state.sortMode = ev.target.value; render(); }});
document.querySelector("#reload").addEventListener("click", () => {{
  state.filterText = ""; state.sortMode = "rankAsc"; state.publisher = "All";
  document.querySelector("#search").value = "";
  document.querySelector("#publisherSelect").value = "All";
  document.querySelector("#sort").value = "rankAsc";
  render();
}});
fillSelect("#publisherSelect", PUBLISHERS);
renderHeroMetrics();
render();
</script>
"""


def scrape_job(page, job, wait_ms, retries, nav_timeout_ms):
    items = []
    last_error = None
    for _ in range(retries + 1):
        try:
            page.goto(job["url"], wait_until="domcontentloaded", timeout=nav_timeout_ms)
            time.sleep(wait_ms / 1000.0)
            click_cookie_banners(page)
            for _ in range(3):
                page.mouse.wheel(0, 1400)
                time.sleep(0.5)
            candidates = extract_anchors(page, selectors=job.get("selectors"))
            items = normalize_rows(job, candidates)
            if items:
                return items
        except Exception as exc:
            last_error = exc
    if last_error:
        print(f"[WARN] {job['source']} extraction failed: {last_error}", file=sys.stderr)
    return items


def launch_browser_and_page(playwright, args, channel_override=None):
    browser_type = {
        "chromium": playwright.chromium,
        "firefox": playwright.firefox,
        "webkit": playwright.webkit,
    }[args.engine]
    launch_kwargs = {
        "headless": args.headless,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    channel = channel_override
    if args.engine == "chromium" and channel is None and args.channel in ("chrome", "msedge"):
        channel = args.channel
    if args.engine == "chromium" and channel:
        launch_kwargs["channel"] = channel
    browser = browser_type.launch(**launch_kwargs)
    context = browser.new_context(
        viewport={"width": 1440, "height": 960},
        user_agent=UA_DESKTOP_CHROME,
        locale="en-US",
        timezone_id="Asia/Kolkata",
    )
    add_stealth(context)
    page = context.new_page()
    add_stealth(page)
    return browser, context, page


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", choices=[job["site_key"] for job in SITE_JOBS] + ["all"], default="all")
    parser.add_argument("--out_csv", default="business_frontpages.csv")
    parser.add_argument("--out_json", default="business_frontpages.json")
    parser.add_argument("--out_html", default="")
    parser.add_argument("--engine", choices=["chromium", "firefox", "webkit"], default="chromium")
    parser.add_argument("--channel", choices=["none", "chrome", "msedge"], default="none")
    parser.add_argument("--wait_ms", type=int, default=1800)
    parser.add_argument("--nav_timeout_ms", type=int, default=25000)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser, context, page = launch_browser_and_page(playwright, args)
        chrome_browser = chrome_context = chrome_page = None
        if args.engine == "chromium" and args.channel == "none":
            try:
                chrome_browser, chrome_context, chrome_page = launch_browser_and_page(playwright, args, channel_override="chrome")
            except Exception as exc:
                print(f"[WARN] Chrome fallback unavailable: {exc}", file=sys.stderr)

        timestamp = now_iso()
        collected = []
        for job in SITE_JOBS:
            if args.site not in (job["site_key"], "all"):
                continue
            active_page = chrome_page if job.get("prefer_channel") == "chrome" and chrome_page is not None else page
            items = scrape_job(active_page, job=job, wait_ms=args.wait_ms, retries=args.retries, nav_timeout_ms=args.nav_timeout_ms)
            for row in items:
                row["collected_at_iso"] = timestamp
            collected.extend(items)

        summary_counts = {}
        for row in collected:
            summary_counts[row["publisher"]] = summary_counts.get(row["publisher"], 0) + 1
        for publisher, count in sorted(summary_counts.items()):
            print(f"{publisher}: {count}")

        if args.out_csv:
            with open(args.out_csv, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["publisher", "source", "source_url", "rank", "headline", "link", "collected_at_iso"],
                )
                writer.writeheader()
                writer.writerows(collected)
            print(f"Saved CSV: {args.out_csv} ({len(collected)} rows)")

        if args.out_json:
            with open(args.out_json, "w", encoding="utf-8") as handle:
                json.dump(collected, handle, ensure_ascii=False, indent=2)
            print(f"Saved JSON: {args.out_json} ({len(collected)} items)")

        if args.out_html:
            with open(args.out_html, "w", encoding="utf-8") as handle:
                handle.write(render_html(collected))
            print(f"Saved HTML: {args.out_html}")

        context.close()
        browser.close()
        if chrome_context is not None:
            chrome_context.close()
        if chrome_browser is not None:
            chrome_browser.close()


if __name__ == "__main__":
    main()
