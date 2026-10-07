#!/usr/bin/env python3
"""Search public GitHub code for distinctive HanHua translation phrases.

Set CANONICAL_REPO to owner/repository. Set GITHUB_TOKEN in CI for API access.
Phrases are read from the HANHUA_PHRASES environment variable (one per line),
falling back to a local phrases file when the variable is unset.
This is a provenance alert, not an automatic takedown system.
"""
from __future__ import annotations
import json, os, pathlib, sys, urllib.parse, urllib.request, urllib.error

ROOT = pathlib.Path(__file__).resolve().parent
repo = os.environ.get("CANONICAL_REPO", "").strip().lower()
token = os.environ.get("GITHUB_TOKEN", "").strip()
phrases_env = os.environ.get("HANHUA_PHRASES", "").strip()
if phrases_env:
    phrases = [x.strip() for x in phrases_env.splitlines() if x.strip() and not x.lstrip().startswith("#")]
else:
    phrases_file = pathlib.Path(os.environ.get("PHRASES_FILE", str(ROOT / "monitor_phrases.txt")))
    phrases = [x.strip() for x in phrases_file.read_text(encoding="utf-8-sig").splitlines() if x.strip() and not x.lstrip().startswith("#")]
headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "hanhua-provenance-monitor"}
if token:
    headers["Authorization"] = f"Bearer {token}"

results = []
for phrase in phrases:
    q = urllib.parse.urlencode({"q": f'"{phrase}" in:file', "per_page": "100"})
    req = urllib.request.Request(f"https://api.github.com/search/code?{q}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        results.append({"phrase": phrase, "error": f"HTTP {e.code}: {body}"})
        continue
    matches = []
    for item in data.get("items", []):
        full_name = str(item.get("repository", {}).get("full_name", ""))
        if repo and full_name.lower() == repo:
            continue
        matches.append({"repository": full_name, "path": item.get("path", ""), "url": item.get("html_url", "")})
    results.append({"phrase": phrase, "total_count": data.get("total_count", 0), "external_matches": matches})

suspicious = any(x.get("external_matches") for x in results)
report = {"canonical_repo": repo, "suspicious": suspicious, "results": results}
path = pathlib.Path(os.environ.get("REPORT_FILE", "monitor_report.json"))
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
md = ["# HanHua 转载监测报告", "", f"Canonical repository: `{repo or '(not configured)'}`", ""]
for x in results:
    md.append(f"## {x['phrase']}")
    if "error" in x:
        md.append(f"- 查询失败：`{x['error']}`")
    elif x.get("external_matches"):
        md.append(f"- 发现 {len(x['external_matches'])} 个非主仓库匹配：")
        for m in x["external_matches"]:
            md.append(f"  - [{m['repository']}:{m['path']}]({m['url']})")
    else:
        md.append("- 未发现非主仓库匹配。")
path.with_suffix(".md").write_text("\n".join(md) + "\n", encoding="utf-8")
out = os.environ.get("GITHUB_OUTPUT")
if out:
    with open(out, "a", encoding="utf-8") as f:
        f.write(f"suspicious={'true' if suspicious else 'false'}\n")
print(json.dumps(report, ensure_ascii=False, indent=2))
