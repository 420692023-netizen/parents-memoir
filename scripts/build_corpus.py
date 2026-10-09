#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_corpus.py —— 由「人工校对过的家书」构建个人书写语料库（字迹数据库）

这是「OCR 手写体识别率提升」工程的地基：
把已经校对确认的文字，变成机器可用的统计先验（字频 / 邻接 / 词表 / 数字语境）。

用法:
  python build_corpus.py --src <已校对转写目录> --out corpus.json
                         [--exclude 关键词] [--owner 姓名]

输出 corpus.json 结构:
  char_freq       字频表（哪些字她常用）
  bigram          邻接频次（字与字的搭配习惯）
  lexicon         词表（重复出现 ≥2 次的 2–4 字组合，自动发现专名/惯用语）
  digit_units     数字后常跟的量词/单位（用于数字纠错）
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# 需要剥离的编辑噪声：批注、存疑标记、markdown 符号
NOISE_PATTERNS = [
    r"\*\*",                      # markdown 加粗
    r"\*",                        # 斜体
    r"〔[^〕]*〕",                  # 编辑批注 〔...〕
    r"［[^］]*］",                  # 全角方括号批注
    r"\[\?[^\]]*\]",              # 存疑标记 [?...]
    r"\[[^\]]{1,8}\??\]",         # 短标注 [字？]
    r"（按：[^）]*）",              # 整理者按语
    r"#+\s*",                     # 标题符
]
ANS_RE = re.compile("|".join(NOISE_PATTERNS))

# 只保留汉字、数字、极少数必要标点（用于切词）
HAN = re.compile(r"[\u4e00-\u9fff]")
DIGIT_RUN = re.compile(r"[0-9０-９]+([.．][0-9０-９]+)?")


def clean_line(line: str) -> str:
    """去掉引用符与编辑噪声，返回干净的正文行。"""
    s = line.strip()
    if s.startswith(">"):
        s = s.lstrip(">").strip()
    s = ANS_RE.sub("", s)
    return s.strip()


def is_body_line(s: str) -> bool:
    """判断是否为信件正文行（排除表格行、说明行）。"""
    if not s:
        return False
    if s.startswith("|"):
        return False
    if s.startswith("【"):
        return False
    return True


def extract_body(text: str) -> str:
    """
    抽取正文。优先级（★ 顺序不可调换）：

      ① 显式围栏  ===BODY=== … ===END===   ← 最高优先，人工标注的权威范围
      ② 引用区启发式（以 > 开头的行）
      ③ 剥离说明块后的兜底正文

    ★ 修 bug（2026-10-06）：原实现遇到**空行即 break**，
      而带"文书编号／人校状态"等头部元信息的真值文件，头部与正文之间必有空行，
      导致正文被整段丢弃（某封信仅统计到 64 字，实际 400+ 字）。
      → 空行应 continue 跳过；只有当遇到明确的说明块（【...】小节）才 break。

    ★★ 修 bug 之 bug（2026-10-06 二次）：修①时把「引用区」排在了「显式围栏」之前，
      而真值文件后半段【校正要点】小节里大量使用 `>` 引文，
      于是统计器把**校正注记**当成正文，真正的正文反而被整段丢弃：
        某封信实收 116 字（真值 544 字，丢 79%）
        另一封实收 35 字（真值约 400 字，丢 91%）
      → **显式围栏必须压过一切启发式**。有围栏的文件，绝不走引用分支。
    """
    lines = text.splitlines()

    # ① 标准正文围栏（最高优先）
    m = re.search(r"===BODY===\s*\n(.*?)\n===END===", text, re.S)
    if m:
        return "\n".join(x for x in
                         (clean_line(l) for l in m.group(1).splitlines()) if x)

    # ② 引用区启发式（无围栏时）
    quoted = [clean_line(l) for l in lines if l.strip().startswith(">")]
    quoted = [l for l in quoted if l]
    if quoted:
        return "\n".join(quoted)

    # ③ 兜底
    body = []
    for l in lines:
        c = clean_line(l)
        if not c:                     # 空行：跳过，不中断
            continue
        if not is_body_line(c):       # 说明块／表格：到此为止
            break
        body.append(c)
    return "\n".join(body)


def build(src: Path, exclude=None, owner=""):
    char_freq = Counter()
    bigram = Counter()
    ngram = defaultdict(Counter)     # n -> Counter
    letters = []

    files = sorted([p for p in src.rglob("*")
                    if p.suffix.lower() in {".md", ".txt"} and p.is_file()])
    if exclude:
        files = [p for p in files if exclude not in p.name]
    # ★ 排除归档目录：其中的文件已并入正件，再统计会重复计字频（D25）
    files = [p for p in files if "_archive" not in p.parts]

    for p in files:
        raw = p.read_text(encoding="utf-8", errors="replace")
        body = extract_body(raw)
        if not HAN.search(body):
            continue

        # 字频
        chars = [c for c in body if HAN.match(c) or c.isdigit() or c in "０１２３４５６７８９"]
        char_freq.update(chars)

        # 邻接（跨行不连，行尾句号等当作断隔）
        for line in body.splitlines():
            seq = [c for c in line if HAN.match(c) or c.isdigit()]
            for a, b in zip(seq, seq[1:]):
                bigram[a + b] += 1

        # 2–4 gram 词表（行内连续汉字）
        for line in body.splitlines():
            seg = re.split(r"[，。、；：？！…—\s（）()「」『』“”\"]+", line)
            for s in seg:
                s = "".join(HAN.findall(s))
                for n in (2, 3, 4):
                    for i in range(len(s) - n + 1):
                        ngram[n][s[i:i + n]] += 1

        letters.append({
            "file": p.name,
            "chars": len(chars),
            "path": str(p),
            "has_fence": bool(re.search(r"===BODY===", raw)),
        })
        # ★ 护栏：显式围栏文件的正文短得离谱时告警（防"抓错分支"静默复发）
        if re.search(r"===BODY===", raw) and len(chars) < 80:
            print(f"  ⚠️ [告警] {p.name} 有围栏却只统计到 {len(chars)} 字，"
                  f"疑似正文抽取分支错误，请核查。")

    # 词表：保留出现 ≥2 次且不被更长的同频组合包含的
    lex = Counter()
    for n in (2, 3, 4):
        for w, c in ngram[n].items():
            if c >= 2:
                lex[w] += c
    # 去掉被更长词完全覆盖且频次相同的短词
    words = sorted(lex.items(), key=lambda x: (-len(x[0]), -x[1]))
    kept = []
    covered = set()
    for w, c in words:
        if any(w in k[0] for k in kept) and c <= max(k[1] for k in kept if w in k[0]):
            covered.add(w)
            continue
        kept.append((w, c))
    kept.sort(key=lambda x: (-x[1], -len(x[0])))

    total = sum(char_freq.values())
    return {
        "owner": owner,
        "letters": letters,
        "char_freq": char_freq,
        "bigram": bigram,
        "lexicon": kept,
        "stats": {
            "letter_count": len(letters),
            "total_chars": total,
            "distinct_chars": len(char_freq),
            "bigram_types": len(bigram),
            "lexicon_size": len(kept),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="已人工校对的转写目录")
    ap.add_argument("--out", required=True, help="输出 corpus.json")
    ap.add_argument("--exclude", default=None, help="排除含该关键词的文件（如测试信）")
    ap.add_argument("--owner", default="")
    a = ap.parse_args()

    src = Path(a.src)
    if not src.exists():
        print("目录不存在:", src); sys.exit(1)

    c = build(src, a.exclude, a.owner)
    out = Path(a.out)
    out.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")

    s = c["stats"]
    print("语料库构建完成 →", out)
    print(f"  信件 {s['letter_count']} 封｜总字数 {s['total_chars']}｜不同字 {s['distinct_chars']}")
    print(f"  邻接类型 {s['bigram_types']}｜自动词表 {s['lexicon_size']} 条")
    print("\n高频字 TOP15:", " ".join(x[0] for x in c["char_freq"].most_common(15)))
    print("高频词 TOP15:", " ".join(w for w, _ in c["lexicon"][:15]))


if __name__ == "__main__":
    main()
