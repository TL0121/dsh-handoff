#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键铺「公共层」：规则 + 标准脚本 + 自动铺交接插件。本脚本就在 skill 载荷根目录里。

它只写 `桌面/公共层/`，**不碰任何项目目录**（项目迁移、改名、补交接要判断，交给 agent 或
`bin/装交接.py --scan`）。货全部从本 skill 目录取，不依赖任何本机路径。

用法（在本文件所在目录里）：
    python3 install.py                    # 只看会写什么（dry-run，安全）
    python3 install.py --apply            # 真写
    python3 install.py --apply --smoke    # 真写 + 铺一个临时项目自测（推荐）
    python3 install.py --desktop ~/Desktop --apply
    python3 install.py --apply --force-agents   # 连 公共层/AGENTS.md 一起覆盖

Windows 是 `python install.py`；macOS 是 `python3 install.py`。
幂等：重复跑只覆盖内容不同的文件，**从不删除**任何东西。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # skill/ 根
RULES = HERE / "references" / "交接规则.md"
SCRIPTS = HERE / "assets" / "scripts"
PLUGIN = HERE / "assets" / "plugin" / "dsh-autohandoff"
LAYER_AGENTS = HERE / "assets" / "layer" / "AGENTS.md"
EXTRA_REFS = (HERE / "references" / "坑与教训.md", HERE / "references" / "迁移检查清单.md")

# 编码：终端（人看）按控制台编码、只替换错误字符；非终端（管道 / agent 抓取）写 UTF-8。
# 与 bin/打包进度.py、bin/接手进度.py 口径一致 —— 否则 agent 读到方块。
for _s in (sys.stdout, sys.stderr):
    try:
        if _s.isatty():
            _s.reconfigure(errors="replace")
        else:
            _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

IS_MAC = sys.platform == "darwin"
PY = "python3" if IS_MAC else "python"
LAYER_DIRS = ("_日志", "_历史", "引导包", "素材库", "工具")
SKIP = {"__pycache__", "node_modules", ".git", ".dsh"}


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def default_desktop() -> Path:
    """桌面可能被 OneDrive / iCloud 重定向，按常见候选依次探测。"""
    home = Path.home()
    for cand in (home / "Desktop", home / "OneDrive" / "Desktop",
                 home / "桌面", home / "OneDrive" / "桌面"):
        if cand.is_dir():
            return cand
    return home / "Desktop"


def files_under(root: Path) -> list[Path]:
    out: list[Path] = []
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in SKIP)
        out += [Path(dp) / fn for fn in sorted(fns)]
    return out


def build_plan(layer: Path, with_refs: bool) -> list[tuple[Path, Path, str]]:
    """(源, 目标, 类别)；目标都落在 layer 里。"""
    plan: list[tuple[Path, Path, str]] = [(RULES, layer / "工作流-双机交接规则.md", "规则")]
    for name in ("装交接.py", "打包引导包.py"):
        plan.append((SCRIPTS / name, layer / "bin" / name, "脚本"))
    for name in ("打包进度.py", "接手进度.py"):
        plan.append((SCRIPTS / name, layer / "bin" / "模板" / name, "模板"))
    for f in files_under(PLUGIN):
        plan.append((f, layer / "plugins" / "dsh-autohandoff" / f.relative_to(PLUGIN), "插件"))
    if with_refs:
        for f in EXTRA_REFS:
            plan.append((f, layer / "参考" / f.name, "参考"))
    return plan


def agents_target(layer: Path, force: bool) -> tuple[Path | None, Path, str]:
    dst = layer / "AGENTS.md"
    if dst.is_file() and not force:
        return None, dst, "已存在 → 保留本机版"
    if dst.is_file():
        return LAYER_AGENTS, dst, "已存在 → 按 --force-agents 覆盖"
    return LAYER_AGENTS, dst, "缺失 → 写骨架"


def same(a: Path, b: Path) -> bool:
    try:
        return b.is_file() and a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def plugin_links() -> list[tuple[str, Path]]:
    """已装插件的 profile 链接（profile 名, 链接路径）。"""
    root = Path.home() / ".dsh" / "profiles"
    hits: list[tuple[str, Path]] = []
    if not root.is_dir():
        return hits
    for prof in sorted(root.iterdir()):
        for rel in ("node_modules/dsh-autohandoff", "node_modules/@local/dsh-autohandoff"):
            p = prof / rel
            if p.exists() or p.is_symlink():
                hits.append((prof.name, p))
    return hits


def print_plugin_step(layer: Path) -> None:
    hits = plugin_links()
    print("\n插件（自动铺交接 dsh-autohandoff）：")
    for prof, p in hits:
        broken = p.is_symlink() and not p.exists()
        try:
            target = os.readlink(p)
        except (OSError, ValueError):
            target = "(非链接)"
        mark = "✗ 死链" if broken else "✓ 已装"
        print(f"  {mark}：profile `{prof}` → {target}")
    if hits:
        print("    换机/升级后重启 DSH 生效；没生效就按下面重装。")
    else:
        print("  ✗ 未装（新机器常见）：用 DSH 的 plugin_manager 装一次，然后重启 DSH。")
    print("    DSH 里让 agent 执行：")
    print(f'      plugin_manager(action="install_bundle", target="{layer / "plugins" / "dsh-autohandoff"}")')
    print("    看到 application: restart-required 就重启；设置 → 插件应出现「新项目自动铺交接」。")


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """子进程输出强制 UTF-8（否则 Windows 下 traceback 是 cp936，读出来是方块）。"""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180, env=env)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:      # 沙箱/缺解释器
        return 1, f"{type(e).__name__}: {e}"


def smoke(layer: Path, desktop: Path, smoke_dir: str | None = None) -> bool:
    """铺一个临时项目，验证脚本落地 + AGENTS 两节 + --list 能跑；跑完删掉。

    临时项目默认建在桌面（安装器本来就在写这里），不用 tempfile：某些沙箱/杀软环境下
    `mkdtemp` 建出来的目录 ACL 收得过紧，反而在里面 mkdir 会 WinError 5。
    """
    base = Path(smoke_dir).expanduser().resolve() if smoke_dir else desktop / f".handoff-smoke-{os.getpid()}"
    try:
        base.mkdir(parents=True, exist_ok=False)
    except OSError as e:
        print(f"\n自测跳过：建不了临时目录 {base}（{type(e).__name__}: {e}）", file=sys.stderr)
        return False
    tmp = base / "自测项目"
    tmp.mkdir()
    try:
        code, out = run([sys.executable, str(layer / "bin" / "装交接.py"), str(tmp),
                         "--init-agents", "--append-agents"], cwd=layer)
        checks: list[tuple[str, bool, str]] = [("装交接.py 退出码 0", code == 0, out.strip().splitlines()[-1] if out.strip() else "")]
        for rel in ("bin/打包进度.py", "bin/接手进度.py", "收件箱/README.md", "发件箱/README.md"):
            checks.append((rel, (tmp / rel).is_file(), ""))
        agents = (tmp / "AGENTS.md").read_text(encoding="utf-8") if (tmp / "AGENTS.md").is_file() else ""
        checks.append(("AGENTS.md 有「交接」节", "交接" in agents, ""))
        checks.append(("AGENTS.md 有「共用工具」节", "共用工具" in agents, ""))
        code2, out2 = run([sys.executable, str(tmp / "bin" / "打包进度.py"), "--list"], cwd=tmp)
        scope_ok = code2 == 0 and "scope" in out2
        checks.append(("新项目 打包进度.py --list", scope_ok, "" if scope_ok else out2.strip()[:200]))

        ok = all(c[1] for c in checks)
        print("\n自测（临时项目）：")
        for name, passed, note in checks:
            print(f"  {'PASS' if passed else 'FAIL'}  {name}" + (f"   {note}" if note and not passed else ""))
        print(f"  临时项目已删除：{base}")
        return ok
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="从本 skill 目录铺「公共层」（默认 dry-run）")
    ap.add_argument("--desktop", default=None, help="桌面路径（默认自动探测 ~/Desktop 与 OneDrive/Desktop）")
    ap.add_argument("--layer", default="公共层", help="公共层目录名（默认 公共层）")
    ap.add_argument("--apply", action="store_true", help="真的写文件（默认只看）")
    ap.add_argument("--force-agents", action="store_true", help="连 公共层/AGENTS.md 一起覆盖")
    ap.add_argument("--with-references", action="store_true", help="把「坑与教训」「迁移检查清单」也铺到 公共层/参考/")
    ap.add_argument("--smoke", action="store_true", help="写完后铺一个临时项目自测（需配合 --apply）")
    ap.add_argument("--smoke-dir", default=None, help="自测用的临时目录（默认 <桌面>/.handoff-smoke-<pid>，跑完删除）")
    a = ap.parse_args()

    missing = [p for p in (RULES, SCRIPTS, PLUGIN, LAYER_AGENTS) if not p.exists()]
    if missing:
        print("skill 载荷不完整，缺：\n  " + "\n  ".join(str(p) for p in missing), file=sys.stderr)
        print("（请在解压后的 skill 目录里运行本脚本）", file=sys.stderr)
        return 2

    desktop = Path(a.desktop).expanduser().resolve() if a.desktop else default_desktop()
    if not desktop.is_dir():
        print(f"桌面目录不存在：{desktop}\n用 --desktop <路径> 指定。", file=sys.stderr)
        return 2
    layer = desktop / a.layer

    plan = build_plan(layer, a.with_references)
    ag_src, ag_dst, ag_note = agents_target(layer, a.force_agents)

    new = [p for p in plan if not p[1].exists()]
    diff = [p for p in plan if p[1].exists() and not same(p[0], p[1])]
    total = sum(s.stat().st_size for s, _, _ in plan) + (ag_src.stat().st_size if ag_src else 0)

    print(f"平台：{'macOS' if IS_MAC else ('Windows' if os.name == 'nt' else sys.platform)}"
          f"　解释器：{PY} {sys.version.split()[0]}")
    print(f"桌面：{desktop}")
    print(f"公共层：{layer}{'（已存在，合并）' if layer.exists() else '（新建）'}")
    print(f"载荷：{len(plan)} 个文件 / {human(total)}　新增 {len(new)} · 内容不同 {len(diff)} · 已一致 {len(plan) - len(new) - len(diff)}")
    by_kind: dict[str, int] = {}
    for _, _, kind in plan:
        by_kind[kind] = by_kind.get(kind, 0) + 1
    print("  " + "　".join(f"{k} {v}" for k, v in by_kind.items()))
    print(f"  AGENTS.md：{ag_note}")
    print("  （建目录）" + "、".join(LAYER_DIRS))

    if not a.apply:
        print("\n（dry-run：未写任何文件；加 --apply 真写）")
        if a.smoke:
            print("（--smoke 需要 --apply）")
        return 0

    for d in LAYER_DIRS:
        (layer / d).mkdir(parents=True, exist_ok=True)
    (layer / "bin" / "模板").mkdir(parents=True, exist_ok=True)
    written = 0
    for src, dst, _ in plan:
        if same(src, dst):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        written += 1
    if ag_src is not None:
        ag_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ag_src, ag_dst)
        written += 1
    print(f"\n已写 {written} 个文件（其余已一致，未动）→ {layer}")

    print_plugin_step(layer)
    print("\n下一步：")
    print(f"  1) {PY} \"{layer / 'bin' / '装交接.py'}\" --scan --desktop \"{desktop}\"")
    print(f"  2) 缺谁就加 --apply 补齐；项目还没挪到桌面同级的，先按 references/迁移检查清单.md 第 2 节挪")
    print(f"  3) 装插件（见上）；重启后在空目录开会话冒烟")
    print(f"  4) 每个项目里：{PY} bin/打包进度.py --list")

    ok = True
    if a.smoke:
        ok = smoke(layer, desktop, a.smoke_dir)
        print("\n自测" + ("全部 PASS" if ok else "有 FAIL —— 看上面哪一行"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
