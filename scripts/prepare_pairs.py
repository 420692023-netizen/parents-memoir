#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prepare_pairs.py —— 把「机器输出(raw)」与「人工真值(truth)」严格配对落盘

通用版：不内置任何信件编号。扫描项目里的转写稿，抽出引用区作为 raw，
再按信件编号在 truth 目录中寻找真值，生成 manifest.json 供
learn_and_validate.py 使用。缺失的真值只报告、不编造。

用法：
    python prepare_pairs.py [项目根路径]
    python prepare_pairs.py <项目根> --raw-dir DIR --truth-dir DIR --manifest out.json
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from person_density import find_root, letter_code

HERE = Path(__file__).resolve().parent
DEFAULT_RAW = HERE / "raw"
DEFAULT_TRUTH = HERE / "truth"
DEFAULT_MANIFEST = HERE / "manifest.json"


def _find_root():
    """自适应定位项目根。显式参数优先，其次是 cwd/脚本目录向上查找。"""
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        c = Path(sys.argv[1]).resolve()
        if (c / "素材库").is_dir():
            return c
    return find_root()


def extract_quoted(md_text: str) -> str:
    """抽取 markdown 中 '>' 引用区（原文照录正文）。"""
    out = []
    for line in md_text.splitlines():
        s = line.strip()
        if s.startswith(">"):
            s = s.lstrip(">").strip()
            if s:
                out.append(s)
    return "\n".join(out)


def _norm_code(code: str) -> str:
    return re.sub(r"[-\s_]", "", code).lower()


def _match_truth(code: str, truth_dir: Path):
    """在 truth 目录找匹配指定信件编号的真值文件，返回 Path 或 None。"""
    if not truth_dir.is_dir():
        return None
    ncode = _norm_code(code)
    candidates = []
    for p in sorted(truth_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() not in (".txt", ".md"):
            continue
        if ncode and ncode in _norm_code(p.stem):
            candidates.append(p)
    if not candidates:
        return None
    # 有多个同名变体时，优先名字里带“真值/confirmed/truth”的
    priority = [p for p in candidates if any(k in p.name.lower() for k in ("真值", "truth", "confirmed"))]
    return (priority or candidates)[0]


def source_files(root: Path):
    """扫描项目转写稿，返回 [(Path, code)]。"""
    zhuaxie = root / "素材库" / "信件" / "转写"
    dianbao = root / "素材库" / "电报" / "转写"
    files = []
    for d in (zhuaxie, dianbao):
        if not d.is_dir():
            continue
        files.extend(sorted(d.glob("信-*.md")) + sorted(d.glob("信-*.txt"))
                     + sorted(d.glob("电报-*.md")) + sorted(d.glob("电报-*.txt")))
    return [(p, letter_code(p.name)) for p in files]


def main():
    parser = argparse.ArgumentParser(description="生成 raw/truth 配对清单与 manifest.json")
    parser.add_argument("root", nargs="?", default=None, help="项目根路径（含 素材库/信件/转写）")
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW), help="raw 输出目录")
    parser.add_argument("--truth-dir", default=str(DEFAULT_TRUTH), help="truth 目录")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="manifest.json 输出路径")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else _find_root()
    raw_dir = Path(args.raw_dir)
    truth_dir = Path(args.truth_dir)
    manifest_path = Path(args.manifest)

    sources = source_files(root)
    if not sources:
        print("!" * 72)
        print("【未找到转写稿】", root)
        print("  本脚本需要项目内的 素材库/信件/转写 或 素材库/电报/转写。")
        print("  请 cd 到项目根目录后重跑，或显式指定项目根路径。")
        print("!" * 72)
        sys.exit(2)

    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    matched = 0
    for p, code in sources:
        body = extract_quoted(p.read_text(encoding="utf-8", errors="replace"))
        if not body.strip():
            continue
        draft = raw_dir / f"{code}_盲读.txt"
        draft.write_text(body.strip() + "\n", encoding="utf-8")
        truth = _match_truth(code, truth_dir)
        entry = {
            "code": code,
            "draft": str(draft),
            "source": str(p),
        }
        if truth is not None:
            entry["truth"] = str(truth)
            matched += 1
        manifest.append(entry)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print(f"{'信件编号':<14}{'raw 文件':<26}{'truth':<8}")
    print("=" * 72)
    for e in manifest:
        draft_name = Path(e["draft"]).name
        truth_name = Path(e["truth"]).name if e.get("truth") else "缺失"
        print(f"{e['code']:<14}{draft_name:<26}{truth_name:<8}")
    print("=" * 72)
    print(f"生成 raw：{len(manifest)} 个｜已匹配 truth：{matched} 个｜缺失：{len(manifest)-matched} 个")
    print(f"manifest → {manifest_path}")


if __name__ == "__main__":
    main()
