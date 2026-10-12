#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
person_density.py —— 家信「人物密度／校正价值」扫描器（v6 · 人名库与项目配置全外置版）

★ 用途
  找出【第三方人物最密集、待正字人名最多】的家信，优先交委托人人工校正。
  方法论依据：语料规模已被证伪为杠杆（学习曲线平坦），
  而「人物关系知识」是本项目唯一被验证的复利资产。

★ v5 的核心变化：零内置数据（2026-10-08 隐私整改）
  ───────────────────────────────────────────────
  v4 及以前把某个人物库硬编码进脚本（KNOWN 字典 + 已校正清单 + 字辈模板）。
  发布后暴露双重危害：
    ① 隐私随包公开 —— 人物库本身就是家传成品；
    ② 对读者无效 —— 读者家的信里不会有这些名字，反而可能把同名者误判。
  v5 起：一切人名数据在**运行时**从用户自己项目的素材库加载：
    - 正字人名 ＋ 误转形别名 ← `素材库/**/人名正字总表.md`
    - 登记册人物             ← `素材库/**/照片/_人物登记册.md`
    - 已校正信件编号         ← `素材库/校正进度.txt`（可选，每行一个编号）
  找不到人名库 → fail-loud 报错并给建库指引，**绝不带默认库静默运行**。
  ───────────────────────────────────────────────

★ 历史版本踩过的坑（保留作方法论记录）
  v1：KNOWN 值混用 tuple/str → 解包异常中断整封信统计 → 大量 0 人。
  v2：改用「扫全文」→ 把整理者注里的正字也计入，虚高。
  v3：只扫引用区 + 姓氏驱动抓候选 →
      ① 姓氏表用《百家姓》全文，把「有/都/高/时/方/和/常/商」等常用字算作姓，
         炸出「乐室×1」「习惯×1」这类垃圾；
      ② 更致命：早期格式的信**正文不带 `>` 引用标记**，被整批跳过
         —— 直接导致「信-030 显示 0 人」的假象。
  v4 的两项修正（v5 继承）：
    修正一 · 正文抽取：引用区优先，无引用区则剥离元数据取正文（格式自适应）。
    修正二 · 人名识别：三通道强信号（称谓锚点 / 字辈模板 / 正字库匹配），
             取消「任意姓 + 1~2 字」的宽扫描。
             未登记的真人名由「残留疑名」单独列出待认。

用法：
    python person_density.py <项目根路径>
        [--mother 母亲名] [--father 父亲名] [--dear 委托人名]
        [--tpl 正则1,正则2,...]      # 字辈模板，如 "张.华,李建."
    项目根 = 含 素材库/信件/转写 的目录。

纯标准库，只读信件转写目录，产物写到项目根。
"""
import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
NAME_ZHENGZI = "人名正字总表.md"
NAME_REGISTRY = "_人物登记册.md"
NAME_PROGRESS = "校正进度.txt"
PROJECT_CONFIG = "项目配置.md"

KEEP = re.compile(r"[\u4e00-\u9fff0-9０-９]")
_NAME_RUN_LONG = re.compile(r"[\u4e00-\u9fff]{2,8}")
_RELATIVE_RE = re.compile(r"^[大小老二三四五六七八末]?[舅叔伯姑姨爷奶婆爸妈哥弟姐]{1,2}$")
_ALIAS_STOP_CHARS = set("废误待核置作勿记疑注写旧音笔原话书区另")


# ══════════════════════════════════════════════════════════════
# 一、人名库外置加载
# ══════════════════════════════════════════════════════════════

def find_file(root: Path, filename: str) -> Path | None:
    """在 root 全树找文件（跳过隐藏目录）。

    Python 3.9 兼容：Path.walk() 到 3.12 才有，这里统一用 os.walk。
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if filename in filenames:
            return Path(dirpath) / filename
    return None


def _is_header_row(cells) -> bool:
    kw = ("正字", "误转", "异写", "勿用", "说明", "备注", "籍贯", "排行",
          "人物", "姓名", "名字", "出处", "身份", "日期", "待核", "存异", "词目")
    return sum(1 for c in cells if len(c) <= 12 and any(k in c for k in kw)) >= 2


def load_zhengzi(path: Path):
    """解析正字总表：返回 (正字名列表, 误转形→正字 映射)。
    红线：~~删除线~~ 废用名不入检索；〔考?〕存疑名所在叙述表整表跳过。"""
    names, aliases = [], {}
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip("|").split("|")])
    i = 0
    while i < len(rows):
        header = rows[i]
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
            if _is_header_row(cells):
                break
            if not set("".join(cells)) <= set("-: ★ "):
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
                        for run in re.findall(r"[\u4e00-\u9fff]{2,5}",
                                              re.sub(r"~~.*?~~", "", cells[alias_idx])):
                            if (len(run) <= 4 and run != name and run not in names
                                    and not _RELATIVE_RE.match(run)
                                    and not (set(run) & _ALIAS_STOP_CHARS)):
                                aliases.setdefault(run, name)
            j += 1
        i = j
    return names, aliases


def load_registry(path: Path):
    """解析人物登记册：返回人物名列表（跳过表头/分隔/示例行）。"""
    names = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells or cells[0] in ("", "人物", "姓名", "名字") or set("".join(cells)) <= set("-: "):
            continue
        m = re.match(r"^[\u4e00-\u9fff]{2,4}$", cells[0])
        if m and cells[0] not in ("示例", "人物"):
            names.append(cells[0])
    return names


def load_known(root: Path):
    """从项目素材库加载人名库（fail-loud）。返回 (known: dict 名→出处, surnames: set)。"""
    known = {}
    zz = find_file(root, NAME_ZHENGZI)
    if zz:
        names, aliases = load_zhengzi(zz)
        for n in names:
            known.setdefault(n, f"正字总表")
        for a, n in aliases.items():
            known.setdefault(a, f"误转形→{n}")
    reg = find_file(root, NAME_REGISTRY)
    if reg:
        for n in load_registry(reg):
            known.setdefault(n, "人物登记册")
    if not known:
        print("!" * 78)
        print("【无法运行】未找到任何人名库 —— v5 起本脚本不带内置数据。")
        print(f"  在以下位置找 `{NAME_ZHENGZI}` 或 `照片/{NAME_REGISTRY}`：{root}")
        print("  若尚未建档：请先与委托人整理《人名正字总表》（正字/误转形两列即可），")
        print("  或运行 asset_inventory.py --photos 生成人物登记册骨架。")
        print("!" * 78)
        sys.exit(2)
    surnames = {n[0] for n in known if len(n) >= 2}
    return known, surnames


def load_project_config(root: Path) -> dict:
    """
    加载 `素材库/项目配置.md` —— **用户自己的**项目参数（脚本不带任何默认真值）。

    ★ 为什么需要这个文件（v6，2026-10-08）：
      v5 把人名库外置了，但「字辈模板」「写信人→关系映射」仍靠命令行参数传，
      结果脱敏版与原版功能差距很大（字辈误字检测失效、写信人退化为"他人"）。
      把它们也外置成**项目侧配置文件**，一份文件同时解决三件事：
        ① 发布包零真实数据（读者环境读到空配置 → 对应通道自动关闭）；
        ② 委托人自己的项目把真值填进去 → 功能一点不损失；
        ③ 换项目只需换这一份文件，不必改脚本。

    文件格式（表格或 YAML 皆可，最简是每行一条）：
        ## 字辈模板
        某.某
        某某.
        ## 写信人
        某某某 = 母亲
        某某某 = 父亲
        某某某 = 委托人
        ## 已校正
        信-000    已校正入库
    """
    cfg = {"tpl": [], "writers": {}, "corrected": {}}
    p = root / "素材库" / PROJECT_CONFIG
    if not p.is_file():
        return cfg
    section = ""
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        # 注意：`##` 是段名，`#` 开头才是注释（先判段名，否则全部内容会被当注释丢掉）
        if s.startswith("##"):
            section = s.lstrip("#").strip()
            continue
        if not s or s.startswith("#"):
            continue
        if "=" in s and section in ("写信人", "已校正"):
            k, v = s.split("=", 1) if section == "写信人" else s.split(None, 1)
            if section == "写信人":
                cfg["writers"][k.strip()] = v.strip()
            else:
                cfg["corrected"][k.strip()] = v.strip() or "已校正入库"
        elif section == "字辈模板":
            cfg["tpl"].append(s)
        elif section == "已校正":
            parts = s.split(None, 1)
            cfg["corrected"][parts[0]] = parts[1] if len(parts) > 1 else "已校正入库"
    return cfg


def load_corrected(root: Path) -> dict:
    """已校正信件编号（可选）。
    优先读 `素材库/项目配置.md` 的「已校正」段；
    兼容旧版 `素材库/校正进度.txt`（每行一个编号，`#` 为注释）。"""
    out = dict(load_project_config(root)["corrected"])
    p = root / "素材库" / NAME_PROGRESS
    if p.is_file():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            parts = s.split(None, 1)
            out.setdefault(parts[0], parts[1] if len(parts) > 1 else "已校正入库")
    return out


# ══════════════════════════════════════════════════════════════
# 二、正文抽取（v4 修正一，格式自适应）
# ══════════════════════════════════════════════════════════════

NOTE_HEADINGS = (
    "存疑标注", "素材价值", "校注与存疑", "校注", "存疑与待确认", "存疑",
    "待确认", "整理者注", "注释", "说明", "价值", "归位",
)


def extract_body(md: str) -> tuple[str, str]:
    """优先取 `>` 引用区（最纯净的盲读原文）；否则剥离元数据取正文（早期格式信）。"""
    lines = md.splitlines()
    quoted = []
    for line in lines:
        s = line.strip()
        if s.startswith(">"):
            s = s.lstrip(">").strip()
            if s:
                quoted.append(s)
    if quoted:
        return "\n".join(quoted), "引用区"
    body, in_note = [], False
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if re.match(r"^#{1,4}\s*(.*)$", s):
            head = re.match(r"^#{1,4}\s*(.*)$", s).group(1)
            in_note = any(k in head for k in NOTE_HEADINGS)
            continue
        if in_note:
            continue
        if re.match(r"^[-*]\s*\*\*[^*]{2,10}\*\*\s*[：:]", s):
            continue
        if re.match(r"^[-*]\s*\*\*\s*$", s):
            continue
        if s.startswith("|"):
            continue
        if re.match(r"^\d+\.\s+\*\*", s):
            continue
        body.append(s)
    return "\n".join(body), "剥离正文"


def strip_brackets(text: str) -> str:
    """去掉 [?] 等校注括号，保留文字骨架。"""
    return re.sub(r"[\[\]【】]", "", text)


# ══════════════════════════════════════════════════════════════
# 三、三通道人名识别（v4 修正二）
# ══════════════════════════════════════════════════════════════

PREFIX_VERBS = set(
    "当到有因做是让请给被把从在为要说找托问喊叫送寄带拿"
    "没有几位其他各位全体一些许多这些那些每个几个两个一个"
    "位个名老大小新老前后左右"
)
PREFIX_RE = re.compile("[" + re.escape("".join(PREFIX_VERBS)) + "]+")

COMMON_NAME_CHARS = set(
    "玉珊桂英凤珍秀芳萍红梅菊华荣富贵康健民国庆和平安"
    "文武斌杰俊伟刚强勇军建国家顺昌茂盛林森松柏青云飞"
    "志明光耀辉亮海洋江河流域湖溪泉源淼"
    "忠义礼智信仁爱孝敬慈祥瑞兆嘉良优良美"
    "金银宝珠玉环佩琪琦琳琅珊"
)

TITLES = ["老师", "校长", "医生", "师傅", "主任", "书记", "队长", "会计", "厂长",
          "叔叔", "伯伯", "大伯", "舅舅", "娘舅", "阿姨", "婶婶", "婶娘",
          "哥哥", "姐姐", "弟弟", "妹妹", "婆婆", "公公", "奶奶", "爷爷",
          "同志", "同学", "老老", "姑父", "姑妈", "大妈", "舅妈"]

STOP = {
    "家里", "人家", "大家", "自己", "别人", "有的", "没有", "就是", "可以",
    "我们", "你们", "他们", "什么", "怎么", "这样", "那样", "时候", "现在",
    "以后", "以前", "一直", "还是", "并且", "如果", "因为", "所以", "但是",
    "然后", "已经", "就要", "还要", "不要", "不会", "不能", "多少", "几个",
    "两个", "一个", "这个", "那个", "这边", "那边", "孙女", "孙子", "儿子",
    "女儿", "父母", "兄弟", "姐妹", "夫妻", "先生", "女士", "朋友", "人们",
    "老人", "病人", "春天", "夏天", "秋天", "冬天", "今年", "去年", "明年",
    "前年", "上午", "下午", "晚上", "中午", "今天", "昨天", "明天", "后天",
    "东西", "地方", "事情", "办法", "问题", "情况", "学校", "大队", "小队",
    "生产队", "公社", "城里", "乡下", "全家", "卫生", "后勤", "工业",
}

TAIL_BLACKLIST = set("埭队岱垈桥河头家姓的是为不有了吗呢吧啊很就把被从对与并还要都年月日在时分元钱斤亩里外上下中个们来去大小多少好坏新老")
FUNCTION_CHARS = set("的了是在不为和有也要就没吗呢吧啊")
TAIL_TITLE_CHARS = set("舅叔姨哥姐弟妹娘爷奶婆公爸妈伯婶姑嫂")
_FILLER_CHARS = (
    TAIL_TITLE_CHARS | FUNCTION_CHARS | TAIL_BLACKLIST
    | set("说到带来的去有着会不会能不能了过把被从对与并还就要都年月日时分")
    | set("先问现前后次封给送来走走进进出出回开关心意")
    | set("在正刚才天常年今明昨再又也就")
)


def scan_title_anchor(clean: str, surnames: set) -> Counter:
    """S1：X + 称谓（最强信号）。动词/虚词前缀拦截，防「当校长」误报。"""
    hits = Counter()
    for t in sorted(TITLES, key=len, reverse=True):
        for m in re.finditer(r"[\u4e00-\u9fff]{1,3}" + re.escape(t), clean):
            w = m.group(0)
            stem = w[: len(w) - len(t)]
            if not stem or stem in STOP:
                continue
            if any(c in FUNCTION_CHARS for c in stem):
                continue
            if stem[-1] in TAIL_BLACKLIST:
                continue
            core = PREFIX_RE.sub("", stem)
            if not core or core in STOP or len(core) > 2:
                continue
            if any(c in FUNCTION_CHARS for c in core):
                continue
            if core[-1] in TAIL_BLACKLIST:
                continue
            if not (core[0] in surnames or core[0] in COMMON_NAME_CHARS):
                continue
            hits[core + t] += 1
    return hits


def scan_generation_tpl(clean: str, tpl_pats: list, stop: set) -> Counter:
    """S2：字辈模板（--tpl 参数注入，如 "张.华,李建."）。家族内部精确信号。

    非法正则只跳过该条并告警，不让一个拼写错误中断整批扫描。
    """
    hits = Counter()
    for p in tpl_pats:
        try:
            pat = re.compile(p)
        except re.error as e:
            print(f"[警告] 字辈模板不是合法正则，已跳过：{p!r}（{e}）", file=sys.stderr)
            continue
        for m in pat.finditer(clean):
            w = m.group(0)
            if w in stop or w in STOP:
                continue
            if any(c in FUNCTION_CHARS for c in w):
                continue
            if w[-1] in TAIL_BLACKLIST:
                continue
            hits[w] += 1
    return hits


def count_known(clean: str, known: dict) -> Counter:
    """S3：正字库匹配（长名优先 + 子串扣除）。"""
    detail = Counter()
    for name in sorted(known, key=len, reverse=True):
        n = clean.count(name)
        if n:
            detail[name] = n
    names = list(detail)
    for i, a in enumerate(names):
        for b in names[:i]:
            if a in b:
                detail[a] = max(0, detail[a] - detail[b])
    return Counter({k: v for k, v in detail.items() if v > 0})


def _collapse_to_known(word: str, known: dict) -> str:
    """把「已知人名 + 后邻虚词/称谓」的切分碎片回退到已知人名
    （v3 教训：「世安舅」不是新人名）。"""
    best = None
    for k in known:
        if len(k) >= 2 and word.startswith(k):
            if best is None or len(k) > len(best):
                best = k
    if best:
        rest = word[len(best):]
        if rest and all(ch in _FILLER_CHARS for ch in rest):
            return best
    return word


def residual_names(clean: str, seen: set, known: dict, surnames: set) -> Counter:
    """残留疑名：本家姓氏开头 + 1~2 字、未被三通道捕获 → 供委托人辨认。"""
    c = Counter()

    def add(word: str):
        word = _collapse_to_known(word, known)
        if len(word) < 2 or word in seen or word in STOP:
            return
        if any(ch in FUNCTION_CHARS for ch in word):
            return
        if word[-1] in TAIL_BLACKLIST:
            return
        c[word] += 1

    for sur in surnames:
        for m in re.finditer(re.escape(sur) + r"[\u4e00-\u9fff]{1,2}", clean):
            add(m.group(0))
    return c


# ══════════════════════════════════════════════════════════════
# 四、写信人识别（人名来自 --mother/--father/--dear 参数）
# ══════════════════════════════════════════════════════════════

def detect_writer(fname: str, writers: dict) -> str:
    """
    从文件名推断写信人，返回 母亲/父亲/委托人/家人/亲戚/他人。

    ★ v6：映射关系来自**项目配置**（"人名 = 关系"），脚本不带任何真实姓名；
      未命中映射时按称谓与文件名线索兜底（母亲/父亲/…致…/亲属称谓）。
    """
    base = fname
    for name, role in writers.items():
        if name and name in base:
            return role
    if re.search(r"母亲|妈妈", base):
        return "母亲"
    if re.search(r"父亲|爸爸", base):
        return "父亲"
    if re.search(r"舅|表|姑|姨|婶", base):
        return "亲戚"
    if re.search(r"致", base):
        return "委托人"
    return "他人"


WRITER_BONUS = {"母亲": 8, "父亲": 4, "家人": 2, "亲戚": 2, "委托人": 0, "他人": 0}

CODE_RE = re.compile(r"(信|电报)-(\d{3})")


def letter_code(fname: str) -> str:
    m = CODE_RE.search(fname)
    return f"{m.group(1)}-{m.group(2)}" if m else fname


# ══════════════════════════════════════════════════════════════
# 五、主流程
# ══════════════════════════════════════════════════════════════

def find_root() -> Path:
    for base in (Path.cwd(), HERE):
        cur = base.resolve()
        for _ in range(5):
            if (cur / "素材库" / "信件" / "转写").is_dir():
                return cur
            cur = cur.parent
    return Path.cwd()


def main():
    ap = argparse.ArgumentParser(description="家信人物密度/校正价值扫描器 v6（配置与人名库全外置）")
    ap.add_argument("root", nargs="?", default=None, help="项目根路径（含 素材库/信件/转写）")
    ap.add_argument("--mother", default="", help="母亲姓名（覆盖项目配置）")
    ap.add_argument("--father", default="", help="父亲姓名（覆盖项目配置）")
    ap.add_argument("--dear", default="", help="委托人姓名（覆盖项目配置）")
    ap.add_argument("--tpl", default="", help="字辈模板正则，逗号分隔（覆盖项目配置）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else find_root()
    zhuaxie = root / "素材库" / "信件" / "转写"
    dianbao = root / "素材库" / "电报" / "转写"

    known, surnames = load_known(root)
    cfg = load_project_config(root)
    corrected = load_corrected(root)
    # 参数覆盖配置文件（命令行 > 项目配置）
    tpl_pats = [p.strip() for p in args.tpl.split(",") if p.strip()] or cfg["tpl"]
    writers = dict(cfg["writers"])
    for k, v in (("母亲", args.mother), ("父亲", args.father), ("委托人", args.dear)):
        if v:
            writers[v] = k

    cfg_path = root / "素材库" / PROJECT_CONFIG
    print("=" * 96)
    print(f"项目配置：{cfg_path if cfg_path.is_file() else '（未找到，对应通道关闭）'}")

    files = sorted(zhuaxie.glob("信-*.md")) + sorted(dianbao.glob("电报-*.md"))
    if not files:
        print("!" * 78)
        print(f"【严重】未找到任何信件转写（{zhuaxie}）—— 根目录定位失败或目录为空。")
        print("  请 cd 到素材库所在的项目根目录后重跑，或显式指定根路径。")
        print("!" * 78)
        sys.exit(2)

    # 核心称谓（每封必现，无区分度；人名核心由 KNOWN 承担）
    core = {"妈妈", "父亲", "爸爸", "婆婆", "公公", "外婆", "祖母"}

    rows, skipped, excluded = [], [], []
    global_res = Counter()
    res_docs = defaultdict(set)

    for p in files:
        code = letter_code(p.name)
        if code in corrected:
            excluded.append((p.name, corrected[code]))
            continue
        md = p.read_text(encoding="utf-8", errors="replace")
        body, src = extract_body(md)
        nchars = len(KEEP.findall(body))
        if nchars < 30:
            skipped.append((p.name, nchars, src))
            continue

        clean = strip_brackets(body)
        kd = count_known(clean, known)
        ta = scan_title_anchor(clean, surnames)
        gt = scan_generation_tpl(clean, tpl_pats, set(known))

        seen = set(kd) | core
        newfound = Counter()
        pool = Counter()
        pool.update(ta)
        pool.update(gt)
        for w, c in pool.items():
            if any(k in w for k in known) or w in seen:
                continue
            if w in STOP or any(ch in FUNCTION_CHARS for ch in w):
                continue
            stem = w
            for t in sorted(TITLES, key=len, reverse=True):
                if w.endswith(t):
                    stem = w[: len(w) - len(t)]
                    break
            if not stem:
                continue
            if any(ch in PREFIX_VERBS for ch in stem):
                continue
            if len(re.findall(r"[\u4e00-\u9fff]", stem)) > 2:
                continue
            newfound[w] = c
            seen.add(w)

        res = residual_names(clean, seen, known, surnames)
        for w, c in res.items():
            global_res[w] += c
            res_docs[w].add(p.name)

        writer = detect_writer(p.name, writers)
        bonus = WRITER_BONUS.get(writer, 0)
        rows.append({
            "file": p.name, "path": p, "src": src, "chars": nchars, "writer": writer,
            "n_known": len(kd), "m_known": sum(kd.values()),
            "n_new": len(newfound), "m_new": sum(newfound.values()),
            "n_res": len(res), "m_res": sum(res.values()),
            "score": len(newfound) * 3 + len(res) * 1 + len(kd) * 1 + bonus,
            "density": (len(newfound) + len(res) + len(kd)) / nchars * 1000,
            "known": kd, "new": newfound, "res": res,
        })

    rows.sort(key=lambda r: (-r["score"], -r["n_new"], -r["density"]))

    print("=" * 96)
    print("家信「人物密度／校正价值」排名 —— v6（人名库与项目配置全外置）")
    print(f"人名库：{len(known)} 条（正字总表 + 人物登记册）｜字辈模板：{len(tpl_pats)} 条｜已校正：{len(corrected)} 封")
    print("=" * 96)
    print(f"{'#':<4}{'信件':<36}{'字数':>6}{'已知':>5}{'新现':>5}{'疑名':>5}{'分值':>5}  {'写信人':<12}来源")
    print("-" * 96)
    for i, r in enumerate(rows[:30], 1):
        print(f"{i:<4}{r['file'][:34]:<36}{r['chars']:>6}{r['n_known']:>5}"
              f"{r['n_new']:>5}{r['n_res']:>5}{r['score']:>5}  {r['writer']:<12}{r['src']}")

    print()
    print("=" * 96)
    print("TOP 15 明细")
    print("=" * 96)
    for i, r in enumerate(rows[:15], 1):
        print(f"\n[{i}] {r['file']}  （{r['src']}，{r['chars']} 字，写信 {r['writer']}，分值 {r['score']}）")
        if r["known"]:
            print(f"    已知：{'、'.join(f'{k}×{v}' for k, v in r['known'].most_common())}")
        if r["new"]:
            print(f"    新现：{'、'.join(f'{k}×{v}' for k, v in r['new'].most_common(14))}")
        if r["res"]:
            print(f"    疑名：{'、'.join(f'{k}×{v}' for k, v in r['res'].most_common(14))}")

    print()
    print("=" * 96)
    print("全库高频「残留疑名」（≥2 次；很可能是未登记的真人名，请优先辨认）")
    print("=" * 96)
    hot = [(w, c, len(res_docs[w])) for w, c in global_res.most_common() if c >= 2]
    if hot:
        print(f"{'疑名':<12}{'总次':>6}{'涉信数':>8}")
        print("-" * 96)
        for w, c, d in hot[:60]:
            print(f"{w:<12}{c:>6}{d:>8}")
    else:
        print("（无）")

    print()
    print(f"[统计] 纳入 {len(rows)} 封｜排除 {len(excluded)} 封（已校正）"
          f"｜跳过 {len(skipped)} 封（正文<30字）")
    if not rows:
        print("!" * 78)
        print("【严重】纳入 0 封 —— 极可能是根目录定位失败或全部被排除。")
        print("!" * 78)
        sys.exit(2)

    # ── 报告 ──
    outdir = root if (root / "素材库").is_dir() else HERE
    L = [
        "# 待校正：人物高密度家信（优先队列）",
        "",
        f"> 脚本：`person_density.py` v5 ｜ 生成时间：{datetime.now():%Y-%m-%d %H:%M}",
        ">",
        "> **排序依据**：校正价值分值 = 新现人名种类 × 3 + 残留疑名 × 1 + 已知正字人名 × 1。",
        "> 只统计**第三方人物**（写信人/收信人/直系已排除 —— 几乎每封必现，无区分度）。",
        ">",
        "> **为什么优先校这些**：信件中人物越密，人名/称谓/关系误读风险越高；",
        "> 校正一封可同时确认多个条目 —— 人物关系知识是本项目唯一被验证为复利增值的资产。",
        ">",
        f"> 纳入 **{len(rows)}** 封（引用区 {sum(1 for r in rows if r['src']=='引用区')} ／"
        f"早期格式 {sum(1 for r in rows if r['src']=='剥离正文')}）。",
        "",
        "## 一、排名（前 20）",
        "",
        "| # | 信件 | 写信人 | 字数 | 已知正字 | 新现名 | 疑名 | 分值 | 来源 |",
        "|---:|---|---|---|---:|---:|---:|---:|---|",
    ]
    for i, r in enumerate(rows[:20], 1):
        L.append(f"| {i} | `{r['file']}` | {r['writer']} | {r['chars']} | {r['n_known']} | "
                 f"{r['n_new']} | {r['n_res']} | **{r['score']}** | {r['src']} |")

    L += ["", "## 二、TOP 15 明细", ""]
    for i, r in enumerate(rows[:15], 1):
        L.append(f"### {i}. `{r['file']}`")
        L.append("")
        L.append(f"- 字数 **{r['chars']}**｜写信 **{r['writer']}**｜已知正字 **{r['n_known']}**｜"
                 f"新现名 **{r['n_new']}**｜疑名 **{r['n_res']}**｜分值 **{r['score']}**｜来源：{r['src']}")
        if r["known"]:
            L.append(f"- 已知正字：**{'、'.join(f'{k}×{v}' for k, v in r['known'].most_common())}**")
        if r["new"]:
            L.append(f"- 新现人名：{'、'.join(f'{k}×{v}' for k, v in r['new'].most_common(14))}")
        if r["res"]:
            L.append(f"- 待辨疑名：{'、'.join(f'{k}×{v}' for k, v in r['res'].most_common(14))}")
        L.append("")

    if hot:
        L += ["## 三、全库高频「残留疑名」（≥2 次）", "",
              "> 这些很可能是**未登记的真人名**（OCR 误读形态）。"
              "辨认一个，往往能同时解开好几封信。", "",
              "| 疑名 | 总次 | 涉及信件数 | |", "|---|---:|---:|"]
        for w, c, d in hot[:60]:
            L.append(f"| {w} | {c} | {d} |")
        L.append("")

    if excluded:
        L += ["## 四、已校正、已入库的信（本次已排除）", "",
              "| 编号 | 状态 |", "|---|---|"]
        for n, t in excluded:
            L.append(f"| `{n}` | {t} |")
        L.append("")

    out_md = outdir / "待校正_人物高密度信.md"
    out_md.write_text("\n".join(L), encoding="utf-8")
    print()
    print("报告 →", out_md)


if __name__ == "__main__":
    main()
