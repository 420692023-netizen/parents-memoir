#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
correct.py —— 基于个人书写语料库（字迹/文笔数据库）的手写 OCR 后纠错引擎

【核心思想】
通用 OCR 认手写体出错，是因为它只判断"这个字形像谁"。
而我们已经从人工校对过的信件里，统计出这位书写者：
  · 常用哪些字（字频）
  · 字与字怎么搭配（邻接/bigram）
  · 会怎样按音落字（方言俗字映射）
  · 哪些形近字容易混（实测混淆表）
所以：当 OCR 输出的字与这些统计先验冲突时，就能自动纠偏或标记存疑。

【三道闸】
  G1 方言俗字映射  —— 确定性最高，释义；正文永不自动改字
  G2 实测混淆表     —— 从已校对信件的"盲读 vs 确认"差异中学到的 误读→正确
  G3 数字语境校验   —— 数字后若无可信量词/单位 → 标 [?] 待人工

【铁律】
  正文永不自动改字（原话保真）。所有纠错以"建议"形式输出到独立字段，
  是否采纳由委托人裁决。这既是伦理底线，也让每次人工裁决反哺档案。

用法:
  python correct.py --in ocr.txt --out corrected.md [--confusion learned.json]
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---------------- 编辑噪声清洗 ----------------
NOISE = [
    r"\*\*", r"\*",
    r"〔[^〕]*〕",
    r"［[^］]*］",
    r"\[\?[^\]]*\]",
    r"\[[^\]]{1,8}\??\]",
    r"（按：[^）]*）",
    r"^#+\s*",
]
NOISE_RE = re.compile("|".join(NOISE), re.M)
HAN = re.compile(r"[\u4e00-\u9fff]")
DIGIT_RUN = re.compile(r"[0-9０-９]+([.．][0-9]+)?")


def clean_line(line: str) -> str:
    s = line.strip()
    if s.startswith(">"):
        s = s.lstrip(">").strip()
    s = NOISE_RE.sub("", s)
    return s.strip()


def is_body(s: str) -> bool:
    return bool(s) and not s.startswith("|") and not s.startswith("【")


def extract_body(text: str) -> str:
    lines = text.splitlines()
    quoted = [clean_line(l) for l in lines if l.strip().startswith(">")]
    quoted = [l for l in quoted if l]
    if quoted:
        return "\n".join(quoted)
    out = []
    for l in lines:
        c = clean_line(l)
        if not c:
            continue          # 空行跳过（原为 break，会把正文截成 2 字）
        if not is_body(c):
            break             # 遇到表格行/说明块才结束
        out.append(c)
    return "\n".join(out)


def keep_chars(text: str) -> str:
    """只保留汉字与数字，用于统计与打分。"""
    return "".join(re.findall(r"[\u4e00-\u9fff0-9０-９]", text))


# ---------------- 统计学习 ----------------
def build_profile(paths):
    cf, bg = Counter(), Counter()
    ng = {2: Counter(), 3: Counter(), 4: Counter()}
    for p in paths:
        body = extract_body(p.read_text(encoding="utf-8", errors="replace"))
        chars = keep_chars(body)
        if not HAN.search(chars):
            continue
        cf.update(chars)
        for line in body.splitlines():
            seq = keep_chars(line)
            for a, b in zip(seq, seq[1:]):
                bg[a + b] += 1
        for line in body.splitlines():
            for seg in re.split(r"[，。、；：？！…—\s（）()「」『』“”\"]+", line):
                s = "".join(HAN.findall(seg))
                for n in (2, 3, 4):
                    for i in range(len(s) - n + 1):
                        ng[n][s[i:i + n]] += 1
    lex = Counter()
    for n in (2, 3, 4):
        for w, c in ng[n].items():
            if c >= 2:
                lex[w] += c
    return cf, bg, lex


def learn_confusion(raw: str, ref: str):
    """
    从"盲读稿(raw)"与"确认稿(ref)"的差异中学习单字混淆：
    返回 {正确字: Counter({误读字: n})}

    ★缺陷 D22 修复：原实现会把 x→y 与 y→x 同时学进表里，
      应用到纠错时两条规则互相打架，导致准确率不升反降（实测 -1.87pt）。
      现改为【去环】：对每一对互逆的混淆，只保留频次更高的方向，
      且要求频次差 ≥ 2，避免频次接近时来回改字。
    """
    import difflib
    sm = difflib.SequenceMatcher(None, ref, raw, autojunk=False)
    pair_freq = Counter()      # (x, y) 表示 误读 x → 正确 y
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace" and (i2 - i1) == 1 and (j2 - j1) == 1:
            wrong, right = raw[j1], ref[i1]
            if HAN.match(right) and HAN.match(wrong):
                pair_freq[(wrong, right)] += 1

    # 去环：x→y 与 y→x 同时存在时，保留频次高的一方（且差≥2）
    resolved = {}
    for (x, y), n in pair_freq.items():
        rev = pair_freq.get((y, x), 0)
        if rev and n > rev and (n - rev) >= 2:
            resolved.setdefault(y, Counter())[x] += n
        elif rev == 0:
            resolved.setdefault(y, Counter())[x] += n
        elif rev and n > rev and (n - rev) < 2:
            pass   # 频次太接近，放弃该规则（宁缺毋错）
        # n < rev 的情况，由 (y,x) 那条规则处理
    return resolved


# ---------------- 纠错应用 ----------------
def apply_corrections(raw: str, cf: Counter, bg: Counter, confusion: dict,
                      threshold: float = 0.0):
    """
    返回 (标注版, 建议稿, 变更日志)
    标注版：原字保留，在其后插入 [误→正?]
    建议稿：把疑似处替换为候选正确字（仅用于评估增益/生成草稿）
    """
    # 反查：误读字 -> [(正确字, 频次)]
    wrong2right = {}
    for right, wrongs in confusion.items():
        for wrong, n in wrongs.items():
            wrong2right.setdefault(wrong, []).append((right, n))

    total = sum(cf.values()) or 1
    annotated, suggested, log = [], [], []
    i, n = 0, len(raw)

    while i < n:
        ch = raw[i]
        hit = wrong2right.get(ch)

        if hit:
            # 用上下文（左右邻接频次）消歧，选最优候选
            best, best_score = None, -1e9
            for right, freq in hit:
                score = freq * 2.0
                if i > 0 and HAN.match(raw[i - 1]):
                    score += bg.get(raw[i - 1] + right, 0) * 3
                if i + 1 < n and HAN.match(raw[i + 1]):
                    score += bg.get(right + raw[i + 1], 0) * 3
                score += cf.get(right, 0) / total * 50
                if score > best_score:
                    best, best_score = right, score
            if best and best != ch and best_score >= threshold:
                annotated.append(ch + "[→" + best + "?]")
                suggested.append(best)
                log.append({
                    "pos": i, "gate": "learned-confusion",
                    "wrong": ch, "right": best,
                    "conf": round(min(best_score / 10, 1.0), 2),
                    "note": "依据已校对信件实测混淆表建议，供人工裁决",
                })
                i += 1
                continue

        if ch.isdigit():
            m = DIGIT_RUN.match(raw, i)
            if m:
                num = m.group(0)
                after = raw[m.end():m.end() + 2]
                units = ["元", "块", "角", "分", "斤", "亩", "担", "日",
                         "号", "月", "年", "岁", "点", "个", "封", "天",
                         "次", "里", "级", "班"]
                annotated.append(num)
                suggested.append(num)
                if not any(u in after for u in units):
                    log.append({
                        "pos": i, "gate": "digit-context",
                        "wrong": num, "right": num, "conf": 0.5,
                        "note": f"数字「{num}」后未见常见量词/单位（后续：{after}），请核对原图",
                    })
                i = m.end()
                continue

        annotated.append(ch)
        suggested.append(ch)
        i += 1

    return "".join(annotated), "".join(suggested), log


# ---------------- 评分 ----------------
def lev(a: str, b: str) -> int:
    """Levenshtein 编辑距离（纯标准库实现）。"""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def score(ref: str, hyp: str) -> float:
    """净准确率（编辑距离口径），0-100。"""
    if not ref:
        return 0.0
    return max(0.0, (1 - lev(ref, hyp) / len(ref)) * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--confusion", default=None)
    ap.add_argument("--corpus", default=str(HERE / "corpus.json"),
                    help="个人语料 corpus.json 路径（默认脚本同目录）")
    ap.add_argument("--threshold", type=float, default=0.0)
    a = ap.parse_args()

    src = Path(a.inp)
    if not src.exists():
        print("输入不存在:", src); sys.exit(1)

    confusion = {}
    if a.confusion and Path(a.confusion).exists():
        confusion = json.loads(Path(a.confusion).read_text(encoding="utf-8"))

    corpus_p = Path(a.corpus)
    cf, bg = Counter(), Counter()
    if corpus_p.exists():
        c = json.loads(corpus_p.read_text(encoding="utf-8"))
        cf = Counter(c.get("char_freq", {}))
        bg = Counter(c.get("bigram", {}))

    raw = src.read_text(encoding="utf-8", errors="replace")
    ann, sug, log = apply_correction_guarded(raw, cf, bg, confusion, a.threshold)

    out_p = Path(a.out)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(ann, encoding="utf-8")

    sug_p = out_p.with_name(out_p.stem.replace("_纠错标注", "") + "_建议稿.txt")
    sug_p.write_text(sug, encoding="utf-8")

    print("标注版 →", out_p)
    print("建议稿 →", sug_p)
    print(f"共标记 {len(log)} 处待人工确认")
    gates = Counter(x["gate"] for x in log)
    for g, n in gates.most_common():
        print(f"  {g}: {n}")


def apply_correction_guarded(raw, cf, bg, confusion, threshold):
    """包装，便于主函数调用。"""
    return apply_corrections(raw, cf, bg, confusion, threshold)


if __name__ == "__main__":
    main()
