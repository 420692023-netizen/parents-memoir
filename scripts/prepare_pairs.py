#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepare_pairs.py —— 把「机器输出(raw)」与「人工真值(truth)」严格配对落盘

★关键校正（2026-10-06）：
  家书第01封原件 与 信50_p1原件 md5 相同 → 两者是同一封信。
  此前把信-050 当作「第02封」与家书001比对，属于张冠李戴，
  是上一轮 D22（-2.19pt）的真正根源。现按真实配对重建：

  组1 信-050 = 家书第01封（1983-09-16，2页）
       raw   ← drafts/A组_信050.txt（盲读，p1+p2）
       truth ← 家书001口述确认稿(p1) + 委托人本次校正的 p2
  组2 某封信 raw ← 素材库转写稿 / truth ← 委托人校正
  组3 信-036（1983-09-30）raw ← 素材库转写稿 p1 / truth ← 委托人校正(p1)
  组4 信-037（1983-10-08）raw ← 素材库转写稿 / truth ← 委托人校正
"""
from pathlib import Path
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent


def _find_root():
    """自适应定位项目根（素材库不在脚本上级目录时也能找到）"""
    if len(sys.argv) > 1:
        c = Path(sys.argv[1]).resolve()
        if (c / "素材库").is_dir():
            return c
    for base in (HERE, Path.cwd()):
        cur = base.resolve()
        for _ in range(5):
            if (cur / "素材库" / "信件" / "转写").is_dir():
                return cur
            cur = cur.parent
    return HERE.parent


ROOT = _find_root()
ZHUANXIE = ROOT / "素材库" / "信件" / "转写"
RAW = HERE / "raw"
TRUTH = HERE / "truth"
RAW.mkdir(exist_ok=True)
TRUTH.mkdir(exist_ok=True)


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


def write(path: Path, text: str):
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def main():
    # ★ v6：先做前置检查，缺素材时给**人话提示 + 退出码 2**，绝不甩 Python 堆栈
    if not ZHUANXIE.is_dir():
        print("!" * 70)
        print("【素材目录不存在】未找到信件转写目录：")
        print(f"  {ZHUANXIE}")
        print("  本脚本需要家传项目的素材库才能配对 raw/truth。请任选其一：")
        print("    ① cd 到项目根目录（含 素材库/信件/转写）后重跑；")
        print("    ② 或用 `python prepare_pairs.py <项目根路径>` 显式指定。")
        print("!" * 70)
        sys.exit(2)

    want = [("信-AAA", "信-AAA_母亲"), ("信-BBB", "信-BBB_母亲"),
            ("信-CCC", "信-CCC_母亲"), ("信-DDD", "信-DDD_母亲")]
    missing = []
    for code, prefix in want:
        if not any(ZHUANXIE.glob(f"{prefix}*.md")):
            missing.append(code)
    if len(missing) == len(want):
        print("!" * 70)
        print(f"【无可配对信件】{ZHUANXIE} 下未找到脚本需要的四封信："
              + "、".join(c for c, _ in want))
        print("  这些是本项目的基准测试信件（机器盲读 vs 人工真值）。")
        print("  若您的项目信件命名不同，请改脚本内的 want 列表；")
        print("  或先用 person_density.py / asset_inventory.py 建立素材清单。")
        print("!" * 70)
        sys.exit(2)
    if missing:
        print(f"[提示] 缺失部分信件（{len(missing)}/{len(want)}）：" + "、".join(missing)
              + " —— 跳过并继续。\n")

    def _read(code, prefix):
        """取该信转写稿；找不到返回空串（上面已统一检查，此处兜底）。"""
        fs = sorted(ZHUANXIE.glob(f"{prefix}*.md"))
        return fs[0].read_text(encoding="utf-8") if fs else ""

    results = []

    # ---------- 组1：信-050（＝家书第01封）raw ----------
    raw050 = extract_quoted(_read("050", "信-050_母亲"))
    write(RAW / "信AAA_盲读.txt", raw050)

    # ---------- 组2 ----------
    rawBBB = extract_quoted(_read("BBB", "信-BBB_母亲"))
    write(RAW / "信BBB_盲读.txt", raw035)

    # ---------- 组3：信-036 raw（只取 p1 段，与委托人校正范围一致） ----------
    txt036 = _read("036", "信-036_母亲")
    paras, cur = [], []
    for line in txt036.splitlines():
        s = line.strip()
        if s.startswith(">"):
            body = s.lstrip(">").strip()
            if body:
                cur.append(body)          # 有字 → 累积到当前段
            else:
                if cur:                   # 空引用行 → 段落分界
                    paras.append("\n".join(cur)); cur = []
        else:
            if cur:
                paras.append("\n".join(cur)); cur = []
    if cur:
        paras.append("\n".join(cur))

    # 委托人校正只覆盖 p1（抬头 + 邮包段 + 想念段 + 棉花段），裁掉 p2 未校正部分
    p1_only = []
    for p in paras:
        if p.startswith("（p2）"):
            break
        p1_only.append(p)
    write(RAW / "信CCC_盲读.txt", "\n\n".join(p1_only))

    # ---------- 组4：信-037 raw ----------
    raw037 = extract_quoted(_read("037", "信-037_母亲"))
    write(RAW / "信DDD_盲读.txt", raw037)

    # ---------- 输出统计 ----------
    print("=" * 62)
    print(f"{'组':<6}{'raw字数':>10}{'truth字数':>12}{'状态':>10}")
    print("=" * 62)
    for code in ("AAA", "BBB", "CCC", "DDD"):
        rp = RAW / f"信{code}_盲读.txt"
        tp = TRUTH / f"信{code}_真值.txt"
        if not rp.exists():
            print(f"信{code}  raw 缺失"); continue
        if not tp.exists():
            print(f"信{code}  truth 缺失"); continue
        rt = rp.read_text(encoding="utf-8")
        tt = tp.read_text(encoding="utf-8")
        rc = len(re.findall(r"[\u4e00-\u9fff0-9]", rt))
        tc = len(re.findall(r"[\u4e00-\u9fff0-9]", tt))
        ratio = rc / tc if tc else 0
        flag = "OK" if 0.6 <= ratio <= 1.4 else "★长度失衡"
        print(f"信{code}  {rc:>10}{tc:>12}{flag:>12}   (raw/truth={ratio:.2f})")
    print("=" * 62)


if __name__ == "__main__":
    main()
