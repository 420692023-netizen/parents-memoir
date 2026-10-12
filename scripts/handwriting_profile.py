#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handwriting_profile.py —— 手写信件「字形档案」与转写质量比对工具（纯标准库）

设计前提（重要）：
    本脚本不训练、不微调任何 OCR/多模态模型。它做三件确定性的事——
      1) 存：把用户核对确认的转写稿沉淀为「个人字形档案」（已确认文本 + 易混字对 + 书写特征）
      2) 比：把任意两份转写稿（盲测稿 vs 带档案稿）做逐字对齐，算准确率、列出差异与易混字对
      3) 报：汇总档案积累情况与识别质量趋势
    准确率的真实提升来自"档案作为参考上下文喂回模型"，而非模型权重变化。

用法（三个子命令）：

  # 1) 初始化档案
  python handwriting_profile.py init --owner 母亲 --profile DIR

  # 2) 归档一封信：录入 AI 转写稿 + 用户核对稿，自动算一致率并累积易混字对
  python handwriting_profile.py add --profile DIR --letter 家书001 \
      --date 1985-03-27 --draft 转写.md --confirmed 核对稿.md

  # 3) A/B 对照：比较两份转写稿（盲测 vs 带档案），输出准确率与混淆字对
  python handwriting_profile.py compare --a 盲测转写.md --b 带档案转写.md

  # 4) 查看档案摘要与质量趋势
  python handwriting_profile.py report --profile DIR

参数：
  --ignore-punct  比对时忽略标点与空白（默认忽略，因为 AI 常擅自补标点）
  --json          额外输出 JSON 结果，便于批量统计
"""

import argparse
import difflib
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

PUNCT_RE = re.compile(
    r"[\s，。、；：？！…—·「」『』（）()《》〈〉“”\"'"
    r"‘’\[\]{}:;,.!?/\\_\-—…·]+"
)

# 占位与存疑标记——比对前必须整块剥离，否则标记里的文字会被当成正文参与逐字比对，
# 污染易混字对统计（实测踩坑：曾产出「刀->〔」「切->读」「给->〔」等无意义字对）。
# 语义约定（与 references/handwriting-profile.md 一致）：
#   〔……〕  = 完全读不出，是"替换型"标记 → 剥离后该处计为漏字（算错，符合预期）
#   [?] [？] = 字读出了但不确信，是"后缀型"标记 → 剥离后保留该字本身（不冤枉）
#   【……】  = 页眉/页脚/背面透字等非正文块 → 整体剥离
PLACEHOLDER_RE = re.compile(
    r"〔[^〕]{0,40}〕"          # 〔读不出〕〔猜测〕
    r"|［[^］]{0,40}］"          # 全角方括号
    r"|\[[^\]]{0,40}\]"         # 半角方括号 [?] [?透字]
    r"|【[^】]{0,40}】"          # 非正文块
    r"|□+|◻+|■+|▢+|�+"          # 空白框与替换符
)


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def normalize(text: str, ignore_punct: bool = True) -> str:
    """剥离占位标记 → 全角转半角 → 去空白；ignore_punct=True 时再去标点。"""
    text = PLACEHOLDER_RE.sub("", text)
    text = unicodedata.normalize("NFKC", text)
    text = PLACEHOLDER_RE.sub("", text)  # NFKC 可能把全角括号转成半角，再剥一次
    if ignore_punct:
        text = PUNCT_RE.sub("", text)
    else:
        text = re.sub(r"\s+", "", text)
    return text


def levenshtein(a: str, b: str) -> int:
    """精确编辑距离（两行 DP）。A/B 结论必须用它，不能只靠 difflib 的对齐口径——
    difflib 会把相邻字互换判成"漏1+多1"，从而虚高准确率。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


def is_meaningful(ch: str) -> bool:
    """字符是否值得计入易混字对——排除残留的括号/符号/空白等标记残渣。
    实测教训：占位符文字一旦漏进比对，会产出「刀->〔」「切->读」这类无意义字对，
    把真正的高频错字淹没。此处按 Unicode 类别只保留字母与数字。"""
    if not ch:
        return False
    return unicodedata.category(ch)[0] in ("L", "N")


def align(a: str, b: str):
    """返回 (opcodes, stats)。a=参照(确认稿), b=待评(转写稿)。"""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ops = sm.get_opcodes()
    match = sub = ins = dele = 0
    confusion = Counter()
    details = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            match += i2 - i1
        elif tag == "replace":
            n = min(i2 - i1, j2 - j1)
            sub += n
            for k in range(n):
                ca, cb = a[i1 + k], b[j1 + k]
                if is_meaningful(ca) and is_meaningful(cb):
                    confusion[(ca, cb)] += 1
            details.append(
                {
                    "op": "replace",
                    "ref": a[i1:i2][:40],
                    "got": b[j1:j2][:40],
                    "at": i1,
                }
            )
            if (i2 - i1) != (j2 - j1):
                details.append(
                    {
                        "op": "length-diff",
                        "ref": a[i1:i2][:40],
                        "got": b[j1:j2][:40],
                        "at": i1,
                    }
                )
        elif tag == "delete":
            dele += i2 - i1
            details.append({"op": "missing(确认稿有/转写无)", "ref": a[i1:i2][:40], "got": "", "at": i1})
        elif tag == "insert":
            ins += j2 - j1
            details.append({"op": "extra(转写多出)", "ref": "", "got": b[j1:j2][:40], "at": i1})
    total_ref = len(a)
    dist = levenshtein(a, b)
    stats = {
        "ref_chars": total_ref,
        "matched": match,
        "substituted": sub,
        "missing": dele,
        "extra": ins,
        "edit_distance": dist,
        "accuracy": round(max(0.0, 1 - dist / total_ref) * 100, 2) if total_ref else 0.0,
        "aligned_accuracy": round(match / total_ref * 100, 2) if total_ref else 0.0,
        "recall": round((match + sub) / total_ref * 100, 2) if total_ref else 0.0,
    }
    return details, stats, confusion


def cmd_init(args):
    root = Path(args.profile)
    root.mkdir(parents=True, exist_ok=True)
    (root / "confirmed").mkdir(exist_ok=True)
    (root / "drafts").mkdir(exist_ok=True)
    pj = root / "profile.json"
    if not pj.exists():
        pj.write_text(
            json.dumps(
                {
                    "owner": args.owner,
                    "created": datetime.now().isoformat(timespec="seconds"),
                    "letters": [],
                    "confusion_pairs": {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    md = root / "字形档案.md"
    if not md.exists():
        md.write_text(
            f"# {args.owner}的手写字形档案\n\n"
            "> 本档案由用户核对稿累积而成，是**识别同一手迹时的参考上下文**，不是训练出来的模型。\n"
            "> 使用方式：转写新信前先读本档案，优先按档案中的写法判读；存疑处仍标 `[?]`，绝不猜改。\n\n"
            "## 一、书写特征（人工填写，随时增补）\n"
            "- 惯用简体/繁体混写情况：\n"
            "- 特定字的固定写法（示例：某字把某部件写反/写成偏旁形）：\n"
            "- 连笔与断笔习惯：\n"
            "- 标点使用习惯（是否用顿号、是否爱用破折号）：\n"
            "- 常见错别字与其正确写法：\n"
            "- 落款格式与日期写法：\n"
            "- 抬头称呼习惯：\n\n"
            "## 二、易混字对（由脚本自动累积，按频次排序）\n"
            "（格式：错字 → 正确字 × 次数）\n\n"
            "## 三、已确认转写库\n"
            "每封信的确认稿存于 `confirmed/`，是本档案最有价值的部分。\n",
            encoding="utf-8",
        )
    print(f"✅ 档案已初始化：{root}")
    print(f"   请人工填写 {md} 的『书写特征』章节（模型猜不出你母亲的个人写法）")
    return 0


def cmd_add(args):
    root = Path(args.profile)
    pj = root / "profile.json"
    if not pj.exists():
        print("档案不存在，请先运行 init", file=sys.stderr)
        return 2
    data = json.loads(pj.read_text(encoding="utf-8"))
    draft = read_text(Path(args.draft))
    confirmed = read_text(Path(args.confirmed))

    a = normalize(confirmed, args.ignore_punct)
    b = normalize(draft, args.ignore_punct)
    details, stats, confusion = align(a, b)

    letter = args.letter
    (root / "confirmed" / f"{letter}.txt").write_text(confirmed, encoding="utf-8")
    (root / "drafts" / f"{letter}.txt").write_text(draft, encoding="utf-8")
    (root / f"比对报告_{letter}.md").write_text(
        render_report(letter, args.date, details, stats, confusion, args.ignore_punct),
        encoding="utf-8",
    )

    entry = {"letter": letter, "date": args.date or "", "stats": stats,
             "added": datetime.now().isoformat(timespec="seconds")}
    data["letters"] = [x for x in data["letters"] if x.get("letter") != letter] + [entry]
    for (wrong, right), n in confusion.items():
        key = f"{wrong}->{right}"
        data["confusion_pairs"][key] = data["confusion_pairs"].get(key, 0) + n
    pj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    update_md(root, data)

    print(f"✅ 已归档 {letter}：准确率 {stats['accuracy']}%（{stats['matched']}/{stats['ref_chars']} 字）")
    if confusion:
        top = confusion.most_common(8)
        print("   高频易混：", "、".join(f"{w}→{r}×{n}" for (w, r), n in top))
    print(f"   报告：{root / f'比对报告_{letter}.md'}")
    if args.json:
        print(json.dumps({"stats": stats, "confusion": confusion.most_common(20)},
                         ensure_ascii=False, indent=2))
    return 0


def render_report(letter, date, details, stats, confusion, ignore_punct) -> str:
    lines = [
        f"# 转写比对报告 · {letter}" + (f"（{date}）" if date else ""),
        "",
        "> 对照口径：以**用户核对稿为参照**，比较 AI 转写稿。标点与空白"
        + ("已忽略。" if ignore_punct else "参与比对。"),
        "",
        "## 一、总分",
        "",
        f"- 参照字数：{stats['ref_chars']}",
        f"- **净准确率（编辑距离口径）：{stats['accuracy']}%**　编辑距离 {stats['edit_distance']} 处",
        f"- 对齐一致率（辅助参考）：{stats['aligned_accuracy']}%",
        f"- 错字：{stats['substituted']}　漏字：{stats['missing']}　多字：{stats['extra']}",
        "",
        "## 二、易混字对（错字 → 正确字）",
        "",
    ]
    if confusion:
        lines += ["| 错字 | 正确字 | 次数 |", "|---|---|---|"]
        for (w, r), n in confusion.most_common(50):
            lines.append(f"| {w} | {r} | {n} |")
    else:
        lines.append("（无——完全一致）")
    lines += ["", "## 三、逐处差异（最多 200 条）", ""]
    for d in details[:200]:
        lines.append(f"- 位置 {d['at']}｜{d['op']}｜参照：{d['ref']}｜转写：{d['got']}")
    if len(details) > 200:
        lines.append(f"- ……（另有 {len(details) - 200} 条，见脚本 JSON 输出）")
    lines += ["", "## 四、下一轮改进动作（人工）", "",
              "1. 把上表高频错字逐个补进 `字形档案.md` 的『书写特征』——写出这位家人的固定写法",
              "2. 确认稿存于 `confirmed/`，转写新信前先读它作为上下文",
              "3. 存疑字不要猜改：在转写稿标 `[?]` 并列入待确认清单",
              ""]
    return "\n".join(lines)


def update_md(root: Path, data: dict):
    md = root / "字形档案.md"
    text = md.read_text(encoding="utf-8")
    pairs = sorted(data.get("confusion_pairs", {}).items(), key=lambda kv: -kv[1])
    block = "\n".join(f"- {k} ×{v}" for k, v in pairs) or "（暂无）"
    text = re.sub(
        r"(## 二、易混字对（由脚本自动累积，按频次排序）\n（格式：错字 → 正确字 × 次数）\n)[\s\S]*?(?=\n## )",
        lambda m: m.group(1) + "\n" + block + "\n",
        text,
    )
    md.write_text(text, encoding="utf-8")


def cmd_compare(args):
    a = normalize(read_text(Path(args.a)), args.ignore_punct)
    b = normalize(read_text(Path(args.b)), args.ignore_punct)
    if args.reverse:
        a, b = b, a
    details, stats, confusion = align(a, b)
    print("=== A/B 转写质量对照（参照=%s）===" % ("A" if not args.reverse else "B"))
    print(f"准确率：{stats['accuracy']}%　（{stats['matched']}/{stats['ref_chars']} 字）")
    print(f"错字 {stats['substituted']}　漏字 {stats['missing']}　多字 {stats['extra']}")
    if confusion:
        print("易混字对 TOP10：")
        for (w, r), n in confusion.most_common(10):
            print(f"  {w} → {r}  ×{n}")
    if args.json:
        print(json.dumps({"stats": stats, "confusion": confusion.most_common(30)},
                         ensure_ascii=False, indent=2))
    return 0


def cmd_report(args):
    root = Path(args.profile)
    pj = root / "profile.json"
    if not pj.exists():
        print("档案不存在", file=sys.stderr)
        return 2
    data = json.loads(pj.read_text(encoding="utf-8"))
    letters = data.get("letters", [])
    print(f"档案主人：{data.get('owner')}　建档：{data.get('created')}")
    print(f"已确认信件：{len(letters)} 封")
    if letters:
        accs = [x["stats"]["accuracy"] for x in letters if x.get("stats")]
        if accs:
            print(f"平均准确率：{sum(accs)/len(accs):.2f}%　最高 {max(accs)}%　最低 {min(accs)}%")
        else:
            print("平均准确率：暂无有效 stats 数据")
        print("\n逐封明细：")
        for x in sorted(letters, key=lambda y: y.get("date") or ""):
            s = x.get("stats")
            if not s:
                continue
            print(f"  {x['letter']:<14}{x.get('date',''):<12}准确率 {s['accuracy']:>6}%　"
                  f"错 {s['substituted']} 漏 {s['missing']} 多 {s['extra']}")
        if len(accs) >= 2:
            print("\n趋势：", " → ".join(f"{a:.1f}%" for a in accs),
                  "（档案累积后应呈上升趋势；若下降，先查是否字迹漂移/图像质量差异）")
    pairs = sorted(data.get("confusion_pairs", {}).items(), key=lambda kv: -kv[1])[:20]
    if pairs:
        print("\n累计易混字对 TOP20：")
        for k, v in pairs:
            print(f"  {k} ×{v}")
    print(f"\n下一步：把高频错字写进 {root / '字形档案.md'} 的『书写特征』——这部分必须人工做")
    return 0


def main():
    ap = argparse.ArgumentParser(description="手写信件字形档案与转写质量比对工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="初始化字形档案")
    p.add_argument("--owner", required=True, help="书写人称呼，如 母亲")
    p.add_argument("--profile", required=True, help="档案目录")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add", help="归档一封信（转写稿 + 核对稿）")
    p.add_argument("--profile", required=True)
    p.add_argument("--letter", required=True, help="信件编号，如 家书001")
    p.add_argument("--date", default="", help="信件日期，如 1985-03-27")
    p.add_argument("--draft", required=True, help="AI 转写稿路径")
    p.add_argument("--confirmed", required=True, help="用户核对稿路径")
    p.add_argument("--ignore-punct", action="store_true", default=True)
    p.add_argument("--keep-punct", dest="ignore_punct", action="store_false")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("compare", help="A/B 对照两份转写稿")
    p.add_argument("--a", required=True, help="A 稿（一般放参照/盲测稿）")
    p.add_argument("--b", required=True, help="B 稿（一般放带档案转写稿）")
    p.add_argument("--reverse", action="store_true", help="交换 A/B 角色")
    p.add_argument("--ignore-punct", action="store_true", default=True)
    p.add_argument("--keep-punct", dest="ignore_punct", action="store_false")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("report", help="档案摘要与质量趋势")
    p.add_argument("--profile", required=True)
    p.set_defaults(func=cmd_report)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
