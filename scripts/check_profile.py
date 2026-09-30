"""Check that the README shows what the GitHub account really has.

Layout checks (a failure here means the page itself is broken):
- every local image the README points at exists
- every badge row adds up to the full width

Card checks (compared with the GitHub API):
- profile summary shows the real number of public repos
- "Top Languages by Repo" lists the main languages of the public repos

Writes to $GITHUB_OUTPUT:
  heal=true   a card is out of date, so the card workflows should run again
  stale=true  a wrong card has not changed for over STALE_HOURS, so something
              upstream is stuck and the run should fail (GitHub emails on that)
Exits 1 on a broken layout.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
OWNER = os.environ.get("PROFILE_OWNER", "headless-start")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
STALE_HOURS = 24


def api(path):
    req = urllib.request.Request(f"https://api.github.com/{path}", headers={"Accept": "application/vnd.github+json"})
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def texts(path):
    return [t.strip() for t in re.findall(r"<text[^>]*>([^<]+)</text>", (ROOT / path).read_text()) if t.strip()]


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

    for msg in broken:
        print(f"BROKEN: {msg}")
    stale = False
    for path, msg in wrong:
        hours = age_hours(path)
        print(f"OUT OF DATE: {msg} (card last changed {hours:.0f}h ago)")
        stale |= hours > STALE_HOURS
    if not broken and not wrong:
        print("all cards and badge rows match the account")

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"heal={'true' if wrong else 'false'}\nstale={'true' if stale else 'false'}\n")
    sys.exit(1 if broken else 0)


if __name__ == "__main__":
    main()
