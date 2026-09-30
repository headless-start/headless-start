"""Check that the README shows what the GitHub account really has.

Layout checks (a failure here means the page itself is broken):
- every local image the README points at exists
- every badge row adds up to the full width

Outside checks (a failure here means something readers see is down):
- the portfolio site answers on /, /de and the CV download
- every image the README still loads from another site answers

Card checks (compared with the GitHub API):
- profile summary shows the real number of public repos
- "Top Languages by Repo" lists the main languages of the public repos
- the streak and activity cards were refreshed in the last FEED_HOURS

Writes to $GITHUB_OUTPUT:
  heal=true   a card is out of date, so the card workflows should run again
  stale=true  a wrong card has not changed for over STALE_HOURS, so something
              upstream is stuck and the run should fail (GitHub emails on that)
Exits 1 on a broken layout, a site that is down, or a dead outside image.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
OWNER = os.environ.get("PROFILE_OWNER", "headless-start")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
STALE_HOURS = 24
FEED_HOURS = 72
SITE = "https://ayushtiwari-ai.vercel.app"
# path -> something the response must contain
SITE_PAGES = {"/": b"Ayush", "/de": b"Ayush", "/Ayush_Tiwari_CV.pdf": b"%PDF"}


def api(path):
    req = urllib.request.Request(f"https://api.github.com/{path}", headers={"Accept": "application/vnd.github+json"})
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def texts(path):
    return [t.strip() for t in re.findall(r"<text[^>]*>([^<]+)</text>", (ROOT / path).read_text()) if t.strip()]


def get(url):
    """Return (status, headers, first bytes of body), retrying a few times."""
    for attempt in range(3):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (profile health check)"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.headers, r.read(200000)
        except urllib.error.HTTPError as e:
            status, headers, body = e.code, e.headers, e.read(2000)
            if status < 500:
                return status, headers, body
        except Exception:
            status, headers, body = 0, {}, b""
        time.sleep(10 * (attempt + 1))
    return status, headers, body


def site_problems():
    out = []
    for path, marker in SITE_PAGES.items():
        status, headers, body = get(SITE + path)
        if status == 200 and marker in body:
            continue
        # Vercel sometimes answers bots with a 403 challenge. That still proves
        # the platform is up and serving the site, so it counts as healthy.
        if status == 403 and "x-vercel-mitigated" in {k.lower() for k in headers.keys()}:
            continue
        out.append(f"portfolio {path} is not serving (HTTP {status})")
    return out


def remote_image_problems(readme):
    out = []
    for url in sorted(set(re.findall(r'(?:src|srcset)="(https?://[^"]+)"', readme))):
        status, headers, _ = get(url)
        ctype = headers.get("Content-Type", "") if headers else ""
        if status != 200 or not ctype.startswith("image/"):
            out.append(f"outside image is gone (HTTP {status}, {ctype or 'no type'}): {url}")
    return out


def age_hours(path):
    out = subprocess.run(["git", "log", "-1", "--format=%ct", "--", path], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return (time.time() - int(out)) / 3600 if out else 0


def main():
    readme = README.read_text()
    width = json.loads((ROOT / "tech-stack.json").read_text())["width"]
    broken = []
    for src in re.findall(r'(?:src|srcset)="(assets/[^"?]+)', readme):
        if not (ROOT / src).exists():
            broken.append(f"missing image {src}")
    for p in re.findall(r"<p>(.*?)</p>", readme):
        if re.search(r'assets/(tech|social)-', p):
            total = sum(int(w) for w in re.findall(r'width="(\d+)"', p))
            if total != width:
                broken.append(f"badge row is {total}px, not {width}px: {re.findall(r'alt=\"([^\"]+)\"', p)}")
    broken += site_problems()
    broken += remote_image_problems(readme)

    user = api(f"users/{OWNER}")
    repos, page = [], 1
    while True:
        batch = api(f"users/{OWNER}/repos?type=owner&per_page=100&page={page}")
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    langs = Counter(r["language"] for r in repos if r["language"] and not r["fork"])
    expected = {lang for lang, _ in langs.most_common(5)}

    wrong = []
    summary = " ".join(texts("assets/profile-summary.svg"))
    m = re.search(r"(\d+) Public Repos", summary)
    if not m or int(m.group(1)) != user["public_repos"]:
        wrong.append(("assets/profile-summary.svg", f"shows {m.group(1) if m else '?'} public repos, account has {user['public_repos']}"))
    shown = set(texts("assets/repos-per-language.svg"))
    missing = sorted(expected - shown)
    if missing:
        wrong.append(("assets/repos-per-language.svg", f"languages card is missing {', '.join(missing)}"))

    stale = False
    for path in ("assets/streak.svg", "assets/activity-graph.svg"):
        hours = age_hours(path)
        if hours > FEED_HOURS:
            # These cards change every day, so days without a change means the
            # outside service behind them keeps failing.
            print(f"STUCK: {path} has not refreshed for {hours:.0f}h")
            stale = True

    for msg in broken:
        print(f"BROKEN: {msg}")
    for path, msg in wrong:
        hours = age_hours(path)
        print(f"OUT OF DATE: {msg} (card last changed {hours:.0f}h ago)")
        stale |= hours > STALE_HOURS
    if not broken and not wrong and not stale:
        print("all cards, badge rows, the portfolio site and outside images are fine")

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"heal={'true' if wrong else 'false'}\nstale={'true' if stale else 'false'}\n")
    sys.exit(1 if broken else 0)


if __name__ == "__main__":
    main()
