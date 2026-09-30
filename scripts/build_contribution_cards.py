"""Draw the streak card and the activity graph from GitHub's own data.

Both cards used to be fetched from free public card services. Those can go
away without notice (the activity graph service did, in August 2026, and the
card silently stayed on old data), so they are now built here from the
contribution calendar in the GitHub GraphQL API.

- assets/streak.svg: total contributions, current streak, longest streak.
  Same design as before: scripts/templates/streak.svg with the values swapped.
  Rules follow the old card: today may still be empty without breaking the
  current streak; a tie for the longest streak keeps the earliest one.
- assets/activity-graph.svg: contributions per day for the last 31 days.

Nothing is written unless the API answered with a sane calendar, so an outage
keeps the last good cards.
"""

import datetime as dt
import json
import math
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNER = os.environ.get("PROFILE_OWNER", "headless-start")
NAME = os.environ.get("PROFILE_NAME", "Ayush Tiwari")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
GRAPH_DAYS = 31


def gql(query, **variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=body,
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.load(r)
    if out.get("errors"):
        raise RuntimeError(out["errors"])
    return out["data"]


def calendar():
    created = gql("query($l:String!){user(login:$l){createdAt}}", l=OWNER)["user"]["createdAt"]
    start = dt.datetime.fromisoformat(created.replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    days = {}
    # The API allows at most one year per query, so walk the account's life
    # in yearly steps. Days on a step boundary come back twice; the dict
    # keeps one.
    f = start
    while f < now:
        t = min(f + dt.timedelta(days=365), now)
        d = gql("""query($l:String!,$f:DateTime!,$t:DateTime!){user(login:$l){contributionsCollection(from:$f,to:$t){
                   contributionCalendar{weeks{contributionDays{date contributionCount}}}}}}""",
                l=OWNER, f=f.isoformat(), t=t.isoformat())
        for w in d["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for x in w["contributionDays"]:
                days[dt.date.fromisoformat(x["date"])] = x["contributionCount"]
        f = t
    return dict(sorted(days.items()))


def fmt(day, today):
    return f"{day:%b} {day.day}" + ("" if day.year == today.year else f", {day.year}")


def span(a, b, today):
    return fmt(a, today) if a == b else f"{fmt(a, today)} - {fmt(b, today)}"


def streak_values(days):
    today = max(days)
    active = [d for d, n in days.items() if n]
    first = min(active)
    total = sum(days.values())

    longest, lstart, lend = 0, None, None
    run, rstart = 0, None
    for d, n in days.items():
        if n:
            run, rstart = run + 1, rstart or d
            if run > longest:
                longest, lstart, lend = run, rstart, d
        else:
            run, rstart = 0, None

    end = today if days[today] else today - dt.timedelta(days=1)
    cur, d = 0, end
    while days.get(d, 0):
        cur, d = cur + 1, d - dt.timedelta(days=1)
    cur_range = span(d + dt.timedelta(days=1), end, today) if cur else fmt(today, today)

    return [f"{total:,}", "Total Contributions", f"{fmt(first, today) if first.year == today.year else f'{first:%b} {first.day}, {first.year}'} - Present",
            "Current Streak", cur_range, str(cur), str(longest), "Longest Streak",
            span(lstart, lend, today) if longest else fmt(today, today)]


def streak_svg(values):
    tpl = (ROOT / "scripts/templates/streak.svg").read_text()
    it = iter(values)
    out, n = re.subn(r"(<text[^>]*>)(\s*)(.*?)(\s*)(</text>)",
                     lambda m: m.group(1) + m.group(2) + next(it) + m.group(4) + m.group(5), tpl, flags=re.S)
    if n != len(values):
        raise SystemExit(f"streak template has {n} text slots, expected {len(values)}")
    return out


def smooth_path(pts):
    """Catmull-Rom through the points, as cubic Beziers."""
    d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for i in range(len(pts) - 1):
        p0, p1, p2, p3 = pts[max(i - 1, 0)], pts[i], pts[i + 1], pts[min(i + 2, len(pts) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        # keep the curve from dipping below the zero line between two points
        c1 = (c1[0], min(c1[1], max(p1[1], p2[1])))
        c2 = (c2[0], min(c2[1], max(p1[1], p2[1])))
        d += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"
    return d


def graph_svg(days):
    W, H = 1200, 420
    left, right, top, bottom = 90, 1150, 80, 350
    last = list(days.items())[-GRAPH_DAYS:]
    peak = max(n for _, n in last)
    step = next(s for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000) if peak / s <= 11)
    ymax = max(step, math.ceil(peak / step) * step)
    xs = [left + i * (right - left) / (len(last) - 1) for i in range(len(last))]
    ys = [bottom - n / ymax * (bottom - top) for _, n in last]
    pts = list(zip(xs, ys))
    c, grid = "#7C7BF7", "#7C7BF733"
    parts = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" fill="none" xmlns="http://www.w3.org/2000/svg">',
             f'<rect width="{W}" height="{H}" fill="#1a1b27"/>',
             '<style>text{font-family:"Segoe UI",Ubuntu,sans-serif;font-weight:600;fill:%s}</style>' % c,
             f'<text x="{W / 2}" y="40" text-anchor="middle" font-size="20">{NAME}\'s Contribution Graph</text>']
    for v in range(0, ymax + 1, step):
        y = bottom - v / ymax * (bottom - top)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="{grid}" stroke-dasharray="2 2"/>')
        parts.append(f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" font-size="12">{v}</text>')
    for x, (d, _) in zip(xs, last):
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" stroke="{grid}" stroke-dasharray="2 2"/>')
        parts.append(f'<text x="{x:.1f}" y="{bottom + 20}" text-anchor="middle" font-size="12">{d.day}</text>')
    line = smooth_path(pts)
    parts.append(f'<path d="{line} L{xs[-1]:.1f},{bottom} L{xs[0]:.1f},{bottom} Z" fill="{c}" fill-opacity="0.15"/>')
    parts.append(f'<path d="{line}" stroke="{c}" stroke-width="4" fill="none"/>')
    for x, y in pts:
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#ffffff"/>')
    parts.append(f'<text x="{(left + right) / 2}" y="{bottom + 50}" text-anchor="middle" font-size="13">Days</text>')
    parts.append(f'<text x="30" y="{(top + bottom) / 2}" text-anchor="middle" font-size="13" transform="rotate(-90 30 {(top + bottom) / 2})">Contributions</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    try:
        days = calendar()
    except Exception as e:
        print(f"keep streak.svg and activity-graph.svg - calendar unavailable: {e}")
        return
    if len(days) < GRAPH_DAYS or not any(days.values()):
        print(f"keep streak.svg and activity-graph.svg - calendar looks wrong ({len(days)} days)")
        return
    values = streak_values(days)
    print("streak:", " | ".join(values))
    for name, svg in (("streak.svg", streak_svg(values)), ("activity-graph.svg", graph_svg(days))):
        path = ROOT / "assets" / name
        if not path.exists() or path.read_text() != svg:
            path.write_text(svg)
            print(f"update {name}")


if __name__ == "__main__":
    if not TOKEN:
        sys.exit("GITHUB_TOKEN is needed for the GraphQL API")
    main()
