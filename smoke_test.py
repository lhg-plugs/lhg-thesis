#!/usr/bin/env python3
"""lhg-thesis 插件冒烟测试：全部绿才算过。

检查项：
 1. 三个 JSON 合法（plugin.json / marketplace.json / hooks.json）
 2. 4 个 SKILL.md 都有 name/description frontmatter，且 150~320 行
 3. 3 个 commands 都有 description frontmatter；thesis 含学术诚信声明
 4. 2 个 agents 都有 name/description/tools/model frontmatter
 5. skills 平台中立：不含 Claude Code 专有工具名
 6. fixtures：坏 fixture 的埋点规则必须全部命中且脚本 exit!=0；
    好 fixture 零 blocker 且 exit==0
 7. hooks 脚本：送审拦截 / 非论文目录放行 / 逃生开关 / 引用提醒

用法：python3 smoke_test.py [--repo <插件根目录>]
退出码：0=全绿，1=有失败。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, cond, detail=""):
    results.append((PASS if cond else FAIL, name, detail))
    return cond


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def frontmatter(path):
    text = read(path)
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fm = {}
    for ln in text[3:end].split("\n"):
        m = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", ln)
        if m:
            fm[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fm


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, **kw)


CITE_BAD_MUST = {"CITE-FMT-001", "CITE-KEY-001", "CITE-DUP-001", "CITE-UNUSED-001"}
STRUCT_BAD_MUST = {"STRUCT-CHAPTER-001", "FIG-NUM-001", "FIG-CAP-001", "REP-001"}
NEUTRAL_DENY = ["Task tool", "Bash tool", "Edit tool", "Write tool", "Read tool",
                "AskUserQuestion", "subagent_type", "PreToolUse", "PostToolUse",
                "${CLAUDE_", "CLAUDE_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)
    AUDIT = os.path.join(repo, "scripts", "audit")

    # 1. JSON 合法
    for rel in [".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
                "hooks/hooks.json"]:
        p = os.path.join(repo, rel)
        try:
            d = json.loads(read(p))
            check("JSON 合法: " + rel, True)
            if rel.endswith("plugin.json"):
                check("plugin.json name==lhg-thesis", d.get("name") == "lhg-thesis",
                      str(d.get("name")))
                check("plugin.json 有 version/description/author",
                      all(d.get(k) for k in ("version", "description", "author")))
            if rel.endswith("marketplace.json"):
                ps = d.get("plugins", [])
                check("marketplace.json source==./",
                      len(ps) == 1 and ps[0].get("source") == "./" and
                      ps[0].get("name") == "lhg-thesis", str(ps))
            if rel.endswith("hooks.json"):
                check("hooks.json 顶层有 hooks 包装", "hooks" in d)
                evts = d["hooks"]
                check("hooks.json 有 PreToolUse+PostToolUse",
                      "PreToolUse" in evts and "PostToolUse" in evts,
                      str(list(evts.keys())))
        except Exception as e:
            check("JSON 合法: " + rel, False, str(e))

    # 2. SKILL.md
    for skill in ["lhg-th-proposal", "lhg-th-writing", "lhg-th-cite", "lhg-th-review"]:
        p = os.path.join(repo, "skills", skill, "SKILL.md")
        fm = frontmatter(p)
        check("skill frontmatter: " + skill,
              bool(fm.get("name")) and bool(fm.get("description")),
              "name=%s" % fm.get("name"))
        nlines = len(read(p).split("\n"))
        check("skill 行数 150~320: %s (%d 行)" % (skill, nlines),
              150 <= nlines <= 320, str(nlines))
        body = read(p)
        bad_words = [w for w in NEUTRAL_DENY if w in body]
        check("skill 平台中立: " + skill, not bad_words, "命中: %s" % bad_words)
        check("skill 有出品区: " + skill,
              "出品：刘洪光" in body and "https://github.com/lhg-skills" in body)
        check("skill 有自检与反馈: " + skill, "自检与反馈" in body)

    # 3. commands
    for cmd in ["thesis", "thesis-cite", "thesis-audit"]:
        p = os.path.join(repo, "commands", cmd + ".md")
        fm = frontmatter(p)
        check("command description: " + cmd, bool(fm.get("description")),
              str(fm.get("description"))[:60])
    check("thesis 命令含学术诚信声明",
          "学术诚信声明" in read(os.path.join(repo, "commands", "thesis.md")))
    check("writing skill 含学术诚信声明",
          "学术诚信声明" in read(os.path.join(repo, "skills", "lhg-th-writing", "SKILL.md")))

    # 4. agents
    for ag in ["writer", "reviewer"]:
        p = os.path.join(repo, "agents", ag + ".md")
        fm = frontmatter(p)
        check("agent frontmatter: " + ag,
              all(fm.get(k) for k in ("name", "description", "tools", "model")),
              str({k: fm.get(k) for k in ("name", "model")}))

    # 5. 审计脚本冒烟
    def audit_hits(script, target):
        r = run([sys.executable, os.path.join(AUDIT, script),
                 "--target", os.path.join(repo, target), "--format", "json"])
        try:
            d = json.loads(r.stdout)
        except Exception:
            return None, r.returncode, []
        return d["summary"], r.returncode, [f["rule_id"] for f in d["findings"]]

    s, code, ids = audit_hits("cite_audit.py", "fixtures/thesis-bad")
    check("cite 坏 fixture exit!=0", code != 0, "exit=%d" % code)
    check("cite 坏 fixture blocker>0", s and s["blocker"] > 0, str(s))
    missing = CITE_BAD_MUST - set(ids)
    check("cite 埋点全命中 (%d/%d)" % (len(CITE_BAD_MUST - missing), len(CITE_BAD_MUST)),
          not missing, "缺失: %s" % sorted(missing))

    s, code, _ = audit_hits("cite_audit.py", "fixtures/thesis-good")
    check("cite 好 fixture 零 blocker", s and s["blocker"] == 0, str(s))
    check("cite 好 fixture exit==0", code == 0, "exit=%d" % code)

    s, code, ids = audit_hits("structure_audit.py", "fixtures/thesis-bad")
    check("struct 坏 fixture exit!=0", code != 0, "exit=%d" % code)
    check("struct 坏 fixture blocker>0", s and s["blocker"] > 0, str(s))
    missing = STRUCT_BAD_MUST - set(ids)
    check("struct 埋点全命中 (%d/%d)" % (len(STRUCT_BAD_MUST - missing), len(STRUCT_BAD_MUST)),
          not missing, "缺失: %s" % sorted(missing))

    s, code, _ = audit_hits("structure_audit.py", "fixtures/thesis-good")
    check("struct 好 fixture 零 blocker", s and s["blocker"] == 0, str(s))
    check("struct 好 fixture exit==0", code == 0, "exit=%d" % code)

    # 6. hooks
    def hook(script, payload, env=None):
        e = dict(os.environ)
        e.update(env or {})
        return run([sys.executable, os.path.join(repo, "hooks", script)],
                   input=payload, env=e)

    with tempfile.TemporaryDirectory() as td:
        # 非论文目录：git commit 直接放行
        r = hook("pre_submit_audit.py",
                 '{"tool_input":{"command":"git commit -m \\"x\\""}}',
                 {"CLAUDE_PROJECT_DIR": td})
        check("hook: 非论文目录放行", r.returncode == 0 and not r.stdout.strip(),
              r.stdout[:80])

        # 论文目录：用坏 fixture 搭一个
        proj = os.path.join(td, "proj")
        shutil.copytree(os.path.join(repo, "fixtures", "thesis-bad"), proj)
        penv = {"CLAUDE_PROJECT_DIR": proj}
        r = hook("pre_submit_audit.py",
                 '{"tool_input":{"command":"git commit -m \\"x\\""}}', penv)
        try:
            d = json.loads(r.stdout)
            denied = d["hookSpecificOutput"]["permissionDecision"] == "deny"
        except Exception:
            denied = False
        check("hook: 论文目录 commit 有 blocker 拦截", denied, r.stdout[:120])

        r = hook("pre_submit_audit.py",
                 '{"tool_input":{"command":"pandoc thesis.md -o thesis.pdf"}}', penv)
        try:
            d = json.loads(r.stdout)
            denied2 = d["hookSpecificOutput"]["permissionDecision"] == "deny"
        except Exception:
            denied2 = False
        check("hook: pandoc 导出拦截", denied2, r.stdout[:80])

        r = hook("pre_submit_audit.py",
                 '{"tool_input":{"command":"git commit -m \\"x\\""}}',
                 dict(penv, LHG_THESIS_HOOKS_OFF="1"))
        check("hook: 逃生开关生效", r.returncode == 0 and not r.stdout.strip(),
              r.stdout[:80])

        r = hook("pre_submit_audit.py",
                 '{"tool_input":{"command":"ls -la"}}', penv)
        check("hook: 非目标命令放行", r.returncode == 0 and not r.stdout.strip(),
              r.stdout[:80])

        # 引用提醒 hook
        ghost_md = os.path.join(proj, "chapters", "ghost.md")
        with open(ghost_md, "w", encoding="utf-8") as fh:
            fh.write("某结论[@ghost2021]。\n")
        r = hook("post_write_cite_warn.py",
                 json.dumps({"tool_input": {"file_path": ghost_md}}), penv)
        check("hook: 幽灵引用警告", "additionalContext" in r.stdout and "ghost2021" in r.stdout,
              r.stdout[:80])

        ok_md = os.path.join(proj, "chapters", "ok.md")
        with open(ok_md, "w", encoding="utf-8") as fh:
            fh.write("某结论[@zhang2025]。\n")
        r = hook("post_write_cite_warn.py",
                 json.dumps({"tool_input": {"file_path": ok_md}}), penv)
        check("hook: 正常引用不警告", not r.stdout.strip(), r.stdout[:80])

        r = hook("post_write_cite_warn.py",
                 json.dumps({"tool_input": {"file_path": ghost_md}}),
                 dict(penv, LHG_THESIS_HOOKS_OFF="1"))
        check("hook: 提醒逃生开关生效", r.returncode == 0 and not r.stdout.strip(),
              r.stdout[:80])

    # 报告
    print("=" * 60)
    print("lhg-thesis 冒烟测试报告")
    print("=" * 60)
    fails = 0
    for st, name, detail in results:
        mark = "✓" if st == PASS else "✗"
        print("%s %s %s" % (mark, st, name))
        if detail and st == FAIL:
            print("    → %s" % detail)
        if st == FAIL:
            fails += 1
    print("=" * 60)
    print("共 %d 项，通过 %d，失败 %d" % (len(results), len(results) - fails, fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
