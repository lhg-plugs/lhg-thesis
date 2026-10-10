#!/usr/bin/env python3
"""lhg-thesis 硬门①：送审/导出/提交前跑引用+结构审计，有 blocker 则拦截。

触发：PreToolUse / Bash。只在"论文项目目录"里生效：
目录下有 thesis.yaml，或 chapters/ + references.bib 同时存在。
拦截的命令：pandoc / xelatex / pdflatex / latexmk（导出排版）
与 git commit（提交）。

逃生方式（按推荐度排序）：
  1. 修掉 blocker 后再导出/提交（推荐）。
  2. 紧急情况：LHG_THESIS_HOOKS_OFF=1（单次豁免本次 hook）。
  3. /plugin disable lhg-thesis（整个插件停用，hooks 不再触发）。

设计原则：脚本内部出错一律 fail-open 直接放行；
非论文目录、非目标命令 0 开销放行。零第三方依赖。
"""

import json
import os
import re
import subprocess
import sys

AUDIT_TIMEOUT = 60
TARGET_RE = re.compile(r"(^|[;&|])\s*(pandoc|xelatex|pdflatex|lualatex|latexmk)\b")
COMMIT_RE = re.compile(r"(^|[;&|])\s*git\s+.*\bcommit\b")


def is_thesis_dir(d):
    if os.path.isfile(os.path.join(d, "thesis.yaml")):
        return True
    return os.path.isdir(os.path.join(d, "chapters")) and (
        os.path.isfile(os.path.join(d, "references.bib"))
        or os.path.isfile(os.path.join(d, "references.md")))


def main() -> int:
    if os.environ.get("LHG_THESIS_HOOKS_OFF") == "1":
        return 0

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    tool_input = payload.get("tool_input", {}) or {}
    command = tool_input.get("command", "") or ""
    if not (TARGET_RE.search(command) or COMMIT_RE.search(command)):
        return 0  # 非目标命令：快速放行

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    if not is_thesis_dir(project_dir):
        return 0  # 非论文目录：放行

    plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scripts = [
        (os.path.join(plugin_root, "scripts", "audit", "cite_audit.py"), "引用"),
        (os.path.join(plugin_root, "scripts", "audit", "structure_audit.py"), "结构"),
    ]
    if not all(os.path.isfile(s) for s, _ in scripts):
        return 0  # 审计脚本缺失：fail-open

    blockers = []
    for script, label in scripts:
        try:
            proc = subprocess.run(
                [sys.executable, script, "--target", project_dir, "--format", "json"],
                capture_output=True, text=True, timeout=AUDIT_TIMEOUT)
            data = json.loads(proc.stdout) if proc.stdout.strip() else {}
        except Exception:
            continue
        for f in data.get("findings", []):
            if f.get("severity") == "blocker":
                blockers.append((label, f))

    if not blockers:
        return 0

    lines = [
        "提交/导出被 lhg-thesis 硬门拦截：审计发现 %d 个 blocker（论文硬伤），修完再继续。"
        % len(blockers), "",
    ]
    for label, f in blockers[:10]:
        lines.append("- [%s][%s] %s %s" % (label, f.get("rule_id"), f.get("file"), f.get("title")))
    if len(blockers) > 10:
        lines.append("…另有 %d 个，完整清单请跑 /lhg-thesis:thesis-audit" % (len(blockers) - 10))
    lines += ["", "修复方式：运行 /lhg-thesis:thesis-cite 与 /lhg-thesis:thesis-audit 按报告逐条修复；",
              "紧急豁免（单次）：LHG_THESIS_HOOKS_OFF=1"]
    out = {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "\n".join(lines)}}
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
