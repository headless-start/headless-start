"""Build the Tech Stack section from tech-stack.json.

Each badge is rendered by shields.io (flat-square) to get its exact text width
and logo, then redrawn as a local SVG in assets/ so every row can be stretched
to the full README width with no gaps. Rows that would not fit in one line are
split into several lines, each filling the width on its own.

Nothing is written unless every badge was fetched and parsed, so a shields.io
outage keeps the last good badges instead of breaking the section.
"""

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
START = "<!-- tech-stack:start -->"
END = "<!-- tech-stack:end -->"


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def shields_url(b):
    label = urllib.parse.quote(b["name"].replace("-", "--").replace("_", "__"), safe="")
    q = "style=flat-square"
    if b.get("logo"):
        q += f"&logo={b['logo']}&logoColor={b.get('logoColor', 'white')}"
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
    w = re.search(r'<svg[^>]*?width="([0-9.]+)"', svg)
    col = re.search(r'<rect x="0" width="[0-9.]+" height="20" fill="(#[0-9a-fA-F]+)"', svg)
    t = re.search(r'<text x="\d+" y="140" textLength="(\d+)" transform="scale\(\.1\)"(?: fill="(#[0-9a-f]+)")?>([^<]+)</text>', svg)
    if not (w and col and t):
        raise SystemExit(f"unexpected badge markup for {b['name']}")
    img = re.search(r'<image [^>]*href="([^"]+)"', svg)
    if b.get("logo") and not img:
        raise SystemExit(f"logo '{b['logo']}' did not render for {b['name']}")
    return dict(name=b["name"], w=float(w.group(1)), col=col.group(1), img=img.group(1) if img else None,
                tl=int(t.group(1)) / 10, fill=t.group(2) or "#fff", text=t.group(3))


def fit(widths, total):
    """Stretch widths to sum exactly to total, sharing the spare space equally."""
    extra = (total - sum(widths)) / len(widths)
    raw = [w + extra for w in widths]
    out = [int(x) for x in raw]
    for k in sorted(range(len(raw)), key=lambda k: raw[k] - out[k], reverse=True)[: total - sum(out)]:
        out[k] += 1
    return out


def draw(i, W):
    cw = 14 + 4 + i["tl"] if i["img"] else i["tl"]
    x0 = (W - cw) / 2
    tx = x0 + 18 + i["tl"] / 2 if i["img"] else W / 2
    im = f'<image x="{x0:.1f}" y="3" width="14" height="14" href="{i["img"]}"/>' if i["img"] else ""
    fa = "" if i["fill"] == "#fff" else f' fill="{i["fill"]}"'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="20" role="img" aria-label="{i["text"]}"><title>{i["text"]}</title>'
            f'<rect width="{W}" height="20" fill="{i["col"]}" shape-rendering="crispEdges"/>'
            f'<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" text-rendering="geometricPrecision" font-size="110">{im}'
            f'<text x="{tx * 10:.0f}" y="140" textLength="{i["tl"] * 10:.0f}" transform="scale(.1)"{fa}>{i["text"]}</text></g></svg>')


def main():
    data = json.loads(DATA.read_text())
    total = data["width"]
    files, parts = {}, []
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
        rows = []
        for line in lines:
            cells = []
            for i, W in zip(line, fit([x["w"] for x in line], total)):
                fn = f"assets/tech-{slug(i['name'])}.svg"
                files[fn] = draw(i, W)
                cells.append(f'<img src="{fn}" width="{W}" alt="{html.escape(i["name"])}">')
            rows.append("<p>" + "&#8203;".join(cells) + "</p>")
        parts.append(f"**{g['group']}**\n\n" + "\n\n".join(rows))

    readme = README.read_text()
    if START not in readme or END not in readme:
        raise SystemExit("tech-stack markers missing from README.md")
    head, rest = readme.split(START, 1)
    _, tail = rest.split(END, 1)
    README.write_text(head + START + "\n\n" + "\n\n".join(parts) + "\n\n" + END + tail)

    for p in ASSETS.glob("tech-*.svg"):
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
