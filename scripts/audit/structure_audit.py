#!/usr/bin/env python3
"""lhg-thesis 结构审计：章节完整性、图表编号连续性、文本重复率启发式估算。

扫描目标目录的 chapters/*.md（或目录下所有 md）：
- 必需章节：摘要 / 绪论（引言）/ 结论 / 参考文献
- 图/表编号连续性（图 1-1、表 2-1 等），图片有无图注
- 章节间文本重叠率启发式估算（8 字滑窗，中文友好）

用法：
    python3 structure_audit.py --target <论文目录> [--format json|text] [--fail-on blocker|warning|nit]

有 blocker 时以 exit code 2 退出。零第三方依赖。
规则文案均为本项目原创。

诚实说明：REP 规则是"文本重叠率启发式估算"，不是学校查重系统的重复率，
报告里不许包装成"查重 X%"。
"""

import argparse
import json
import os
import re
import sys

VERSION = "1.0.0"
TOOL = "lhg-thesis/structure-audit"

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".bak"}
FIG_RE = re.compile(r"图\s*(\d+)(?:-(\d+))?")
TAB_RE = re.compile(r"表\s*(\d+)(?:-(\d+))?")
IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
NGRAM = 8
REP_THRESHOLD = 0.08  # 章节间重复 8-gram 占比超 8% 报 warning
# 计算重叠前剥离的内容：引用标记、图片语法（这些不是"重复写作"）
STRIP_RES = [re.compile(r"\[@[^\]]+\]"), re.compile(r"\\cite\{[^}]+\}"),
             re.compile(r"!\[[^\]]*\]\([^)]+\)")]


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


@rule("STRUCT-CHAPTER-001", "blocker", "结构", "必需章节缺失",
      "摘要、结论、参考文献三者缺一不可（绪论缺失为 warning）。"
      "缺什么补什么，不许带着缺章送审。")
def _r_chapter(ctx):
    blob = ctx["blob"]
    for name in ("摘要", "结论"):
        if name not in blob:
            yield _hit("STRUCT-CHAPTER-001", ctx["target"], "-",
                       "缺失必需章节：%s" % name)
    if "参考文献" not in blob and not ctx["has_refs"]:
        yield _hit("STRUCT-CHAPTER-001", ctx["target"], "-",
                   "缺失必需章节：参考文献（未找到 references.bib/md）")


@rule("STRUCT-INTRO-001", "warning", "结构", "绪论/引言章节缺失",
      "没找到绪论或引言。确认章节命名，或补上研究背景与问题提出章节。")
def _r_intro(ctx):
    if "绪论" not in ctx["blob"] and "引言" not in ctx["blob"]:
        yield _hit("STRUCT-INTRO-001", ctx["target"], "-",
                   "未发现绪论/引言章节")


def _check_num(rule_id, kind, regex, ctx):
    # 收集所有编号：chapter -> [seq...] 或全局 [n...]
    per_ch, glob = {}, []
    for path, text in ctx["chapters"]:
        for m in regex.finditer(text):
            ch, seq = m.group(1), m.group(2)
            if seq is None:
                glob.append(int(ch))
            else:
                per_ch.setdefault(ch, []).append(int(seq))
    if glob:
        expect = list(range(1, max(glob) + 1))
        missing = sorted(set(expect) - set(glob))
        if missing:
            yield _hit(rule_id, ctx["target"], "-",
                       "%s全局编号缺号：%s" % (kind, missing))
    for ch, seqs in sorted(per_ch.items()):
        expect = list(range(1, max(seqs) + 1))
        missing = sorted(set(expect) - set(seqs))
        if missing:
            yield _hit(rule_id, ctx["target"], "-",
                       "%s第 %s 章编号缺号：%s" % (kind, ch, missing))


@rule("FIG-NUM-001", "warning", "图表", "图编号不连续",
      "图 1-1 之后直接图 1-3（或全局图 1 后直接图 3）。补齐编号或重排，不许跳号。")
def _r_fignum(ctx):
    yield from _check_num("FIG-NUM-001", "图", FIG_RE, ctx)


@rule("TAB-NUM-001", "warning", "图表", "表编号不连续",
      "表编号跳号。补齐或重排，不许跳号。")
def _r_tabnum(ctx):
    yield from _check_num("TAB-NUM-001", "表", TAB_RE, ctx)


@rule("FIG-CAP-001", "warning", "图表", "图片无图注",
      "Markdown 图片没有配图注（图 X-X 标题）。补图注并在正文引用，不许留死图。")
def _r_figcap(ctx):
    for path, text in ctx["chapters"]:
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            if IMG_RE.search(ln):
                near = "\n".join(lines[max(0, i - 2):i + 3])
                if not FIG_RE.search(near):
                    yield _hit("FIG-CAP-001", path, "L%d" % (i + 1),
                               "图片无图注：%s" % ln.strip()[:80])


@rule("FIG-REF-001", "nit", "图表", "图的编号在正文未被引用",
      "出现了图注编号，但正文没有'如图 X-X 所示'引用。确认是死图就删，是漏引就补。")
def _r_figref(ctx):
    for path, text in ctx["chapters"]:
        defined, cited = set(), set()
        for m in re.finditer(r"^.{0,20}图\s*(\d+(?:-\d+)?)\s", text, re.M):
            defined.add(m.group(1))
        for m in re.finditer(r"如图\s*(\d+(?:-\d+)?)", text):
            cited.add(m.group(1))
        for num in sorted(defined - cited):
            yield _hit("FIG-REF-001", path, "-",
                       "图 %s 有图注但正文未引用" % num)


def _ngrams(text):
    for rx in STRIP_RES:
        text = rx.sub("", text)
    t = re.sub(r"\s+", "", text)
    return {t[i:i + NGRAM] for i in range(len(t) - NGRAM + 1)} if len(t) >= NGRAM else set()


@rule("REP-001", "warning", "重复", "章节间文本重叠率偏高（启发式）",
      "8 字滑窗统计跨章节重复片段占比。这只是重叠率估算，不是学校查重率；"
      "定位高重叠段落改写或加引用，不许用同义词替换糊弄。")
def _r_rep(ctx):
    grams_list = [(p, _ngrams(t)) for p, t in ctx["chapters"] if _ngrams(t)]
    for a in range(len(grams_list)):
        for b in range(a + 1, len(grams_list)):
            pa, ga = grams_list[a]
            pb, gb = grams_list[b]
            if not ga or not gb:
                continue
            inter = ga & gb
            ratio = len(inter) / min(len(ga), len(gb))
            if ratio > REP_THRESHOLD:
                sample = sorted(inter)[0] if inter else ""
                yield _hit("REP-001", "%s <-> %s" % (pa, pb), "-",
                           "两章重复 8-gram 占比 %.1f%%（如「%s…」），建议改写或加引用"
                           % (ratio * 100, sample[:12]))


# ---------------------------------------------------------------- 主流程

def collect_chapters(target):
    out = []
    ch_dir = os.path.join(target, "chapters")
    roots = [ch_dir] if os.path.isdir(ch_dir) else [target]
    for root in roots:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in sorted(files):
                if f.endswith(".md") and f.lower() not in ("readme.md", "references.md"):
                    p = os.path.join(dirpath, f)
                    try:
                        with open(p, encoding="utf-8") as fh:
                            out.append((p, fh.read()))
                    except OSError:
                        pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=".")
    ap.add_argument("--format", choices=["json", "text"], default="text")
    ap.add_argument("--fail-on", choices=["blocker", "warning", "nit"], default="blocker")
    args = ap.parse_args()

    target = os.path.abspath(args.target)
    chapters = collect_chapters(target)
    blob = "\n".join(t for _, t in chapters)
    # 文件名也参与章节识别
    blob += "\n" + "\n".join(os.path.basename(p) for p, _ in chapters)
    has_refs = any(os.path.isfile(os.path.join(target, n))
                   for n in ("references.bib", "references.md"))

    ctx = {"target": target, "chapters": chapters, "blob": blob, "has_refs": has_refs}
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
               "chapters": len(chapters), "rules_run": len(RULES),
               "blocker": counts["blocker"], "warning": counts["warning"],
               "nit": counts.get("nit", 0)}

    if args.format == "json":
        print(json.dumps({"summary": summary,
                          "findings": [f.to_dict() for f in findings]},
                         ensure_ascii=False, indent=2))
    else:
        print("lhg-thesis 结构审计 v%s：%d 个章节文件，%d 条规则"
              % (VERSION, len(chapters), len(RULES)))
        print("blocker=%d warning=%d nit=%d"
              % (counts["blocker"], counts["warning"], counts.get("nit", 0)))
        print("注：文本重叠率为启发式估算，不是学校查重率。")
        for f in sorted(findings, key=lambda x: (sev_rank[x.severity], x.rule_id)):
            print("[%s][%s] %s %s %s" % (f.severity, f.rule_id, f.file, f.line, f.title))
            if f.snippet:
                print("    %s" % f.snippet)

    fail_rank = sev_rank[args.fail_on]
    bad = any(sev_rank[f.severity] <= fail_rank for f in findings)
    return 2 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
