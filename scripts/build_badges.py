"""Build the Socials and Tech Stack badge rows from tech-stack.json.

Every badge is drawn as a local SVG in assets/ so a row can be stretched to the
full README width with no gaps. shields.io (flat-square) is only asked for each
label's text width and logo; the badge itself is redrawn at SIZE below.

- Socials: one row, every tag the same width, linked.
- Tech Stack: one row per group; spare width is shared equally between the
  badges of a row. A group too long for one line is split into several lines,
  each filling the width on its own.

Nothing is written unless every badge was fetched and parsed, so a shields.io
outage keeps the last good badges instead of breaking the page.
"""

import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tech-stack.json"
README = ROOT / "README.md"
ASSETS = ROOT / "assets"

# Badge geometry. shields.io measures text at 11px; FONT scales that up.
FONT = 13      # text size in px
HEIGHT = 26    # bar height
LOGO = 16      # logo square
PAD = 6        # space left of the content and right of it
GAP = 5        # space between logo and text
SCALE = FONT / 11


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def shields_url(b):
    label = urllib.parse.quote(b["name"].replace("-", "--").replace("_", "__"), safe="")
    q = "style=flat-square"
    if b.get("logo"):
        q += f"&logo={urllib.parse.quote(b['logo'], safe='')}&logoColor={b.get('logoColor', 'white')}"
    return f"https://img.shields.io/badge/{label}-{b['color']}?{q}"


def fetch(url):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "profile-readme-build"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode()
        except Exception as e:
            print(f"retry {attempt + 1} for {url}: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise SystemExit(f"could not fetch {url}")


def measure(b):
    svg = fetch(shields_url(b))
    col = re.search(r'<rect x="0" width="[0-9.]+" height="20" fill="(#[0-9a-fA-F]+)"', svg)
    t = re.search(r'<text x="\d+" y="140" textLength="(\d+)" transform="scale\(\.1\)"(?: fill="(#[0-9a-f]+)")?>([^<]+)</text>', svg)
    if not (col and t):
        raise SystemExit(f"unexpected badge markup for {b['name']}")
    img = b.get("logoImage")
    if b.get("logo"):
        m = re.search(r'<image [^>]*href="([^"]+)"', svg)
        if not m:
            raise SystemExit(f"logo '{b['logo']}' did not render for {b['name']}")
        img = m.group(1)
    tl = int(t.group(1)) / 10 * SCALE
    w = PAD * 2 + tl + (LOGO + GAP if img else 0)
    return dict(name=b["name"], href=b.get("href"), w=w, col=col.group(1), img=img, tl=tl,
                fill=t.group(2) or "#fff", text=t.group(3))


def fit(widths, total):
    """Stretch widths to sum exactly to total, sharing the spare space equally."""
    extra = (total - sum(widths)) / len(widths)
    raw = [w + extra for w in widths]
    out = [int(x) for x in raw]
    for k in sorted(range(len(raw)), key=lambda k: raw[k] - out[k], reverse=True)[: total - sum(out)]:
        out[k] += 1
    return out


def draw(i, W):
    cw = LOGO + GAP + i["tl"] if i["img"] else i["tl"]
    x0 = (W - cw) / 2
    tx = x0 + LOGO + GAP + i["tl"] / 2 if i["img"] else W / 2
    ty = HEIGHT / 2 + 4 * SCALE
    im = (f'<image x="{x0:.1f}" y="{(HEIGHT - LOGO) / 2:.1f}" width="{LOGO}" height="{LOGO}" href="{i["img"]}"/>'
          if i["img"] else "")
    fa = "" if i["fill"] == "#fff" else f' fill="{i["fill"]}"'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{HEIGHT}" role="img" aria-label="{i["text"]}"><title>{i["text"]}</title>'
            f'<rect width="{W}" height="{HEIGHT}" fill="{i["col"]}" shape-rendering="crispEdges"/>'
            f'<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" text-rendering="geometricPrecision" font-size="{FONT * 10}">{im}'
            f'<text x="{tx * 10:.0f}" y="{ty * 10:.0f}" textLength="{i["tl"] * 10:.0f}" transform="scale(.1)"{fa}>{i["text"]}</text></g></svg>')


def row(line, widths, prefix, files):
    cells = []
    for i, W in zip(line, widths):
        svg = draw(i, W)
        # GitHub serves README images with a 5 minute cache, so a badge that
        # changes keeps its old look for a while under the same name. A content
        # hash in the name makes every change a new file.
        fn = f"assets/{prefix}-{slug(i['name'])}-{hashlib.sha1(svg.encode()).hexdigest()[:8]}.svg"
        files[fn] = svg
        img = f'<img src="{fn}" width="{W}" alt="{html.escape(i["name"])}">'
        cells.append(f'<a href="{i["href"]}">{img}</a>' if i["href"] else img)
    return "<p>" + "&#8203;".join(cells) + "</p>"


def replace_between(text, name, body):
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    if start not in text or end not in text:
        raise SystemExit(f"{name} markers missing from README.md")
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    return head + start + "\n\n" + body + "\n\n" + end + tail


def main():
    data = json.loads(DATA.read_text())
    total = data["width"]
    files = {}

    socials = [measure(b) for b in data["socials"]]
    n = len(socials)
    social_row = row(socials, [total // n + (1 if k >= n - total % n else 0) for k in range(n)], "social", files)

    parts = []
    for g in data["groups"]:
        if not g["badges"]:
            continue
        info = [measure(b) for b in g["badges"]]
        lines, cur = [], []
        for i in info:
            if cur and sum(x["w"] for x in cur) + i["w"] > total:
                lines.append(cur)
                cur = []
            cur.append(i)
        lines.append(cur)
        rows = [row(line, fit([x["w"] for x in line], total), "tech", files) for line in lines]
        parts.append(f"**{g['group']}**\n\n" + "\n\n".join(rows))

    readme = README.read_text()
    readme = replace_between(readme, "socials", social_row)
    readme = replace_between(readme, "tech-stack", "\n\n".join(parts))
    README.write_text(readme)

    for p in list(ASSETS.glob("tech-*.svg")) + list(ASSETS.glob("social-*.svg")):
        if f"assets/{p.name}" not in files:
            p.unlink()
            print(f"removed {p.name}")
    for fn, svg in files.items():
        path = ROOT / fn
        if not path.exists() or path.read_text() != svg:
            path.write_text(svg)
            print(f"wrote {fn}")


if __name__ == "__main__":
    main()
