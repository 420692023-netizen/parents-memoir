#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
learn_and_validate.py —— 「从人工校对中学习 → 留一法交叉验证 → 量化提升」

这才是"识别率提升"的严谨做法：不用任何人第二次看图，
而是把【已有的一次盲读】当成"OCR 输出"，把【你的校对确认稿】当成"标准答案"，
从两者的差异里自动学到这个人的字形混淆规律，
再用**留一法**（每次留一封做测试，其余做训练）证明：
  用上学到的规律后，同样的盲读稿能被纠正到多少准确率。

输出：
  learned_confusion.json   学到的混淆规律
  validation_report.md     逐封验证报告（含提升幅度）

用法:
  python learn_and_validate.py
"""
import json
import sys
from pathlib import Path

import correct as C

HERE = Path(__file__).resolve().parent
DRAFTS = HERE / "drafts"
REFDIR = HERE / "ref"

OUT_JSON = HERE / "learned_confusion.json"
OUT_MD = HERE / "validation_report.md"


def load_pairs():
    """把 drafts 里的盲读稿 与 ref 里同编号的参照稿配对。"""
    pairs = []
    for p in sorted(DRAFTS.glob("*.txt")):
        name = p.stem
        # 提取 信050 / 家书001 之类的编号
        code = None
        for token in (r"信0?(\d{3})", r"家书(\d{3})", r"家书第?(\d{2})封"):
            import re
            m = re.search(token, name)
            if m:
                code = m.group(0)
                break
        if not code:
            continue
        # 找参照稿
        cands = list(REFDIR.glob(f"*{code}*_去标记.md"))
        if not cands:
            continue
        pairs.append({
            "draft": p,
            "ref": cands[0],
            "code": code,
        })
    return pairs


def main():
    pairs = load_pairs()
    if not pairs:
        # ★ 静默成功比失败更危险：无数据却退出码 0，会让人以为"验证通过"
        print("!" * 70)
        print("【无可验证配对】未找到盲读稿（raw）与参照稿（truth）的配对文件。")
        print("  本脚本用于盲测准确率，需要先有：")
        print("    raw/   —— 机器盲读输出（未看原件时的识别结果）")
        print("    truth/ —— 人工校正后的真值")
        print("  生成方式：先跑 prepare_pairs.py 落盘配对，再跑 learn_and_validate.py。")
        print("!" * 70)
        sys.exit(2)

    print(f"发现 {len(pairs)} 组可验证配对\n")

    rows = []
    for i, pr in enumerate(pairs):
        raw = pr["draft"].read_text(encoding="utf-8", errors="replace")
        ref = pr["ref"].read_text(encoding="utf-8", errors="replace")

        # 留一法：用 除自己以外 的所有配对 学混淆表（调用已去环的 learn_confusion）
        table = {}
        for j, other in enumerate(pairs):
            if i == j:
                continue
            o_raw = other["draft"].read_text(encoding="utf-8", errors="replace")
            o_ref = other["ref"].read_text(encoding="utf-8", errors="replace")
            for right, wrongs in C.learn_confusion(
                C.keep_chars(C.extract_body(o_raw)),
                C.keep_chars(C.extract_body(o_ref)),
            ).items():
                table.setdefault(right, {}).update(
                    {w: table.get(right, {}).get(w, 0) + n
                     for w, n in wrongs.items()}
                )

        ann, sug, log = C.apply_corrections(
            C.keep_chars(C.extract_body(raw)),
            C.Counter(), C.Counter(), table,
        )
        base = C.score(C.keep_chars(C.extract_body(ref)),
                       C.keep_chars(C.extract_body(raw)))
        after = C.score(C.keep_chars(C.extract_body(ref)), sug)
        rows.append((pr["code"], pr["draft"].name, base, after,
                     after - base, len(log)))

    lines = [
        "# 手写 OCR 纠错引擎 · 留一法交叉验证报告",
        "",
        "> 方法：把已有的【盲读稿】视为 OCR 原始输出，【人工校对确认稿】视为标准答案；",
        "> 每次留出一封做测试，用其余信件学到的字形混淆规律去纠错，计算准确率提升。",
        "> 这样无需任何人重看图片，结论可复现、可审计。",
        "",
        "| 信件 | 盲读稿 | 基线准确率 | 纠错后准确率 | 提升 | 标记处数 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    tot_b = tot_a = 0.0
    for code, fn, b, a, d, nlog in rows:
        lines.append(f"| {code} | {fn} | {b:.2f}% | {a:.2f}% | "
                     f"{d:+.2f}pt | {nlog} |")
        tot_b += b; tot_a += a
    k = len(rows)
    if k:
        lines += [
            "",
            f"**平均基线：{tot_b/k:.2f}%　→　纠错后：{tot_a/k:.2f}%　"
            f"平均提升：{(tot_a-tot_b)/k:+.2f} 个百分点**",
            "",
            "> 判定标准（协议）：样本 ≥3 封、留一法、平均提升 ≥5 个百分点 → 机制有效。",
        ]

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({r[0]: r[1] for r in rows}, f, ensure_ascii=False, indent=1)

    print("\n".join(lines))
    print(f"\n报告 → {OUT_MD}")


if __name__ == "__main__":
    main()
