"""Add tech-stack badges for anything new in the public repos.

Looks at every public, non-fork repo of the owner: its languages (any language
that is the repo's main one or at least 10% of its code) and its dependency
files (requirements*.txt, pyproject.toml, package.json, Cargo.toml). Anything
that matches an entry in the catalog of tech-stack.json and has never been
seen before is appended to that entry's group.

A badge is only ever added once. Its name then goes into "seen", so a badge
removed by hand from tech-stack.json stays removed.
"""

import base64
import json
import os
import re
import sys
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tech-stack.json"
OWNER = os.environ.get("PROFILE_OWNER", "headless-start")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
MANIFESTS = re.compile(r"(^|/)(requirements[^/]*\.txt|pyproject\.toml|package\.json|Cargo\.toml)$")
SKIP_DIRS = re.compile(r"(^|/)(node_modules|vendor|\.venv|venv|site-packages|dist|build|target)/")


def api(path):
    req = urllib.request.Request(f"https://api.github.com/{path}", headers={"Accept": "application/vnd.github+json"})
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def norm(name):
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def py_req(text):
    out = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if m:
            out.add("py:" + norm(m.group(1)))
    return out


def pyproject(text):
    d = tomllib.loads(text)
    deps = list(d.get("project", {}).get("dependencies", []))
    for extra in d.get("project", {}).get("optional-dependencies", {}).values():
        deps += extra
    deps += list(d.get("tool", {}).get("poetry", {}).get("dependencies", {}).keys())
    return py_req("\n".join(deps))


def package_json(text):
    d = json.loads(text)
    return {"npm:" + k.lower() for sec in ("dependencies", "devDependencies") for k in d.get(sec, {})}


def cargo(text):
    d = tomllib.loads(text)
    keys = set(d.get("dependencies", {})) | set(d.get("workspace", {}).get("dependencies", {}))
    return {"cargo:" + norm(k) for k in keys}


PARSERS = {"pyproject.toml": pyproject, "package.json": package_json, "Cargo.toml": cargo}


def repo_signals(repo):
    name = repo["name"]
    found = set()
    langs = api(f"repos/{OWNER}/{name}/languages")
    total = sum(langs.values()) or 1
    for lang, size in langs.items():
        if lang == repo.get("language") or size / total >= 0.10:
            found.add("lang:" + lang.lower())
    try:
        tree = api(f"repos/{OWNER}/{name}/git/trees/{repo['default_branch']}?recursive=1")["tree"]
    except Exception:
        return found
    for item in tree:
        path = item["path"]
        if item["type"] != "blob" or not MANIFESTS.search(path) or SKIP_DIRS.search(path):
            continue
        base = path.rsplit("/", 1)[-1]
        try:
            blob = api(f"repos/{OWNER}/{name}/git/blobs/{item['sha']}")
            text = base64.b64decode(blob["content"]).decode("utf-8", "replace")
            found |= PARSERS.get(base, py_req)(text)
        except Exception as e:
            print(f"skip {name}/{path}: {e}", file=sys.stderr)
    return found


def main():
    data = json.loads(DATA.read_text())
    repos, page = [], 1
    while True:
        batch = api(f"users/{OWNER}/repos?type=owner&per_page=100&page={page}")
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    signals = set()
    for repo in repos:
        if repo["fork"] or repo["private"] or repo["archived"] or repo["name"] == OWNER:
            continue
        signals |= repo_signals(repo)

    is_lang = {e["name"] for e in data["catalog"] if any(m.startswith("lang:") for m in e["match"])}
    present = {b["name"] for g in data["groups"] for b in g["badges"]}
    seen = set(data.get("seen", [])) | present
    added = []
    for entry in data["catalog"]:
        name = entry["name"]
        if name in seen or not signals & set(entry["match"]):
            continue
        badge = {k: entry[k] for k in ("name", "color", "logo", "logoColor") if k in entry}
        group = next((g for g in data["groups"] if g["group"] == entry["group"]), None)
        if group is None:
            group = {"group": entry["group"], "badges": []}
            data["groups"].append(group)
        if name in is_lang:
            # keep languages together at the front of their group
            pos = max((i + 1 for i, b in enumerate(group["badges"]) if b["name"] in is_lang), default=0)
            group["badges"].insert(pos, badge)
        else:
            group["badges"].append(badge)
        seen.add(name)
        added.append(f"{name} -> {entry['group']}")
    data["seen"] = sorted(seen)
    DATA.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print("added: " + (", ".join(added) if added else "nothing new"))


if __name__ == "__main__":
    main()
