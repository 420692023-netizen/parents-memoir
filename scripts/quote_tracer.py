#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quote_tracer.py — 原话溯源脚本（时光家传 Skill 配套）

用途：
    把家传成稿中的每句"原话直引"反向映射到原始素材/转写稿的文件与行号，
    生成《原话溯源表》Markdown。既是质检工具，也是交付给客户的信任凭证。

用法：
    python quote_tracer.py 成稿.md 素材目录 [-o 输出.md]

说明：
    - 提取成稿中 “...”「...」"..." 三种引号内、长度 >= 6 字的文本作为原话候选
    - 匹配前做归一化（去空白与标点），容忍转写标点差异
    - 未匹配的条目标记"未找到（需人工核对）"——这正是防"AI 顺手补写"的关卡
    - 纯本地运行，只读不写素材，标准库零依赖
"""
import argparse
import re
import sys
from pathlib import Path

QUOTE_PATTERN = re.compile(r"[“\"「]([^”\"」]{6,120})[”\"」]")
PUNCT = re.compile(r"[\s，。、；：？！…—·“”‘’「」『』（）()《》<>.,;:!?—-]")


def normalize(text: str) -> str:
    return PUNCT.sub("", text)


def load_sources(src_dir: Path, exclude: set):
    """读取素材目录下所有 .md/.txt 文件，返回 [(文件, 行号, 原文行, 归一化行)]。排除成稿与输出文件自身。"""
    rows = []
    exts = {".md", ".txt"}
    exclude = {p.resolve() for p in exclude}
    for p in sorted(src_dir.rglob("*")):
        if p.suffix.lower() not in exts or not p.is_file() or p.resolve() in exclude:
            continue
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                rows.append((p, i, line.strip(), normalize(line)))
        except OSError as e:
            print(f"[警告] 读取失败 {p}: {e}", file=sys.stderr)
    return rows


def trace(manuscript: Path, src_dir: Path, extra_exclude=None):
    text = manuscript.read_text(encoding="utf-8", errors="replace")
    quotes = []
    seen = set()
    for m in QUOTE_PATTERN.finditer(text):
        q = m.group(1).strip()
        if q and q not in seen:
            seen.add(q)
            quotes.append(q)
    exclude = {manuscript}
    if extra_exclude:
        exclude.update(extra_exclude)
    sources = load_sources(src_dir, exclude)

    results = []
    for q in quotes:
        nq = normalize(q)
        hit = None
        if nq:
            for f, ln, raw, nrow in sources:
                if nq in nrow:
                    hit = (f, ln, raw)
                    break
        results.append((q, hit))
    return results


def render(manuscript: Path, results) -> str:
    found = sum(1 for _, h in results if h)
    lines = [
        f"# 原话溯源表（{manuscript.stem}）",
        "",
        f"- 原话直引总数：{len(results)}",
        f"- 已溯源：{found} ｜ 未找到（需人工核对）：{len(results) - found}",
        "- 说明：未找到不等于虚构（可能是标点/归并差异），但必须逐条人工确认来源后方可交付。",
        "",
        "| # | 原话直引 | 来源文件 | 行号 | 状态 |",
        "|---|---|---|---|---|",
    ]
    for i, (q, hit) in enumerate(results, 1):
        q_disp = q.replace("|", "\\|")
        if len(q_disp) > 50:
            q_disp = q_disp[:50] + "…"
        if hit:
            f, ln, _ = hit
            lines.append(f"| {i} | {q_disp} | {f.name} | {ln} | ✅ 已溯源 |")
        else:
            lines.append(f"| {i} | {q_disp} | — | — | ⚠️ 需人工核对 |")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="原话溯源（时光家传配套）")
    ap.add_argument("manuscript", help="家传成稿 Markdown 文件")
    ap.add_argument("src_dir", help="素材/转写稿目录（递归扫描 .md/.txt）")
    ap.add_argument("-o", "--output", help="输出 Markdown 路径（默认打印到屏幕）")
    args = ap.parse_args()

    manuscript = Path(args.manuscript)
    src_dir = Path(args.src_dir)
    if not manuscript.is_file():
        sys.exit(f"成稿不存在：{manuscript}")
    if not src_dir.is_dir():
        sys.exit(f"素材目录不存在：{src_dir}")

    extra = [Path(args.output)] if args.output else None
    results = trace(manuscript, src_dir, extra_exclude=extra)
    report = render(manuscript, results)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"已生成：{args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
