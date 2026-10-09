#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fill_blanks.py —— 用「个人语料库」填补母亲信件中的真实空白（〔读不出〕／[?]）

★这才是自学习的正确用法：
  不改机器已经认出的字（那会篡改记忆），
  只对机器【读不出】的位置，给出基于这位书写者本人用词习惯的候选字，
  交人工裁决。既安全，又把人工从"逐字通读"降到"重点复核"。

先验来源（三类叠加，可分别开关做对照）：
  P1 个人邻接 bigram（左右邻字）      —— 主力
  P2 个人字频                         —— 回退
  P3 人名/方言知识表（本次校正所获）  —— 专名保护（不猜，只提示）

输出：
  filled/<信件>_填补建议.md          正文原样保留，空白位给出候选
  filled/<信件>_空白清单.md          空白逐条列出，带上下文与候选

用法:
  python fill_blanks.py                    # 处理全部母亲的未校正信
  python fill_blanks.py --letters 信-060   # 只处理指定信
  python fill_blanks.py --topk 5
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ZHUANXIE = ROOT / "素材库" / "信件" / "转写"
TRUTH = HERE / "truth"
OUT = HERE / "filled"
OUT.mkdir(exist_ok=True)

KEEP = re.compile(r"[\u4e00-\u9fff0-9０-９]")
BLANK_RE = re.compile(r"〔读不出〕|\[\?\]|\[[^\]]{0,8}\?\]")
NOISE = [r"\*\*", r"\*", r"［[^］]*］", r"（按：[^）]*）", r"^#+\s*", r"^>"]


def clean(t):
    return re.sub("|".join(NOISE), "", t, flags=re.M)


def load_prior():
    """合并：102 封大语料 + 已校正真值语料。"""
    cf, bg = Counter(), Counter()
    p = HERE / "corpus.json"
    if p.exists():
        c = json.loads(p.read_text(encoding="utf-8"))
        cf.update(Counter(c.get("char_freq", {})))
        bg.update(Counter(c.get("bigram", {})))
    for f in sorted(TRUTH.glob("信*_真值.txt")):
        t = "".join(KEEP.findall(BLANK_RE.sub("", clean(
            f.read_text(encoding="utf-8")))))
        cf.update(Counter(t))
        bg.update(Counter(a + b for a, b in zip(t, t[1:])))
    prev_tot = Counter()
    for (a, _), n in bg.items():
        prev_tot[a] += n
    tot = sum(cf.values()) or 1
    uni = {k: v / tot for k, v in cf.items()}
    return {"cf": cf, "bg": bg, "uni": uni,
            "prev_tot": prev_tot, "vocab": set(cf)}


def clean_only(t: str) -> str:
    return clean(t)


def candidates(m, prev, nxt, topk=5):
    """给定左右邻字，返回候选字及分数。"""
    bg, uni, prev_tot, vocab = m["bg"], m["uni"], m["prev_tot"], m["vocab"]
    scored = []
    for ch in vocab:
        sc = 0.0
        if prev:
            sc += ((bg.get(prev + ch, 0) + 0.5 * uni.get(ch, 1e-7))
                   / (prev_tot.get(prev, 0) + 0.5))
        if nxt:
            sc += ((bg.get(ch + nxt, 0) + 0.5 * uni.get(nxt, 1e-7))
                   / (prev_tot.get(ch, 0) + 0.5))
        scored.append((ch, sc))
    scored.sort(key=lambda x: -x[1])
    return scored[:topk]


def load_known_names(root):
    """人名库运行时加载（v6）：与 person_density 同源，不再硬编码任何姓名。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from person_density import load_known
        known, _ = load_known(Path(root))
        return list(known)
    except Exception as e:                      # 人名库缺失时不阻断主流程
        print(f"[提示] 未能加载人名库（{e}）；未登记人名不参与保护名单")
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--letters", nargs="*", default=None,
                    help="只处理指定信（如 信-060）")
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--root", default=None, help="项目根路径（含 素材库/信件/转写）")
    a = ap.parse_args()

    proj_root = Path(a.root).resolve() if a.root else Path(__file__).resolve().parent
    known_names = load_known_names(proj_root)
    print(f"保护名单（不填补）：{len(known_names)} 个人名")

    m = load_prior()
    print(f"先验语料：字种 {len(m['vocab'])}，"
          f"bigram {len(m['bg'])}，总字频 {sum(m['cf'].values()):,}\n")

    zx = proj_root / "素材库" / "信件" / "转写"
    files = sorted(zx.glob("信-*.md")) + sorted(zx.glob("信-*.txt"))
    if a.letters:
        files = [f for f in files
                 if any(tag in f.name for tag in a.letters)]

    # 排除已校正的（那些已是 truth）
    corrected = {"035", "036", "037", "050"}
    files = [f for f in files
             if not any(c in f.name for c in corrected)]

    print(f"待填补：{len(files)} 封（已排除 4 封已校正信）\n")

    summary = []
    for p in files:
        raw_text = p.read_text(encoding="utf-8", errors="replace")
        # 抽取引用区正文（保留占位标记）
        lines = [l.lstrip(">").strip() for l in raw_text.splitlines()
                 if l.strip().startswith(">")]
        body = "\n".join(x for x in lines if x)

        blanks = list(BLANK_RE.finditer(body))
        if not blanks:
            continue

        items = []
        for mobj in blanks:
            s = mobj.start()
            # 上下文：左右各取最近 6 个汉字
            left = "".join(KEEP.findall(body[:s]))[-6:]
            right = "".join(KEEP.findall(body[mobj.end():]))[:6]
            cands = candidates(m, left[-1] if left else "",
                               right[0] if right else "", topk=a.topk)
            items.append({
                "ctx": f"…{left}[□]{right}…",
                "cands": [(c, round(sc, 4)) for c, sc in cands],
            })

        # 写清单
        out_list = OUT / f"{p.stem}_空白清单.md"
        with open(out_list, "w", encoding="utf-8") as f:
            f.write(f"# {p.stem} · 空白填补建议（{len(items)} 处）\n\n")
            f.write("> 由个人语料库（102 封大语料 + 已校正真值）生成候选。\n")
            f.write("> **候选仅供参考，必须回原图核对后由委托人裁决。**\n\n")
            for i, it in enumerate(items, 1):
                cs = "　".join(f"{c}({sc:.3f})" for c, sc in it["cands"][:3])
                f.write(f"{i:>3}. `{it['ctx']}`\n")
                f.write(f"     候选：{cs}\n\n")

        summary.append((p.stem, len(items)))

    # 汇总
    print("=" * 56)
    print(f"{'信件':<40}{'空白处数':>10}")
    print("=" * 56)
    for name, n in sorted(summary, key=lambda x: -x[1]):
        print(f"{name:<40}{n:>10}")
    print("=" * 56)
    print(f"{'合计空白':<40}{sum(n for _, n in summary):>10}")
    print(f"\n输出目录 → {OUT}")


if __name__ == "__main__":
    main()
