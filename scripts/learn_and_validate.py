#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""learn_and_validate.py —— 「从人工校对中学习 → 留一法交叉验证 → 量化提升」

通用版：
  - 优先读取 prepare_pairs.py 生成的 manifest.json；
  - 没有 manifest 时，按信件编号在 raw/ 与 truth/ 目录自动配对；
  - 输出 learned_confusion.json（真实混淆表，供 correct.py --confusion 使用）
    和 validation_report.md（留一法验证报告）。

用法：
    python learn_and_validate.py
    python learn_and_validate.py --manifest manifest.json
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import correct as C
from person_density import letter_code

HERE = Path(__file__).resolve().parent
RAW_DIR = HERE / "raw"
TRUTH_DIR = HERE / "truth"
MANIFEST = HERE / "manifest.json"
OUT_JSON = HERE / "learned_confusion.json"
OUT_MD = HERE / "validation_report.md"


def _norm_code(code: str) -> str:
    return re.sub(r"[-\s_]", "", code).lower()


def _auto_pairs():
    pairs = []
    truth_files = list(TRUTH_DIR.glob("*")) if TRUTH_DIR.is_dir() else []
    for p in sorted(RAW_DIR.glob("*")) if RAW_DIR.is_dir() else []:
        if p.suffix.lower() not in (".txt", ".md"):
            continue
        code = _norm_code(letter_code(p.name))
        cands = [t for t in truth_files if code and code in _norm_code(t.stem)]
        if not cands:
            continue
        # 优先真值命名
        priority = [t for t in cands if any(k in t.name.lower() for k in ("真值", "truth", "confirmed"))]
        pairs.append({"code": p.stem, "draft": p, "truth": (priority or cands)[0]})
    return pairs


def load_pairs(manifest_path=None):
    if manifest_path is not None and Path(manifest_path).is_file():
        data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        pairs = []
        for e in data:
            if e.get("draft") and e.get("truth"):
                pairs.append({
                    "code": e.get("code", Path(e["draft"]).stem),
                    "draft": Path(e["draft"]),
                    "truth": Path(e["truth"]),
                })
        return pairs
    if MANIFEST.is_file():
        return load_pairs(MANIFEST)
    return _auto_pairs()


def main():
    parser = argparse.ArgumentParser(description="盲测准确率验证与混淆表学习")
    parser.add_argument("--manifest", default=None, help="prepare_pairs.py 生成的配对清单")
    args = parser.parse_args()

    pairs = load_pairs(args.manifest)
    if not pairs:
        print("!" * 72)
        print("【无可验证配对】未找到盲读稿与人工真值的配对文件。")
        print("  请先运行 prepare_pairs.py 生成 raw/ 与 manifest.json，")
        print("  或把 raw 放 raw/、真值放 truth/。")
        print("!" * 72)
        sys.exit(2)

    print(f"发现 {len(pairs)} 组可验证配对\n")

    # 全量学习真实混淆表，供 correct.py 使用
    global_table = {}
    for pr in pairs:
        raw = pr["draft"].read_text(encoding="utf-8", errors="replace")
        ref = pr["truth"].read_text(encoding="utf-8", errors="replace")
        table = C.learn_confusion(
            C.keep_chars(C.extract_body(raw)),
            C.keep_chars(C.extract_body(ref)),
        )
        for right, wrongs in table.items():
            dst = global_table.setdefault(right, {})
            for wrong, n in wrongs.items():
                dst[wrong] = dst.get(wrong, 0) + n

    rows = []
    for i, pr in enumerate(pairs):
        raw = pr["draft"].read_text(encoding="utf-8", errors="replace")
        ref = pr["truth"].read_text(encoding="utf-8", errors="replace")

        # 留一法：用除自己以外的配对学习混淆表
        table = {}
        for j, other in enumerate(pairs):
            if i == j:
                continue
            o_raw = other["draft"].read_text(encoding="utf-8", errors="replace")
            o_ref = other["truth"].read_text(encoding="utf-8", errors="replace")
            learned = C.learn_confusion(
                C.keep_chars(C.extract_body(o_raw)),
                C.keep_chars(C.extract_body(o_ref)),
            )
            for right, wrongs in learned.items():
                dst = table.setdefault(right, {})
                for wrong, n in wrongs.items():
                    dst[wrong] = dst.get(wrong, 0) + n

        ann, sug, log = C.apply_corrections(
            C.keep_chars(C.extract_body(raw)),
            Counter(), Counter(), table,
        )
        base = C.score(C.keep_chars(C.extract_body(ref)), C.keep_chars(C.extract_body(raw)))
        after = C.score(C.keep_chars(C.extract_body(ref)), sug)
        rows.append((pr["code"], pr["draft"].name, base, after, after - base, len(log)))

    lines = [
        "# 手写 OCR 纠错引擎 · 留一法交叉验证报告",
        "",
        "> 方法：把已有的【盲读稿】视为 OCR 原始输出，【人工校对确认稿】视为标准答案；",
        "> 每次留出一封做测试，用其余信件学到的字形混淆规律去纠错，计算准确率提升。",
        "",
        "| 信件 | 盲读稿 | 基线准确率 | 纠错后准确率 | 提升 | 标记处数 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    tot_b = tot_a = 0.0
    for code, fn, b, a, d, nlog in rows:
        lines.append(f"| {code} | {fn} | {b:.2f}% | {a:.2f}% | {d:+.2f}pt | {nlog} |")
        tot_b += b
        tot_a += a
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
    OUT_JSON.write_text(
        json.dumps(global_table, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    print("\n".join(lines))
    print(f"\n混淆表 → {OUT_JSON}")
    print(f"报告 → {OUT_MD}")


if __name__ == "__main__":
    main()
