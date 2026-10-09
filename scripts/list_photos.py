#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
list_photos.py —— 输出「待校正原件照片文件名」清单

按 person_density 的优先队列顺序，从每封信的转写稿中抽取
「原件／原件照片／照片」字段里的 .jpg 文件名，并核对文件是否存在。
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from person_density import (find_root, extract_body, strip_brackets,
                            count_known, scan_title_anchor, scan_generation_tpl,
                            residual_names, detect_writer, load_known, load_corrected,
                            load_project_config, WRITER_BONUS,
                            letter_code, KEEP)
from collections import Counter

ROOT = find_root()
ZHUANXIE = ROOT / "素材库" / "信件" / "转写"
DIANBAO = ROOT / "素材库" / "电报" / "转写"
# 人名库/已校正清单均运行时外置（v5 起脚本不带内置数据）
KNOWN, FAMILY_SURNAMES = load_known(ROOT)
CORE = {"妈妈", "父亲", "爸爸", "婆婆", "公公", "外婆", "祖母"}
CORRECTED = load_corrected(ROOT)
WRITERS = load_project_config(ROOT)["writers"]
# 字辈模板：运行时由 --tpl/环境变量注入，留空则该通道关闭（家族内部字辈规则因人而异）
import os as _os
TPL_PATTERNS = [p for p in _os.environ.get("PM_TPL", "").split(",") if p.strip()]
IMG_DIRS = [ROOT / "素材库" / "信件", ROOT / "素材库" / "电报"]

IMG_RE = re.compile(r"[\w\u4e00-\u9fff\-（）()【】\[\]]{2,}\.(?:jpg|jpeg|png|JPG|JPEG|PNG)")

# 照片字段所在行的提示词
FIELD_HINT = ("原件", "照片", "扫描", "原图")


def build_index():
    """建立 文件名（小写）→ 绝对路径 索引，覆盖信件/电报目录及其子目录。"""
    idx = {}
    for d in IMG_DIRS:
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png"):
                idx.setdefault(p.name.lower(), p)
    return idx


def pick_photo_lines(md: str):
    """挑出含「原件/照片/扫描」且含图片文件名的行。"""
    out = []
    for line in md.splitlines():
        if any(h in line for h in FIELD_HINT) and IMG_RE.search(line):
            out.append(line.strip())
    return out


def photos_by_prefix(fname: str, idx: dict):
    """
    ★ 更稳的取法：直接按「信件编号前缀」在图片索引里捞。
    转写稿常写简写名（`p3_原件.jpg`）甚至措辞不一致
    （`信-027_母亲柳淑贞_1987-04-17` vs 照片 `信27_母亲_1987-04-17_...`），
    靠文本正则抓取极易漏。按编号前缀捞则不会错。
    """
    m = re.match(r"^(信|电报)-(\d{3})", fname)
    if not m:
        return []
    prefix = f"{m.group(1)}{int(m.group(2))}_"
    return sorted([p for k, p in idx.items() if k.startswith(prefix.lower())],
                  key=lambda x: x.name)


def resolve(fn: str, stem: str, idx: dict):
    """
    解析照片文件真实路径。转写稿里常写简写名（如 `p3_原件.jpg`），
    磁盘完整名带信件前缀但**措辞未必一致**（转写稿 `信-027_母亲柳淑贞_1987-04-17`，
    照片 `信27_母亲_1987-04-17_p3_原件.jpg` —— 少「柳淑贞」）。
    故三级查找：原名 → 主名+原名 → 编号前缀模糊匹配。
    """
    hit = idx.get(fn.lower())
    if hit:
        return hit, False
    if stem:
        hit = idx.get((stem + fn).lower())
        if hit:
            return hit, True
    # 编号前缀：信-027 → 信27_
    m = re.match(r"^(信|电报)-(\d{3})", stem or fn)
    if m:
        prefix = f"{m.group(1)}{int(m.group(2))}_"
        cands = [p for k, p in idx.items() if k.startswith(prefix.lower())
                 and p.name.lower().endswith(fn.lower().split("_")[-1])]
        # 退一步：同前缀且同为 .jpg 即算命中（限于该信页面照）
        if not cands:
            cands = [p for k, p in idx.items() if k.startswith(prefix.lower())]
        if len(cands) == 1:
            return cands[0], True
        if len(cands) > 1:
            return sorted(cands, key=lambda x: x.name)[0], True
    return None, False


def letter_stem(fname: str) -> str:
    """从转写稿文件名推出原件照片的前缀，如
    `信-xxx_母亲_某年某月某日.md` → `信xx_母亲_某年某月某日_`
    """
    base = re.sub(r"\.md$", "", fname)
    m = re.match(r"^(信|电报)-(\d{3})_(.*)$", base)
    if not m:
        return ""
    return f"{m.group(1)}{int(m.group(2))}_{m.group(3)}_"


def main():
    idx = build_index()
    files = sorted(ZHUANXIE.glob("信-*.md")) + sorted(DIANBAO.glob("电报-*.md"))

    rows = []
    for p in files:
        code = letter_code(p.name)
        if code in CORRECTED:
            continue
        md = p.read_text(encoding="utf-8", errors="replace")
        body, src = extract_body(md)
        nchars = len(KEEP.findall(body))
        if nchars < 30:
            continue
        clean = strip_brackets(body)
        kd = count_known(clean, KNOWN)
        pool = Counter(); pool.update(scan_title_anchor(clean, FAMILY_SURNAMES))
        pool.update(scan_generation_tpl(clean, TPL_PATTERNS, set(KNOWN)))
        seen = set(kd) | set(CORE)
        nf = Counter()
        for w, c in pool.items():
            if any(k in w for k in KNOWN) or w in seen: continue
            if w in CORE: continue
            stem = w
            for t in ("老师","校长","主任","叔叔","舅舅","哥哥","姐姐","同学","同志"):
                if w.endswith(t): stem = w[:len(w)-len(t)]; break
            if any(ch in "的了是在不为和有也要就没吗呢吧啊" for ch in stem) or not stem: continue
            if len(stem) > 2: continue
            nf[w] = c; seen.add(w)
        res = residual_names(clean, seen, KNOWN, FAMILY_SURNAMES)
        bonus = WRITER_BONUS.get(detect_writer(p.name, WRITERS), 0)
        rows.append({
            "file": p.name, "md": md, "chars": nchars, "src": src,
            "writer": detect_writer(p.name, WRITERS),
            "n_known": len(kd), "n_new": len(nf), "n_res": len(res),
            "score": len(nf)*3 + len(res) + len(kd) + bonus,
            "known": kd, "new": nf, "res": res,
        })

    rows.sort(key=lambda r: -r["score"])

    print("=" * 88)
    print("待校正 · 原件照片文件名（按人物密度优先队列排序）")
    print("=" * 88)

    missing_all = []
    for i, r in enumerate(rows[:15], 1):
        # 优先按编号前缀从磁盘捞；捞不到再退回转写稿里标注的名字
        hits = photos_by_prefix(r["file"], idx)
        imgs = []
        if hits:
            imgs = [p.name for p in hits]
            resolved = list(zip(imgs, [True] * len(imgs)))
        else:
            declared = []
            for ln in pick_photo_lines(r["md"]):
                for m in IMG_RE.finditer(ln):
                    fn = m.group(0)
                    if fn.lower() not in [x.lower() for x in declared]:
                        declared.append(fn)
            imgs = declared
            resolved = [(fn, False) for fn in declared]

        print(f"\n【{i}】{r['file']}")
        print(f"     写信：{r['writer']}｜字数 {r['chars']}｜分值 {r['score']}")
        if r["known"]:
            print(f"     已正字：{'、'.join(r['known'])}")
        if r["new"]:
            print(f"     新现名：{'、'.join(r['new'])}")
        if r["res"]:
            print(f"     待辨疑名：{'、'.join(list(r['res'])[:10])}")
        if imgs:
            for fn, _ in resolved:
                hit = idx.get(fn.lower())
                if hit:
                    print(f"     [OK ] {fn}")
                else:
                    print(f"     [⚠磁盘无此文件] {fn}")
                    missing_all.append((r["file"], fn))
        else:
            print("     （转写稿未标注原件照片文件名）")

    print()
    print("=" * 88)
    if missing_all:
        print(f"⚠️ 转写稿中标注但磁盘上找不到的文件：{len(missing_all)} 个")
        for f, fn in missing_all:
            print(f"   - {fn}   （见于 {f}）")
    else:
        print("✅ 清单中所有标注的照片文件均能在 素材库/信件、素材库/电报 下找到")
    print(f"磁盘已索引图片总量：{len(idx)}")


if __name__ == "__main__":
    main()
