#!/usr/bin/env python3
"""Monitor public GitHub code; never publish the configured search phrases."""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
QUERY_INTERVAL_SECONDS = 6.2  # GitHub code search: at most 10 requests/minute.


def load_phrases() -> list[str]:
    value = os.environ.get("HANHUA_PHRASES", "").strip()
    if not value:
        source = pathlib.Path(os.environ.get("PHRASES_FILE", str(ROOT / "monitor_phrases.txt")))
        if not source.is_file():
            raise ValueError("未配置 HANHUA_PHRASES，且没有本地监测词文件。")
        value = source.read_text(encoding="utf-8-sig")
    phrases = list(dict.fromkeys(line.strip() for line in value.splitlines()
                                if line.strip() and not line.lstrip().startswith("#")))
    if not phrases:
        raise ValueError("监测词为空，无法进行查询。")
    if any(len(phrase) > 240 for phrase in phrases):
        raise ValueError("监测词过长，请使用不超过 240 字符的短句。")
    return phrases


def search(phrase: str, repo: str, headers: dict[str, str]) -> dict:
    query = f'"{phrase}" in:file -repo:{repo}'
    params = urllib.parse.urlencode({"q": query, "per_page": 100})
    request = urllib.request.Request(f"https://api.github.com/search/code?{params}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as error:
        return {"status": "failed", "error": f"HTTP {error.code}"}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"status": "failed", "error": "网络连接失败或超时"}
    except (ValueError, UnicodeError):
        return {"status": "failed", "error": "接口未返回有效 JSON"}

    if (not isinstance(data, dict) or not isinstance(data.get("items"), list)
            or not isinstance(data.get("total_count"), int)):
        return {"status": "failed", "error": "接口响应结构不完整"}

    matches = []
    for item in data["items"]:
        if not isinstance(item, dict):
            return {"status": "failed", "error": "接口匹配条目无效"}
        repository = item.get("repository") or {}
        if not isinstance(repository, dict):
            return {"status": "failed", "error": "接口仓库条目无效"}
        full_name = str(repository.get("full_name", ""))
        if full_name.lower() == repo:
            continue
        url = str(item.get("html_url", ""))
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "github.com":
            return {"status": "failed", "error": "接口匹配链接无效"}
        matches.append({"repository": full_name, "path": str(item.get("path", "")), "url": url})

    incomplete = bool(data.get("incomplete_results")) or data["total_count"] > len(data["items"])
    result = {"status": "partial" if incomplete else "ok", "total_count": data["total_count"],
              "external_matches": matches}
    if incomplete:
        result["error"] = "搜索结果不完整，不能确认全部匹配。"
    return result


def write_report(report: dict) -> None:
    path = pathlib.Path(os.environ.get("REPORT_FILE", "monitor_report.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    labels = {"ok": "查询完成", "partial": "查询不完整", "failed": "查询失败"}
    lines = ["# HanHua 转载监测报告", "", f"状态：{labels[report['status']]}",
             f"主仓库：`{report['canonical_repo']}`", "",
             "匹配是待核查线索，不代表已经确认侵权。监测词原文不公开。", ""]
    for error in report.get("errors", []):
        lines.extend([f"- {error}", ""])
    for result in report["results"]:
        lines.append(f"## 监测词 {result['phrase_id']}")
        if result.get("error"):
            lines.append(f"- {result['error']}")
        matches = result.get("external_matches", [])
        if matches:
            for match in matches:
                # Only publish links, not search terms or potentially matching snippets.
                url = urllib.parse.quote(match["url"], safe=":/%?#=&._-")
                lines.append(f"- [查看匹配文件](<{url}>)")
        elif result["status"] == "ok":
            lines.append("- 本次查询未发现非主仓库匹配。")
        lines.append("")
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"suspicious={'true' if report['suspicious'] else 'false'}\n")
            stream.write(f"status={report['status']}\n")
    print(f"监测状态：{labels[report['status']]}；完成 {report['completed_queries']}/{report['phrase_count']} 个查询；"
          f"存在外部匹配：{'是' if report['suspicious'] else '否'}。")


def main() -> int:
    repo = os.environ.get("CANONICAL_REPO", "").strip().lower()
    report = {"canonical_repo": repo if re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", repo) else "(未配置)",
              "status": "failed", "suspicious": False, "phrase_count": 0,
              "completed_queries": 0, "results": [], "errors": []}
    try:
        if report["canonical_repo"] == "(未配置)":
            raise ValueError("CANONICAL_REPO 必须为 owner/repository。")
        phrases = load_phrases()
    except (ValueError, OSError, UnicodeError):
        report["errors"].append("配置无效：请检查 CANONICAL_REPO 和 HANHUA_PHRASES；本地词文件须为 UTF-8。")
        write_report(report)
        return 1

    report["phrase_count"] = len(phrases)
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "hanhua-provenance-monitor"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_query = None
    for index, phrase in enumerate(phrases, 1):
        if last_query is not None:
            time.sleep(max(0.0, QUERY_INTERVAL_SECONDS - (time.monotonic() - last_query)))
        last_query = time.monotonic()
        result = search(phrase, repo, headers)
        result["phrase_id"] = f"{index:03d}"
        report["results"].append(result)
        if result["status"] == "ok":
            report["completed_queries"] += 1
        if result.get("external_matches"):
            report["suspicious"] = True
        # Authorization or rate-limit failure won't improve by sending more queries now.
        if result.get("error") in {"HTTP 401", "HTTP 403", "HTTP 429"}:
            break

    if report["completed_queries"] == len(phrases):
        report["status"] = "ok"
    elif report["completed_queries"] or report["suspicious"]:
        report["status"] = "partial"
    write_report(report)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
