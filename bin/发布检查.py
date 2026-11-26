#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布前检查：把「本机痕迹」和「载荷缺件」在打包发布之前找出来。

只读，不改任何文件。检查对象默认是本项目（dsh-handoff 源仓库）：
    python bin/发布检查.py                # 人读报告，有 ERROR 时退出码 1
    python bin/发布检查.py --json         # 机读（CI / agent）
    python bin/发布检查.py --root <目录>  # 查别的目录

三类问题：
    ERROR  发布出去就是事故：本机绝对路径 / 个人标识 / 载荷缺件 / 规则两份不一致
    WARN   能用但不干净：待填占位 / 大文件 / 本机专有名字
    INFO   提示：TODO、空目录

「本机专有名字」不写死在本脚本里：放进仓库根的 `.releaseignore`（一行一个，该文件已进
`.gitignore`，不随仓库公开）；没有这个文件时该项自动跳过。

只依赖标准库；输出与其它脚本同口径（非终端强制 UTF-8）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # 项目 bin/
ROOT = HERE.parent                              # 项目根

for _s in (sys.stdout, sys.stderr):
    try:
        if _s.isatty():
            _s.reconfigure(errors="replace")
        else:
            _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

SKIP_DIRS = {".git", ".dsh", "__pycache__", "node_modules", ".idea", ".vscode"}
TEXT_EXT = {".md", ".py", ".json", ".yml", ".yaml", ".mjs", ".js", ".svg", ".txt",
            ".ps1", ".cmd", ".bat", ".sh", ".toml", ".cfg", ".ini", ".html", ".css"}
SKILL = ROOT / "skill"
RULE_FILE = ROOT / "工作流-双机交接规则.md"
SIZE_WARN = 2 * 1024 * 1024

# (名字, 正则, 级别, 说明) —— 只针对「会被发布出去」的文本文件
# 占位写法（`<用户>`、`%USERPROFILE%`、`~/Desktop`）是**期望**的，所以用户段用负向断言排除 `<`。
# 本机用户名从系统取，绝不写进仓库。
HOME_NAME = Path.home().name
PATTERNS = [
    ("Windows 具体用户路径", re.compile(r"[A-Za-z]:[\\/]{1,2}(?:Users|用户)[\\/](?![<…])[^\\/\s\"'<>|]+"), "ERROR",
     "本机绝对路径：换成 <桌面> 或 %USERPROFILE% 这类占位"),
    ("mac 具体用户路径", re.compile(r"/Users/(?![<…])(?!Shared\b|shared\b)[A-Za-z0-9._-]+"), "ERROR",
     "本机绝对路径：换成 ~/Desktop 这类写法"),
    ("本机用户名", re.compile(r"\b" + re.escape(HOME_NAME) + r"\b"), "ERROR", "把用户名换成占位"),
    ("本机机器名", re.compile(r"\bDESKTOP-[A-Z0-9]{6,}\b"), "WARN", "机器名泄露"),
    ("手机号样式", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "WARN", "像手机号，确认不是个人信息"),
    ("邮箱", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"), "WARN", "确认可公开"),
    ("待填占位", re.compile(r"<[^<>\n]*(?:待填|TODO|TBD|待补)[^<>\n]*>"), "WARN",
     "作者名 / 路径占位，发布前补上"),
    ("TODO/FIXME", re.compile(r"\b(TODO|FIXME|XXX)\b"), "INFO", "遗留标记"),
]
# 本机专有的目录名/项目名：写在仓库根的 `.releaseignore`（一行一个，已进 .gitignore，不公开），
# 这样工具自己能公开，而清单只留在本机。
LOCAL_NAMES_FILE = ROOT / ".releaseignore"
# 这些文件本身就是「本机痕迹」的定义者，扫自己只会自噪
SELF_SKIP = {"发布检查.py"}


def local_names() -> list[str]:
    if not LOCAL_NAMES_FILE.is_file():
        return []
    out = []
    for line in LOCAL_NAMES_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def walk(root: Path):
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS)
        for fn in sorted(fns):
            yield Path(dp) / fn


def read_text(p: Path) -> tuple[str | None, str | None]:
    """(文本, 问题)。问题 = 'BOM' / 'BAD-UTF8' / None"""
    try:
        raw = p.read_bytes()
    except OSError as e:
        return None, f"读不了：{e}"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", "replace"), "BOM"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return raw.decode("utf-8", "replace"), "BAD-UTF8"


def check_patterns(files, findings):
    names = local_names()
    for p in files:
        if p.suffix.lower() not in TEXT_EXT:
            continue
        if p.stat().st_size > SIZE_WARN:
            continue
        text, problem = read_text(p)
        if text is None:
            findings.append(("ERROR", str(p.relative_to(ROOT)), problem))
            continue
        if problem == "BOM":
            findings.append(("ERROR", str(p.relative_to(ROOT)), "UTF-8 带 BOM：规则要求无 BOM"))
        if problem == "BAD-UTF8":
            findings.append(("ERROR", str(p.relative_to(ROOT)), "不是合法 UTF-8（乱码风险）"))
        if p.name in SELF_SKIP:
            continue                              # 检查器自己必然含有这些模式
        for name, rx, level, hint in PATTERNS:
            hits = {}
            for m in rx.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                hits.setdefault(line, m.group(0)[:60])
            for line, sample in sorted(hits.items())[:5]:
                findings.append((level, f"{p.relative_to(ROOT)}:{line}", f"{name} → {sample}　（{hint}）"))
        for word in names:                        # 本机专有名字：来自 .releaseignore
            if word in text:
                line = text.count("\n", 0, text.index(word)) + 1
                findings.append(("WARN", f"{p.relative_to(ROOT)}:{line}",
                                 f"本机专有名字 → {word}　（从代码/文档里拿掉，换成可配置项或占位）"))


def check_payload(findings):
    if not SKILL.is_dir():
        findings.append(("ERROR", "skill/", "开源载荷目录不存在"))
        return
    skill_md = SKILL / "SKILL.md"
    if not skill_md.is_file():
        findings.append(("ERROR", "skill/SKILL.md", "缺 SKILL 入口"))
    else:
        head = skill_md.read_text(encoding="utf-8")[:600]
        if not head.startswith("---"):
            findings.append(("ERROR", "skill/SKILL.md", "frontmatter 缺失（首行应为 ---）"))
        for key in ("name:", "description:"):
            if key not in head:
                findings.append(("ERROR", "skill/SKILL.md", f"frontmatter 缺 {key}"))
    for rel in ("install.py", "assets/layer/AGENTS.md",
                "references/交接规则.md", "references/坑与教训.md", "references/迁移检查清单.md"):
        if not (SKILL / rel).is_file():
            findings.append(("ERROR", f"skill/{rel}", "载荷缺件"))
    for name in ("装交接.py", "打包引导包.py", "打包进度.py", "接手进度.py"):
        if not (SKILL / "assets" / "scripts" / name).is_file():
            findings.append(("ERROR", f"skill/assets/scripts/{name}", "载荷缺件"))
    pkg = SKILL / "assets" / "plugin" / "dsh-autohandoff" / "package.json"
    if not pkg.is_file():
        findings.append(("ERROR", "skill/assets/plugin/dsh-autohandoff/package.json", "插件缺 package.json"))
    # 载荷里不该出现的东西
    for p in walk(SKILL):
        rel = p.relative_to(ROOT)
        if p.suffix.lower() == ".pyc" or p.name == "__pycache__":
            findings.append(("ERROR", str(rel), "不该进载荷：__pycache__/.pyc"))
        elif p.suffix.lower() == ".zip":
            findings.append(("ERROR", str(rel), "不该进载荷：压缩包"))
        elif p.stat().st_size > SIZE_WARN:
            findings.append(("WARN", str(rel), f"大文件 {p.stat().st_size // 1024} KB，确认要随载荷发布"))


def check_rules(findings):
    if not RULE_FILE.is_file():
        findings.append(("ERROR", "工作流-双机交接规则.md", "规则文件不存在"))
        return
    text = RULE_FILE.read_text(encoding="utf-8")
    m = re.search(r"改版\s*(v\d+\.\d+)", text[:400])
    if not m:
        findings.append(("ERROR", "工作流-双机交接规则.md:1", "首行没有「改版 vX.Y」"))
    copy = SKILL / "references" / "交接规则.md"
    if copy.is_file() and copy.read_bytes() != RULE_FILE.read_bytes():
        findings.append(("ERROR", "skill/references/交接规则.md", "与根目录规则不一致（版本源只能一份）"))
    lic = ROOT / "LICENSE"
    if lic.is_file() and "待填" in lic.read_text(encoding="utf-8", errors="replace"):
        findings.append(("WARN", "LICENSE", "作者名还是占位；发布前定许可与署名"))


def main() -> int:
    ap = argparse.ArgumentParser(description="发布前检查（只读）")
    ap.add_argument("--root", default=None, help="检查哪个目录（默认本项目根）")
    ap.add_argument("--json", action="store_true", help="机读输出")
    a = ap.parse_args()

    global ROOT, SKILL, RULE_FILE
    if a.root:
        ROOT = Path(a.root).expanduser().resolve()
        SKILL = ROOT / "skill"
        RULE_FILE = ROOT / "工作流-双机交接规则.md"
    if not ROOT.is_dir():
        print(f"目录不存在：{ROOT}", file=sys.stderr)
        return 2

    files = list(walk(ROOT))
    findings: list[tuple[str, str, str]] = []
    check_patterns(files, findings)
    check_payload(findings)
    check_rules(findings)

    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    findings.sort(key=lambda f: (order.get(f[0], 3), f[1]))

    if a.json:
        print(json.dumps({"root": str(ROOT), "files": len(files),
                          "findings": [{"level": l, "where": w, "what": d} for l, w, d in findings]},
                         ensure_ascii=False, indent=1))
    else:
        errors = sum(1 for f in findings if f[0] == "ERROR")
        warns = sum(1 for f in findings if f[0] == "WARN")
        infos = sum(1 for f in findings if f[0] == "INFO")
        print(f"检查：{ROOT}")
        print(f"文件：{len(files)} 个　结论：ERROR {errors} · WARN {warns} · INFO {infos}")
        if not findings:
            print("干净，可以发布。")
        for level, where, what in findings:
            print(f"  {level:<5} {where}\n        {what}")
        if errors:
            print("\n有 ERROR：先修完再发布（--json 可接 CI）。")
        elif warns:
            print("\n没有 ERROR；WARN 建议清掉再开源。")
    return 1 if any(f[0] == "ERROR" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
