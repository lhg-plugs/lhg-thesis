#!/usr/bin/env python3
"""lhg-thesis 引用审计：GB/T 7714 相关校验。

扫描目标目录：
- references.bib（BibTeX）：条目必填字段、key 重复
- chapters/*.md（或目录下所有 md）：[@key] / \\cite{key} 引用
  是否在 bib 中存在（幽灵引用）、bib 条目是否被引用（僵尸条目）
- references.md（如存在）：编号条目是否符合 GB/T 7714 著录格式（启发式）

用法：
    python3 cite_audit.py --target <论文目录> [--format json|text] [--fail-on blocker|warning|nit]

有 blocker 时以 exit code 2 退出。零第三方依赖。
规则文案均为本项目原创。
"""

import argparse
import json
import os
import re
import sys

VERSION = "1.0.0"
TOOL = "lhg-thesis/cite-audit"

CITE_RE = re.compile(r"\[@([A-Za-z0-9_:\-]+(?:\s*;\s*@[A-Za-z0-9_:\-]+)*)\]")
LATEX_CITE_RE = re.compile(r"\\cite\{([^}]+)\}")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".bak"}


class Finding:
    __slots__ = ("rule_id", "severity", "category", "title", "file", "line", "snippet", "detail")

    def __init__(self, rule_id, severity, category, title, file, line, snippet, detail):
        self.rule_id = rule_id
        self.severity = severity
        self.category = category
        self.title = title
        self.file = file
        self.line = line
        self.snippet = snippet
        self.detail = detail

    def to_dict(self):
        return {"rule_id": self.rule_id, "severity": self.severity,
                "category": self.category, "title": self.title,
                "file": self.file, "line": self.line,
                "snippet": self.snippet, "detail": self.detail}


RULES = []
_RULE_BY_ID = {}


def rule(rule_id, severity, category, title, detail):
    def deco(fn):
        r = {"id": rule_id, "severity": severity, "category": category,
             "title": title, "detail": detail}
        _RULE_BY_ID[rule_id] = r
        r["check"] = fn
        RULES.append(r)
        return fn
    return deco


def _hit(rule_id, path, line, snippet):
    rule = _RULE_BY_ID[rule_id]
    return Finding(rule["id"], rule["severity"], rule["category"], rule["title"],
                   path, line, snippet, rule["detail"])


# ---------------------------------------------------------------- BibTeX 解析

def parse_bibtex(text):
    """返回 (entries, dup_keys)。entry: {type, key, fields, line}。"""
    entries, seen, dups = [], {}, set()
    i, n = 0, len(text)
    while i < n:
        m = re.search(r"@(\w+)\s*\{", text[i:])
        if not m:
            break
        etype = m.group(1).lower()
        j = i + m.end()
        # key：到第一个顶层逗号
        depth, k = 0, j
        while k < n:
            ch = text[k]
            if ch == "{":
                depth += 1
            elif ch == "}":
                if depth == 0:
                    break
                depth -= 1
            elif ch == "," and depth == 0:
                break
            k += 1
        key = text[j:k].strip()
        # body：配平大括号
        depth, b = 1, k + 1
        while b < n and depth > 0:
            if text[b] == "{":
                depth += 1
            elif text[b] == "}":
                depth -= 1
            b += 1
        body = text[k + 1:b - 1]
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"[^\"]*\"|\S+)",
                              body):
            val = fm.group(2).strip()
            if val.startswith("{") and val.endswith("}"):
                val = val[1:-1]
            elif val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            fields[fm.group(1).lower()] = val.strip()
        line = text.count("\n", 0, i + m.start()) + 1
        if key in seen:
            dups.add(key)
        else:
            seen[key] = True
        entries.append({"type": etype, "key": key, "fields": fields, "line": line})
        i = b
    return entries, sorted(dups)


@rule("CITE-FMT-001", "blocker", "引用", "bib 条目缺必填字段",
      "author/year/title 三者缺一不可（期刊还建议 journal，专著建议 publisher）。"
      "补齐字段，补不到就换一篇能查到的文献，不许留空蒙混。")
def _r_fmt(ctx):
    for e in ctx["entries"]:
        f = e["fields"]
        missing = [k for k in ("author", "year", "title") if not f.get(k)]
        if missing:
            yield _hit("CITE-FMT-001", ctx["bib_path"], "L%d" % e["line"],
                       "@%s{%s 缺字段：%s" % (e["type"], e["key"], ",".join(missing)))


@rule("CITE-DUP-001", "warning", "引用", "bib 中 key 重复",
      "两个条目用了同一个 key，引用时会指向不明。合并为一条，key 全文唯一。")
def _r_dup(ctx):
    for key in ctx["dup_keys"]:
        yield _hit("CITE-DUP-001", ctx["bib_path"], "-",
                   "重复的 key：%s" % key)


@rule("CITE-KEY-001", "blocker", "引用", "幽灵引用：文中引用的 key 在 bib 中不存在",
      "正文 [@key] 或 \\cite{key} 指向了不存在的条目。二选一：补条目，或删引用。不许留着。")
def _r_key(ctx):
    keys = {e["key"] for e in ctx["entries"]}
    for path, lineno, key in ctx["citations"]:
        if key not in keys:
            yield _hit("CITE-KEY-001", path, "L%d" % lineno,
                       "引用了不存在的条目：%s" % key)


@rule("CITE-UNUSED-001", "warning", "引用", "僵尸条目：bib 中从未被正文引用",
      "条目在 bib 里但正文一次没引用。删掉，或在正文真正用它一次。")
def _r_unused(ctx):
    cited = {key for _, _, key in ctx["citations"]}
    for e in ctx["entries"]:
        if e["key"] not in cited:
            yield _hit("CITE-UNUSED-001", ctx["bib_path"], "L%d" % e["line"],
                       "从未被引用：@%s{%s" % (e["type"], e["key"]))


@rule("CITE-GB-001", "warning", "引用", "参考文献条目疑似不符合 GB/T 7714 著录格式",
      "启发式检查（条目应含年份、文献类型标识、结尾标点）。各校细则以学校模板为准，"
      "本规则只做提醒，不做硬拦截。")
def _r_gb(ctx):
    path = ctx.get("ref_md")
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().split("\n")
    except OSError:
        return
    for i, ln in enumerate(lines, start=1):
        m = re.match(r"\s*\[(\d+)\]\s*(.+)", ln)
        if not m:
            continue
        body = m.group(2)
        problems = []
        if not re.search(r"(19|20)\d{2}", body):
            problems.append("缺年份")
        if not re.search(r"\[(J|M|C|D|EB/OL|S|R|P)\]", body):
            problems.append("缺文献类型标识[J]/[M]/[D]等")
        if not re.search(r"[.。]$", body.strip()):
            problems.append("缺结尾标点")
        if problems:
            yield _hit("CITE-GB-001", path, "L%d" % i,
                       "[%s] %s：%s" % (m.group(1), "、".join(problems), body[:60]))


# ---------------------------------------------------------------- 主流程

def collect_md(target):
    out = []
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".md") and f.lower() != "readme.md":
                out.append(os.path.join(root, f))
    return sorted(out)


def find_citations(path):
    """返回 [(path, lineno, key)]。"""
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return out
    for i, ln in enumerate(text.split("\n"), start=1):
        for m in CITE_RE.finditer(ln):
            for key in m.group(1).split(";"):
                key = key.strip().lstrip("@")
                if key:
                    out.append((path, i, key))
        for m in LATEX_CITE_RE.finditer(ln):
            for key in m.group(1).split(","):
                key = key.strip()
                if key:
                    out.append((path, i, key))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=".")
    ap.add_argument("--format", choices=["json", "text"], default="text")
    ap.add_argument("--fail-on", choices=["blocker", "warning", "nit"], default="blocker")
    args = ap.parse_args()

    target = os.path.abspath(args.target)
    bib_path = os.path.join(target, "references.bib")
    entries, dup_keys = [], []
    if os.path.isfile(bib_path):
        try:
            with open(bib_path, encoding="utf-8") as fh:
                entries, dup_keys = parse_bibtex(fh.read())
        except OSError:
            pass

    ref_md = None
    for cand in (os.path.join(target, "references.md"),
                 os.path.join(target, "chapters", "references.md")):
        if os.path.isfile(cand):
            ref_md = cand
            break

    md_files = collect_md(target)
    citations = []
    for p in md_files:
        citations.extend(find_citations(p))

    ctx = {"target": target, "bib_path": bib_path if os.path.isfile(bib_path) else "(无 references.bib)",
           "entries": entries, "dup_keys": dup_keys,
           "citations": citations, "ref_md": ref_md}
    findings = []
    for r in RULES:
        try:
            findings.extend(r["check"](ctx))
        except Exception:
            continue

    sev_rank = {"blocker": 0, "warning": 1, "nit": 2}
    counts = {"blocker": 0, "warning": 0, "nit": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1

    summary = {"tool": TOOL, "version": VERSION, "target": target,
               "bib_entries": len(entries), "citations_found": len(citations),
               "rules_run": len(RULES),
               "blocker": counts["blocker"], "warning": counts["warning"],
               "nit": counts.get("nit", 0)}

    if args.format == "json":
        print(json.dumps({"summary": summary,
                          "findings": [f.to_dict() for f in findings]},
                         ensure_ascii=False, indent=2))
    else:
        print("lhg-thesis 引用审计 v%s：%d 个 bib 条目，%d 处文中引用，%d 条规则"
              % (VERSION, len(entries), len(citations), len(RULES)))
        print("blocker=%d warning=%d nit=%d"
              % (counts["blocker"], counts["warning"], counts.get("nit", 0)))
        for f in sorted(findings, key=lambda x: (sev_rank[x.severity], x.rule_id)):
            print("[%s][%s] %s %s %s" % (f.severity, f.rule_id, f.file, f.line, f.title))
            if f.snippet:
                print("    %s" % f.snippet)

    fail_rank = sev_rank[args.fail_on]
    bad = any(sev_rank[f.severity] <= fail_rank for f in findings)
    return 2 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
