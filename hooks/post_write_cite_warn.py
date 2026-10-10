#!/usr/bin/env python3
"""lhg-thesis 硬门②（警告级，不拦截）：写章节 md 时检查引用 key 是否存在。

触发：PostToolUse / Write|Edit。只做提醒，永远 exit 0、不拦截写入。
逻辑：被写的 .md 文件若含 [@key]/\\cite{key}，就到同项目 references.bib
里查 key 是否存在；有幽灵引用则提醒补条目或删引用。

逃生方式：LHG_THESIS_HOOKS_OFF=1（环境变量）可关闭本提醒；
或 /plugin disable lhg-thesis 停用整个插件。
零第三方依赖；内部出错 fail-open。
"""

import json
import os
import re
import sys

CITE_RE = re.compile(r"\[@([A-Za-z0-9_:\-]+(?:\s*;\s*@[A-Za-z0-9_:\-]+)*)\]")
LATEX_CITE_RE = re.compile(r"\\cite\{([^}]+)\}")
BIB_KEY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)\s*,")


def bib_keys(bib_path):
    try:
        with open(bib_path, encoding="utf-8") as fh:
            return set(BIB_KEY_RE.findall(fh.read()))
    except OSError:
        return set()


def cited_keys(text):
    out = set()
    for m in CITE_RE.finditer(text):
        for k in m.group(1).split(";"):
            k = k.strip().lstrip("@")
            if k:
                out.add(k)
    for m in LATEX_CITE_RE.finditer(text):
        for k in m.group(1).split(","):
            k = k.strip()
            if k:
                out.add(k)
    return out


def find_bib(path):
    d = os.path.dirname(os.path.abspath(path)) or "."
    for _ in range(4):  # 向上找 4 层（chapters/ 子目录场景）
        for name in ("references.bib",):
            cand = os.path.join(d, name)
            if os.path.isfile(cand):
                return cand
        d = os.path.dirname(d)
    return None


def main() -> int:
    if os.environ.get("LHG_THESIS_HOOKS_OFF") == "1":
        return 0
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    tool_input = payload.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path", "") or ""
    if not file_path.endswith(".md"):
        return 0
    if os.path.basename(file_path).lower() == "readme.md":
        return 0

    try:
        with open(file_path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return 0

    keys = cited_keys(text)
    if not keys:
        return 0
    bib = find_bib(file_path)
    if not bib:
        return 0
    missing = sorted(keys - bib_keys(bib))
    if not missing:
        return 0

    msg = (
        "引用提醒（lhg-thesis）：%s 引用了 %d 个在 references.bib 中不存在的 key：%s\n"
        "这是'幽灵引用'，送审前必须处理：补 bib 条目，或删除引用。\n"
        "关闭本提醒：export LHG_THESIS_HOOKS_OFF=1（当前会话有效）。"
    ) % (os.path.basename(file_path), len(missing), "、".join(missing[:10]))
    out = {"hookSpecificOutput": {
        "hookEventName": "PostToolUse", "additionalContext": msg}}
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
