<!-- About 简介（推送后填写到仓库 About 栏）：
毕业论文助手：开题到盲审的写作流水线 ｜ 一键安装：/plugin marketplace add lhg-plugs/lhg-thesis
-->
<!-- topics（推送后打）：claude-code, claude-plugin, agent-skills, thesis, academic-writing, latex -->

# lhg-thesis：毕业论文助手，开题到盲审的写作流水线

> ## 学术诚信声明
>
> 本插件是**写作助手**，不是代写工具。它帮你搭框架、顺逻辑、查格式、模拟评审，
> 但**论文的观点、数据、结论必须是你的原创**。
> 使用本插件即表示你承诺遵守所在学校的学术规范，不抄袭、不编造数据、不伪造引用。
> 涉及学术不端的请求（如"帮我编几篇参考文献""数据不好看帮我改改"），本插件一律拒绝。

> **一句话介绍**：给 AI 编程助手装上"毕业论文流水线"——开题→大纲→分章写作→交叉引用审计→查重前自查→盲审模拟，GB/T 7714 引用格式脚本校验，学术诚信先行。
>
> **一键安装**：在 Claude Code 里运行
> ```
> /plugin marketplace add lhg-plugs/lhg-thesis
> /plugin install lhg-thesis@lhg-plugs
> ```

## 它是什么

`lhg-thesis` 是一个 Claude Code 插件（plugin 为主、skill 为辅）：

- **3 个命令**（小白入口）：`thesis` 全流程流水线，`thesis-cite` 引用专项，`thesis-audit` 结构体检
- **4 个平台中立 skill**（方法论，可移植到豆包/Workbuddy 等 agent 平台）：开题与大纲、分章写作（含去 AI 味 20 条清单）、GB/T 7714 引用规范、盲审模拟
- **2 个专家 agent**：分章写作专家、盲审模拟专家
- **2 个 hooks**：送审/导出/提交前审计拦截（硬门，可一键豁免）、写章节时幽灵引用提醒（警告级）
- **12 条确定性审计规则**：纯 Python、零第三方依赖

## 3 个命令用法

| 命令 | 作用 | 示例 |
|---|---|---|
| `/lhg-thesis:thesis` | 开题→大纲→分章写作→引用审计→查重前自查→盲审模拟，全流程 | `/lhg-thesis:thesis "大模型在作业批改中的应用"` |
| `/lhg-thesis:thesis-cite` | 引用专项：GB/T 7714 校验、幽灵引用/僵尸条目排查 | `/lhg-thesis:thesis-cite ./my-thesis` |
| `/lhg-thesis:thesis-audit` | 结构体检：缺章、图表跳号、文本重叠率估算 | `/lhg-thesis:thesis-audit ./my-thesis` |

## 目录结构

```
lhg-thesis/
├── .claude-plugin/          # plugin.json（插件清单）+ marketplace.json（本仓即市场）
├── commands/                # 3 个命令：thesis / thesis-cite / thesis-audit
├── skills/                  # 4 个平台中立 skill（开题大纲/分章写作/引用规范/盲审模拟）
├── agents/                  # 2 个专家 agent（writer / reviewer）
├── hooks/                   # 送审拦截 + 幽灵引用提醒（均可一键关闭）
├── scripts/audit/           # 确定性审计：cite_audit.py + structure_audit.py（零第三方依赖）
├── fixtures/                # 好/坏论文对照用例
├── smoke_test.py            # 冒烟测试（53 项）
├── ATTRIBUTION.md           # 灵感来源声明
└── LICENSE                  # MIT
```

## 论文目录约定

```
my-thesis/
├── thesis.yaml          # 题目/作者/学校/日期（可选，有它 hook 识别更准）
├── chapters/
│   ├── 01-摘要.md
│   ├── 02-绪论.md
│   └── ...
├── references.bib       # BibTeX 参考文献
└── figures/             # 图片（可选）
```

## 什么时候用 / 什么时候不用（FAQ）

**Q：各校格式要求不一样，这个插件能用吗？**
A：能，但要摆正位置。本插件给的是**通用底线**（GB/T 7714 著录框架、结构完整性、引用对应关系），各校模板的细则（标点全角半角、作者列几位、页眉页脚）**以学校模板为准**，插件里的 skill 和命令都写了这条。建议先把学校模板喂给 AI，再跑流程。

**Q：能保证查重率吗？**
A：**不能，也不承诺**。`structure_audit.py` 的 REP 规则是"章节间文本重叠率启发式估算"（8 字滑窗），只能定位疑似高重叠段落，**不是**学校查重系统的重复率。报告里会明确写清这一点，任何把它包装成"查重 X%"的说法都是不诚实的。

**Q：这是代写工具吗？**
A：不是。本插件是写作助手：框架、逻辑、格式、评审模拟可以帮你，但观点、数据、结论必须是你的。编造文献/数据的请求会被直接拒绝。首次使用 `/thesis` 会请你明确承诺遵守学术规范。

**Q：支持 LaTeX 吗？**
A：支持。引用标记同时识别 `[@key]`（Markdown）和 `\cite{key}`（LaTeX）；审计脚本不依赖编译环境。导出排版（pandoc/xelatex）在论文目录下会触发送审前审计硬门。

**Q：一定要用 Claude Code 吗？**
A：`skills/` 下的方法论是平台中立的纯 Markdown，可直接搬到豆包、Workbuddy 等 agent 平台用。只有 commands/agents/hooks 需要 Claude Code。

## 自迭代

- 每个 skill 末尾有「自检与反馈」节：质检门 + 标准冒烟用例 + 一键提 issue。
- 发现规则误报/漏报、方法论不合理：到本仓库提 issue（标题带对应 skill 前缀，如 `[lhg-th-cite]`），附论文类型（本/硕/博）与场景描述。

## 出品：刘洪光

刘洪光（https://github.com/lhg-skills）出品，lhg-plugs「小白专家插件」系列之一。
灵感来源见 [ATTRIBUTION.md](./ATTRIBUTION.md)（借鉴思路，实现与文案均为原创）。
