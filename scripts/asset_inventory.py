#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
asset_inventory.py — 家庭数字资产盘点脚本（时光家传 Skill 配套）

两种模式：
  1) 默认模式：扫描指定文件夹（可递归），按 照片/音频/视频/文档 四类统计
     数量与体积，生成 Markdown 盘点表（《家庭数字资产档案》的数据来源）。
  2) --photos 模式：生成"照片登记表"——每张照片标 类型（原件/AI副本/视频）、
     AI 副本自动配对到原件、dHash 感知哈希查重复；并读取 `_人物登记册.md`
     （已确认人物"问一次、终身免问"，无册则输出建册骨架）。配合
     references/photo-archive.md 的"照片入传五步流程"使用。
  3) --docs 模式：生成"文档登记表"——SHA-256 精确查重（同一文件的重复副本）、
     去空白内容查重（同文异名/跨格式）、人物提及扫描（读 txt/md/docx 文本，
     对照 `_人物登记册.md` 与 `人名正字总表.md`，命中人名与误转形仅提示 [?]）。
     配合 references/document-archive.md 使用。

用法：
    python asset_inventory.py <文件夹路径> [--out 盘点表.md]
    python asset_inventory.py <照片目录> --photos [--out 照片登记表.md]
    python asset_inventory.py <文档目录> --docs [--out 文档登记表.md]

纯标准库实现（dHash 去重为 Pillow 可选增强；docx 文本抽取用内置 zipfile），
不联网、不上传任何数据，只读不写目标文件夹。
"""
import argparse
import os
import re
import sys
from datetime import datetime

CATEGORIES = {
    "照片": {".jpg", ".jpeg", ".png", ".heic", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".raw", ".dng"},
    "音频": {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".wma", ".amr"},
    "视频": {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".m4v", ".3gp"},
    "文档": {".txt", ".md", ".doc", ".docx", ".pdf", ".wps"},
}

# ★ AI 加工副本识别关键词（小写子串匹配；目录名含 AI 也算）
AI_KEYWORDS = [
    "topaz", "grok", "remini", "midjourney", "sdxl", "stable",
    "ai修图", "ai还原", "ai上色", "ai修复", "ai-enhance", "ai_enhance",
    "上色", "修图", "修复", "增强", "去噪",
    "enhance", "denoise", "faceai", "sharpen", "upscale", "remaster", "colorize",
]
# 目录命中只认完整 AI 关键词；不再用两个字母的 "ai" 子串，
# 否则 portrait / detail / email 这类普通英文目录会被误判成 AI 加工目录。

DUP_THRESHOLD = 5      # 汉明距离 ≤5 判"疑似重复"（dHash 或 pHash 任一命中）
SIM_THRESHOLD = 10     # pHash ≤10 判"相似组"（重拍/裁剪/上色候选，仅提示不结论）


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def phash(path: str):
    """8x8 pHash（DCT 感知哈希）。纯 Python 实现（不依赖 numpy/scipy），
    对亮度/对比度变化、重新压缩、适度裁剪比 dHash 更鲁棒。无 Pillow 时返回 None。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    import math
    N, K = 32, 8
    try:
        with Image.open(path) as im:
            g = im.convert("L").resize((N, N), Image.LANCZOS)
            px = list(g.getdata())
    except Exception:
        return None
    alpha = [math.sqrt(1.0 / N)] + [math.sqrt(2.0 / N)] * (N - 1)
    cos_t = [[math.cos((2 * i + 1) * u * math.pi / (2 * N)) for i in range(N)] for u in range(K)]
    # 分离式 2D DCT：先对每行做 1D DCT 取前 K 个系数，再对列方向取前 K 个
    rows = []
    for y in range(N):
        seg = px[y * N:(y + 1) * N]
        rows.append([alpha[u] * sum(cos_t[u][x] * seg[x] for x in range(N)) for u in range(K)])
    coeffs = []
    for u in range(K):
        col = [rows[y][u] for y in range(N)]
        coeffs.append([alpha[v] * sum(cos_t[v][y] * col[y] for y in range(N)) for v in range(K)])
    flat = [c for row in coeffs for c in row]
    med = sorted(flat)[len(flat) // 2]
    bits = 0
    for c in flat:
        bits = (bits << 1) | (1 if c > med else 0)
    return bits


def scan(root: str):
    stats = {cat: {"count": 0, "bytes": 0, "exts": {}} for cat in CATEGORIES}
    other = {"count": 0, "bytes": 0}
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            try:
                size = os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue
            matched = False
            for cat, exts in CATEGORIES.items():
                if ext in exts:
                    s = stats[cat]
                    s["count"] += 1
                    s["bytes"] += size
                    s["exts"][ext] = s["exts"].get(ext, 0) + 1
                    matched = True
                    break
            if not matched:
                other["count"] += 1
                other["bytes"] += size
    return stats, other


def render_markdown(root: str, stats, other) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# 家庭数字资产盘点表（{today}）",
        "",
        f"- 扫描目录：`{os.path.abspath(root)}`",
        "- 本表由 asset_inventory.py 本地生成，未上传任何数据",
        "",
        "| 类型 | 文件数 | 总大小 | 格式分布 |",
        "|---|---|---|---|",
    ]
    total_count = total_bytes = 0
    for cat, s in stats.items():
        exts = "、".join(f"{e}×{n}" for e, n in sorted(s["exts"].items())) or "—"
        lines.append(f"| {cat} | {s['count']} | {human_size(s['bytes'])} | {exts} |")
        total_count += s["count"]
        total_bytes += s["bytes"]
    lines.append(f"| 其他 | {other['count']} | {human_size(other['bytes'])} | — |")
    lines += [
        "",
        f"**合计**：{total_count + other['count']} 个文件，{human_size(total_bytes + other['bytes'])}",
        "",
        "## 备份自查（逐项确认）",
        "",
        "- [ ] 音频（访谈录音）是否已有两份以上副本（本地硬盘 + 云盘/U盘）？",
        "- [ ] 老照片是否已全部数字化（扫描件命名：人物_事件_日期）？",
        "- [ ] 视频是否为零？若是，下次访谈请改为录像，留住影像与神态。",
        "- [ ] 重要文件是否另有第三份副本，交由另一位家人保管？",
    ]
    return "\n".join(lines) + "\n"


# ======================================================================
# --photos 模式：照片登记表（原件/AI副本配对 + dHash 查重）
# ======================================================================

def _is_ai(path: str) -> bool:
    parts = re.split(r"[\\/]", path)
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    if any(k in stem for k in AI_KEYWORDS):
        return True
    # 父目录名命中完整 AI 关键词（如 02_AI加工版 / 05_AI动态还原）
    return any(any(k in p.lower() for k in AI_KEYWORDS) for p in parts[:-1])


def _pair_key(stem: str) -> str:
    """把文件名中的 AI 关键词、分隔符剥掉，得到配对键。"""
    s = stem.lower()
    for k in sorted(AI_KEYWORDS, key=len, reverse=True):
        s = s.replace(k, " ")
    s = re.sub(r"[-_.\s]+", " ", s).strip()
    return s


def dhash(path: str):
    """8x8 dHash（差值哈希）。无 Pillow 时返回 None。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            g = im.convert("L").resize((9, 8))
            px = list(g.getdata())
        bits = 0
        for row in range(8):
            for col in range(8):
                bits = (bits << 1) | (1 if px[row * 9 + col] > px[row * 9 + col + 1] else 0)
        return bits
    except Exception:
        return None


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# ★ 人物登记册：问一次、终身免问（格式见 references/photo-archive.md §五）
REGISTRY_FILENAME = "_人物登记册.md"
REGISTRY_SKELETON = """# 人物登记册（问一次、终身免问）

> 维护规则：委托人每亲认一位新人，追加一行；此后所有批次**先读本表**——
> 已入册者自动挂名（标注"据登记册"），勿重复询问；仅新面孔或对不上号者才问。

| 人物 | 首认照片 | 头像裁片 | 确认日期 | 备注 |
|---|---|---|---|---|
| （示例）示例人物 | 01_原件翻拍/IMG_xxx.jpg（某组·家人合照） | 06_人物头像/某某.jpg | 2026-01-01 | 示例行，可删 |
"""


def _load_registry(root: str):
    """在照片根目录及其上一级查找人物登记册，返回 (路径或None, 已确认人名列表)。"""
    here = os.path.abspath(root)
    candidates = [os.path.join(here, REGISTRY_FILENAME),
                  os.path.join(os.path.dirname(here), REGISTRY_FILENAME)]
    for p in candidates:
        if not os.path.isfile(p):
            continue
        names = []
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line.startswith("|"):
                        continue
                    cells = [c.strip() for c in line.strip("|").split("|")]
                    if not cells or not cells[0]:
                        continue
                    if set(cells[0]) <= set("-: "):   # 分隔行 |---|---|
                        continue
                    if cells[0] in ("人物", "姓名", "名字"):  # 表头行
                        continue
                    if cells[0].startswith("（"):      # 示例行等备注
                        continue
                    if cells[0] not in names:
                        names.append(cells[0])
        except OSError:
            continue
        return p, names
    return None, []


def build_photo_registry(root: str) -> str:
    photos, videos = [], []  # (relpath, size)
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            full = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            rel = os.path.relpath(full, root)
            if ext in CATEGORIES["照片"]:
                photos.append((rel, size))
            elif ext in CATEGORIES["视频"]:
                videos.append((rel, size))

    # ★ fail loud：空扫描必须报错，杜绝静默出空表
    if not photos and not videos:
        print(f"错误：目录中未找到任何照片/视频：{root}", file=sys.stderr)
        print("诊断：请确认路径正确、扩展名在支持列表内（jpg/png/heic/mp4 等）。", file=sys.stderr)
        sys.exit(2)

    originals = [(rel, size) for rel, size in photos if not _is_ai(rel)]
    ai_copies = [(rel, size) for rel, size in photos if _is_ai(rel)]

    # AI 副本 → 原件配对：配对键最长前缀匹配
    orig_keys = {os.path.splitext(os.path.basename(rel))[0]: rel for rel, _ in originals}
    pair_of = {}
    for rel, _ in ai_copies:
        key = _pair_key(os.path.splitext(os.path.basename(rel))[0])
        best, best_len = None, 0
        for ostem, orel in orig_keys.items():
            okey = _pair_key(ostem)
            n = len(os.path.commonprefix([key, okey]))
            if n > best_len:
                best, best_len = orel, n
        pair_of[rel] = best if best_len >= 4 else None

    # 双哈希查重与相似检测（Pillow 可用时）：dHash 抓精确重复，pHash 抓
    # 亮度/压缩/裁剪后的同一张（方法分层见 references/photo-archive.md §二）
    has_pillow = True
    try:
        import PIL  # noqa
    except ImportError:
        has_pillow = False
    dh, ph = {}, {}
    if has_pillow:
        for rel, _ in photos:
            full = os.path.join(root, rel)
            h1 = dhash(full)
            if h1 is not None:
                dh[rel] = h1
            h2 = phash(full)
            if h2 is not None:
                ph[rel] = h2

    def _dup_pair(a, b):
        """疑似重复：dHash 或 pHash 任一 ≤DUP_THRESHOLD。"""
        if a in dh and b in dh and _hamming(dh[a], dh[b]) <= DUP_THRESHOLD:
            return True
        return a in ph and b in ph and _hamming(ph[a], ph[b]) <= DUP_THRESHOLD

    def _sim_pair(a, b):
        """相似组：pHash ≤SIM_THRESHOLD 且未判为疑似重复。"""
        return (a in ph and b in ph
                and DUP_THRESHOLD < _hamming(ph[a], ph[b]) <= SIM_THRESHOLD)

    # 并查集：重复、相似必须分开聚类，不能共用一个 parent。
    # 否则 A 与 B 相似、B 与 C 重复时，A/B/C 会被串成一个组件，
    # 导致「重复组」里混入相似照片、「相似组」里混入重复照片。
    dup_parent, sim_parent = {}, {}

    def _make_find(parent):
        def _find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        return _find

    def _make_union(find_fn, parent):
        def _union(a, b):
            ra, rb = find_fn(a), find_fn(b)
            if ra != rb:
                parent[rb] = ra
        return _union

    dup_find = _make_find(dup_parent)
    sim_find = _make_find(sim_parent)
    dup_union = _make_union(dup_find, dup_parent)
    sim_union = _make_union(sim_find, sim_parent)

    dup_pairs, sim_pairs = [], []
    keys = [rel for rel, _ in photos if rel in dh or rel in ph]
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if _dup_pair(a, b):
                dup_pairs.append((a, b))
                dup_union(a, b)
            elif _sim_pair(a, b):
                sim_pairs.append((a, b))
                sim_union(a, b)

    def _groups(pairs, parent, find_fn):
        seen, groups = set(), []
        for a, b in pairs:
            for x in (a, b):
                r = find_fn(x)
                if r not in seen:
                    seen.add(r)
                    groups.append(sorted(m for m in parent if find_fn(m) == r))
        return groups

    dup_groups = _groups(dup_pairs, dup_parent, dup_find)
    sim_groups = _groups(sim_pairs, sim_parent, sim_find)

    # 内容级配对兜底：名字配不上的 AI 副本，用 dHash/pHash 找最相近的原件
    content_pair = {}
    if dh or ph:
        for rel, _ in ai_copies:
            if pair_of.get(rel) is None:
                best, best_d = None, 999
                for orel, _s in originals:
                    d = 999
                    if rel in dh and orel in dh:
                        d = _hamming(dh[rel], dh[orel])
                    if rel in ph and orel in ph:
                        d = min(d, _hamming(ph[rel], ph[orel]))
                    if d < best_d:
                        best, best_d = orel, d
                if best is not None and best_d <= 16:  # 内容匹配仅作提示，仍须人工确认
                    content_pair[rel] = best

    today = datetime.now().strftime("%Y-%m-%d")
    reg_path, reg_names = _load_registry(root)
    L = [
        f"# 照片登记表（{today}）",
        "",
        f"- 扫描目录：`{os.path.abspath(root)}`",
        f"- 照片 {len(photos)} 张（原件 {len(originals)} ／ AI 副本 {len(ai_copies)}），视频 {len(videos)} 段",
        f"- 查重引擎：{'dHash＋pHash（DCT，纯 Python）' if has_pillow else '未启用（未安装 Pillow，pip install pillow 后重跑）'}",
        "- 本表由 asset_inventory.py --photos 本地生成，未上传任何数据",
        "",
    ]

    # ★ 人物登记册状态（问一次、终身免问）
    L += ["## 〇、人物登记册", ""]
    if reg_names:
        reg_abs = os.path.abspath(reg_path)
        root_abs = os.path.abspath(root)
        rel_reg = os.path.relpath(reg_abs, root_abs) if reg_abs.startswith(root_abs) else reg_path
        L += [f"- ✅ 已入册 **{len(reg_names)}** 人（`{rel_reg}`）：" + "、".join(reg_names),
              "- 逐张判读时：已入册人物**自动挂名**（标注\"据登记册\"），**勿重复询问委托人**；",
              "- 仅新面孔、或与登记册对不上号（相似度低／年代矛盾）者，裁头像（存 `06_人物头像\\`）询问。",
              ""]
    else:
        L += ["- ⚠️ 尚无人物登记册——首轮判读请按以下流程建册：",
              "  ① 每张照片裁出人物头像（存 `06_人物头像\\`）→ ② 按相似度归簇 → "
              "③ 生成待认卡片（头像＋出现位置＋上下文线索）**一次性**请委托人辨认 → "
              "④ 答复写入 `_人物登记册.md` → ⑤ 此后批次先读册，已入册者不再问。",
              "",
              "**红线**：AI 首轮\"认识\"的只能是登记册里已有的人；对新面孔 AI 永远不认识，"
              "只能提示候选 `[?]`，第一次仍须委托人亲认后才入册。",
              "",
              "登记册骨架（复制保存为照片目录下 `_人物登记册.md`）：",
              "",
              "```markdown",
              REGISTRY_SKELETON.rstrip(),
              "```",
              ""]

    L += [
        "## 一、AI 副本配对",
        "",
        "| AI 副本 | 配对到的原件 | 体积 |",
        "|---|---|---|",
    ]
    unpaired = []
    for rel, size in ai_copies:
        o = pair_of.get(rel)
        if o:
            L.append(f"| `{rel}` | `{o}` | {human_size(size)} |")
        elif rel in content_pair:
            L.append(f"| `{rel}` | `{content_pair[rel]}`（内容匹配） | {human_size(size)} |")
        else:
            unpaired.append(rel)
            L.append(f"| `{rel}` | ⚠️ 未配对到原件 | {human_size(size)} |")
    if not ai_copies:
        L.append("| （无 AI 副本） | — | — |")
    if unpaired:
        L += ["", f"> ⚠️ {len(unpaired)} 个 AI 副本未配对到原件——请人工确认其原件是否缺失（扫描时漏拍/改名）。"]

    L += ["", "## 二、疑似重复（dHash／pHash 任一距离 ≤%d）" % DUP_THRESHOLD, ""]
    if not dup_groups:
        L.append("未发现疑似重复。" if has_pillow else "（未启用查重）")
    else:
        for i, grp in enumerate(dup_groups, 1):
            sizes = ", ".join(f"`{g}`" for g in grp)
            L.append(f"{i}. {sizes}")
        L += ["",
              "> ⚠️ 重复项仅报告、不删除；确认哪些是冗余前请委托人过目",
              ">（本项目教训：『多扫描了一页』曾被误判为『缺第 3 页』，结构错误要人裁决）。",
              "> 整理建议：每组保留最清晰／最完整的一张（原件优先），其余待确认后归档或删除。"]

    L += ["", "## 二·五、相似组（pHash 距离 %d–%d，非重复）" % (DUP_THRESHOLD + 1, SIM_THRESHOLD), ""]
    if not sim_groups:
        L.append("未发现相似组。")
    else:
        for i, grp in enumerate(sim_groups, 1):
            tagged = ", ".join(
                f"`{g}`（{'AI副本' if _is_ai(g) else '原件'}）" for g in grp)
            L.append(f"{i}. {tagged}")
        L += ["",
              "> 相似组＝同一画面的重拍／裁剪／上色／不同尺寸版本——**仅提示，不是结论**。",
              "> 已在 §一 配对到原件的 AI 副本无需再处理；组内**全是原件**时，疑为连拍或重复扫描，"
              "> 请委托人挑保留张；判断不了的按 `[?]` 留待逐张判读。"]

    L += ["", "## 三、全部照片清单", "",
          "| # | 文件 | 类型 | 配对原件 | 体积 | 人物候选[?] | 年代候选 | 备注 |",
          "|---|---|---|---|---|---|---|---|"]
    for i, (rel, size) in enumerate(photos, 1):
        typ = "AI副本" if _is_ai(rel) else "原件"
        pair = pair_of.get(rel, "—") if typ == "AI副本" else ""
        L.append(f"| {i} | `{rel}` | {typ} | {pair or '—'} | {human_size(size)} | `[?]` | `[?]` | |")
    L += ["", "## 四、视频清单", ""]
    if videos:
        for rel, size in videos:
            L.append(f"- `{rel}`（{human_size(size)}）")
    else:
        L.append("（无视频）")
    L += ["",
          "> 逐张判读与人物/年代候选填写，按 `references/photo-archive.md` 五步流程走；",
          "> 裁决权归委托人，AI 只出 `[?]` 候选。"]
    return "\n".join(L) + "\n"


# ======================================================================
# --docs 模式：文档登记表（哈希查重 + 人物提及扫描）
# ======================================================================

DOC_SKIP_DIRS = {".workbuddy", "__pycache__", ".git", "$RECYCLE.BIN", "System Volume Information"}
NAME_REGISTRY = "_人物登记册.md"
NAME_ZHENGZI = "人名正字总表.md"
# 误转形候选过滤：含这些字的片段不是人名（"已作废""待核""音记""注意区分"等）
_ALIAS_STOP_CHARS = set("废误待核置作勿记疑注写旧音笔原话书区另地")
_NAME_RUN = re.compile(r"[\u4e00-\u9fff]{2,5}")
_NAME_RUN_LONG = re.compile(r"[\u4e00-\u9fff]{2,8}")
# 表头行特征：≥2 个短单元格含表头关键词（防跨表表头被当数据行吞掉）
_HEADER_KW = ("正字", "误转", "异写", "勿用", "说明", "备注", "籍贯", "排行",
              "人物", "姓名", "出处", "身份", "日期", "待核", "存异", "原词", "写法")
# 称谓类别名黑名单：称谓随家族史实变化（如某日期前"大舅"指某人、之后指另一人），
# 提示"『大舅』疑为某人之误转"会违反称谓时间轴，一律不作别名提示
_RELATIVE_RE = re.compile(r"^[大小老二三四五六七八末]?[舅叔伯姑姨爷奶婆爸妈哥弟姐]{1,2}$")


def _is_header_row(cells) -> bool:
    hits = sum(1 for c in cells if len(c) <= 12 and any(k in c for k in _HEADER_KW))
    return hits >= 2


def _iter_doc_files(root: str):
    """递归收集文档类文件，跳过隐藏/内部目录。返回 [(rel, full, size, ext)]。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in DOC_SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext not in CATEGORIES["文档"]:
                continue
            if name.startswith("文档登记表"):
                continue   # 本脚本生成的报告，防止复跑时被当素材自吞
            full = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            out.append((os.path.relpath(full, root), full, size, ext))
    return out


def _sha256(path: str):
    import hashlib
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _extract_text(path: str, ext: str):
    """抽出可比较的文本。txt/md 直接读（utf-8→gbk 兜底）；
    docx 用内置 zipfile 读 word/document.xml 剥标签；doc/pdf/wps 不硬解析返回 None。"""
    if ext in (".txt", ".md"):
        for enc in ("utf-8", "gbk"):
            try:
                with open(path, encoding=enc) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
            except OSError:
                return None
        return None
    if ext == ".docx":
        import html as _html
        import zipfile
        try:
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
        except Exception:
            return None
        xml = xml.replace("</w:p>", "\n").replace("<w:tab/>", " ").replace("<w:br/>", "\n")
        return _html.unescape(re.sub(r"<[^>]+>", "", xml))
    return None


def _find_up(root: str, filename: str, max_up: int = 4):
    """先在 root 及其最多 max_up 级祖先目录找（照片目录→素材库 场景），
    找不到再向下全树找（项目根→素材库/人名正字总表 场景）。返回绝对路径或 None。"""
    here = os.path.abspath(root)
    for _ in range(max_up + 1):
        cand = os.path.join(here, filename)
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    for dirpath, dirnames, filenames in os.walk(os.path.abspath(root)):
        dirnames[:] = [d for d in dirnames if d not in DOC_SKIP_DIRS and not d.startswith(".")]
        if filename in filenames:
            return os.path.join(dirpath, filename)
    return None


def _load_zhengzi(path: str):
    """解析人名正字总表：正字列→人名，误转/异写列→alias→正字 映射。
    红线：~~删除线~~ 的废用名不入检索；过滤片段只做提示不做认定。"""
    names, aliases = [], {}
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("|"):
                    rows.append([c.strip() for c in line.strip("|").split("|")])
    except OSError:
        return names, aliases
    i = 0
    while i < len(rows):
        header = rows[i]
        # 正字列的表头须**严格**是"正字"（剥掉★与符号后）；"正字情况""正字依据"
        # 等叙述列表格是待核台账不是名册，整表跳过（其中的存疑名〔考?〕本不该入检索）
        canon_idx = next((j for j, c in enumerate(header)
                          if re.sub(r"[^\u4e00-\u9fff]", "", c) == "正字"), None)
        alias_idx = next((j for j, c in enumerate(header)
                          if "误转" in c or "异写" in c or "勿用" in c or "存异" in c), None)
        if canon_idx is None:
            i += 1
            continue
        j = i + 1
        while j < len(rows) and len(rows[j]) >= len(header):
            cells = rows[j]
            if _is_header_row(cells):          # 下一个表的表头被顺带吞进来的防线
                break
            if not set("".join(cells)) <= set("-: ★ "):     # 跳过分隔行
                canon_raw = cells[canon_idx] if canon_idx < len(cells) else ""
                canon_raw = cells[canon_idx] if canon_idx < len(cells) else ""
                runs = _NAME_RUN_LONG.findall(canon_raw) if (
                    "~~" not in canon_raw and canon_raw and not canon_raw.startswith("（")) else []
                name = ""
                if runs:
                    name = runs[0]
                    if name.endswith("舅舅"):
                        name = name[:-2]
                    elif name.endswith("舅"):
                        name = name[:-1]
                if name and (_RELATIVE_RE.match(name) or name in ("原词", "写法")):
                    name = ""
                if name:
                    if name not in names:
                        names.append(name)
                    if alias_idx is not None and alias_idx < len(cells):
                        for run in _NAME_RUN.findall(re.sub(r"~~.*?~~", "", cells[alias_idx])):
                            if (len(run) <= 4 and run != name and run not in names
                                    and not _RELATIVE_RE.match(run)
                                    and not (set(run) & _ALIAS_STOP_CHARS)):
                                aliases.setdefault(run, name)
            j += 1
        i = j
    return names, aliases


def build_doc_registry(root: str) -> str:
    docs = _iter_doc_files(root)
    if not docs:
        print(f"错误：目录中未找到任何文档文件：{root}", file=sys.stderr)
        print("诊断：请确认路径正确、扩展名在支持列表内（txt/md/docx/doc/pdf/wps）。", file=sys.stderr)
        sys.exit(2)

    # 人名来源：登记册 + 正字总表（向上找 4 级，覆盖"文档目录在素材库子目录"场景）
    src_files, canon_names, alias_map = set(), [], {}
    reg_path = _find_up(root, NAME_REGISTRY)
    reg_count = 0
    if reg_path:
        _, reg_names = _load_registry(os.path.dirname(reg_path))
        reg_count = len(reg_names)
        for n in reg_names:
            if n not in canon_names:
                canon_names.append(n)
        src_files.add(os.path.abspath(reg_path))
    zz_path = _find_up(root, NAME_ZHENGZI)
    zz_names, zz_alias_n = [], 0
    if zz_path:
        zz_names, zz_aliases = _load_zhengzi(zz_path)
        for n in zz_names:
            if n not in canon_names:
                canon_names.append(n)
        for k, v in zz_aliases.items():
            alias_map.setdefault(k, v)
        zz_alias_n = len(zz_aliases)
        src_files.add(os.path.abspath(zz_path))
    src_label = []
    if reg_path:
        src_label.append(f"`{NAME_REGISTRY}` {reg_count} 人")
    if zz_path:
        src_label.append(f"`{NAME_ZHENGZI}` {len(zz_names)} 人（含误转形 {zz_alias_n} 个）")
    if not src_label:
        src_label.append("⚠️ 未找到（人物扫描未启用）")

    # 抽文本 + 哈希
    entries = []   # dict: rel,size,ext,sha,ntext
    for rel, full, size, ext in docs:
        e = {"rel": rel, "size": size, "ext": ext,
             "sha": _sha256(full), "ntext": None}
        text = _extract_text(full, ext)
        if text is not None:
            e["ntext"] = re.sub(r"\s+", "", text)
        entries.append(e)

    def _group_by(key):
        buckets, order = {}, []
        for e in entries:
            k = e.get(key)
            if not k:
                continue
            if k not in buckets:
                buckets[k] = []
                order.append(k)
            buckets[k].append(e["rel"])
        return [buckets[k] for k in order if len(buckets[k]) > 1]

    exact_groups = _group_by("sha")
    # 内容重复：去空白后一致、但文件级哈希不同（同文异名/跨格式）
    exact_rels = {rel for grp in exact_groups for rel in grp}
    seen_norm = {}
    content_groups = []
    for e in entries:
        if e["ntext"] is None or e["rel"] in exact_rels:
            continue
        nh = e["ntext"][:20000]  # 超长文档截断比较，防极端性能
        if nh in seen_norm:
            for grp in content_groups:
                if seen_norm[nh] in grp:
                    grp.append(e["rel"])
                    break
            else:
                content_groups.append([seen_norm[nh], e["rel"]])
        else:
            seen_norm[nh] = e["rel"]

    # 人物提及扫描（仅提示）
    mentions = {}   # rel -> (canon_hits {name:count}, alias_hits {alias:canon})
    for e in entries:
        if e["ntext"] is None or os.path.abspath(os.path.join(root, e["rel"])) in src_files:
            continue
        hits, ahits = {}, {}
        for n in canon_names:
            c = e["ntext"].count(n)
            if c:
                hits[n] = c
        for a, canon in alias_map.items():
            if a in e["ntext"] and hits.get(canon, 0) == 0 and a not in hits:
                ahits[a] = canon
        if hits or ahits:
            mentions[e["rel"]] = (hits, ahits)

    today = datetime.now().strftime("%Y-%m-%d")
    n_readable = sum(1 for e in entries if e["ntext"] is not None)
    L = [
        f"# 文档登记表（{today}）",
        "",
        f"- 扫描目录：`{os.path.abspath(root)}`",
        f"- 文档 {len(entries)} 个（可读文本 {n_readable} ／ 待人工 {len(entries) - n_readable}：doc/pdf/wps 不硬解析）",
        f"- 人名来源：{'、'.join(src_label)}，合计待检人名 {len(canon_names)} 个",
        "- 本表由 asset_inventory.py --docs 本地生成，未上传任何数据",
        "",
        "## 〇、人名来源",
        "",
    ]
    if src_files:
        for p in sorted(src_files):
            L.append(f"- `{os.path.relpath(p, os.path.abspath(root)) if p.startswith(os.path.abspath(root)) else p}`")
    else:
        L.append("- ⚠️ 未找到 `_人物登记册.md` 或 `人名正字总表.md`——人物扫描未启用，仅出查重结果。")
    L += ["", "## 一、精确重复（SHA-256 完全一致）", ""]
    if not exact_groups:
        L.append("未发现精确重复。")
    else:
        for i, grp in enumerate(exact_groups, 1):
            L.append(f"{i}. " + ", ".join(f"`{g}`" for g in grp))
        L += ["", "> ⚠️ 重复项仅报告、不删除；保留哪份（通常留路径最规范的一份）请委托人确认。"]
    L += ["", "## 二、内容重复（去空白后一致——同文异名/跨格式）", ""]
    if not content_groups:
        L.append("未发现内容重复。")
    else:
        for i, grp in enumerate(content_groups, 1):
            L.append(f"{i}. " + ", ".join(f"`{g}`" for g in grp))
        L += ["", "> 同一封信的 .txt 与 .docx、或换行不同的两份转写稿会落在这里——"
              "属**同一内容的多份载体**，不是两个文档；请委托人指定正本，其余归档。"]
    L += ["", "## 三、人物提及扫描（仅提示 `[?]`，提及≠同一人）", ""]
    if not canon_names:
        L.append("（人名来源缺失，未扫描）")
    elif not mentions:
        L.append("未发现任何人名提及。")
    else:
        L += ["| 文件 | 命中人名（次数） | 误转形警示 `[?]` |", "|---|---|---|"]
        for rel in sorted(mentions, key=lambda r: -sum(mentions[r][0].values())):
            hits, ahits = mentions[rel]
            items = sorted(hits.items(), key=lambda kv: -kv[1])
            shown = "、".join(f"{n}×{c}" for n, c in items[:12])
            if len(items) > 12:
                shown += f" 等 {len(items)} 人"
            warn = "、".join(f"『{a}』疑为『{c}』之误转" for a, c in ahits.items()) or "—"
            L.append(f"| `{rel}` | {shown} | {warn} |")
        L += ["",
              "> **红线**：人名提及只说明「该文件里出现过这个名字」，**不代表就是本家同一位人物**"
              "（重名风险，如两位姓名相近但并非同一人）；误转形按正字总表提示更正方向，"
              "**原话照录区不改字**，裁决权归委托人。"]
    L += ["", "## 四、文档清单", "",
          "| # | 文件 | 文本 | 大小 | 提及人名数 |", "|---|---|---|---|---|"]
    for i, e in enumerate(entries, 1):
        n_hit = len(mentions.get(e["rel"], ({}, {}))[0])
        L.append(f"| {i} | `{e['rel']}` | {'可读' if e['ntext'] is not None else '待人工'} "
                 f"| {human_size(e['size'])} | {n_hit if e['rel'] in mentions else '—'} |")
    L += ["", "> 版本演进（如同名文档不同日期后缀）不属查重范围，属人工审读；"
          "本表只抓'完全相同/内容相同'与人物提及，不越界下结论。"]
    return "\n".join(L) + "\n"


def main():
    parser = argparse.ArgumentParser(description="家庭数字资产盘点（时光家传配套）")
    parser.add_argument("folder", help="要扫描的文件夹路径")
    parser.add_argument("--out", default=None, help="输出 Markdown 文件路径（默认打印到屏幕）")
    parser.add_argument("--photos", action="store_true",
                        help="照片登记表模式：原件/AI副本配对 + dHash 查重")
    parser.add_argument("--docs", action="store_true",
                        help="文档登记表模式：SHA-256/内容查重 + 人物提及扫描")
    args = parser.parse_args()

    if not os.path.isdir(args.folder):
        print(f"错误：目录不存在：{args.folder}", file=sys.stderr)
        sys.exit(1)

    if args.photos:
        md = build_photo_registry(args.folder)
    elif args.docs:
        md = build_doc_registry(args.folder)
    else:
        md = render_markdown(args.folder, *scan(args.folder))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"已生成：{args.out}")
    else:
        print(md)


if __name__ == "__main__":
    main()
