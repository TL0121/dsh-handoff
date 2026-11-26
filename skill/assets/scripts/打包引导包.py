#!/usr/bin/env python3
"""打「引导包」：规则 + 标准交接脚本 + 装交接器 —— 给新机器 / 新项目装规则用。

公共层（`公共层`，2026-11-25 前叫 `交接工作区`）**不产出进度包**；进度包在各项目自己的 `bin/打包进度.py` 里打。
本项目脚本是**公共层唯一**的打包入口：它只装规则与脚本（元数据 + 脚本，不含任何项目数据），
标准脚本优先取 `公共层/bin/模板/`（没有则用 `--from` 指定，或自动取桌面同级第一个带标准脚本的项目）。

    引导-YYYYMMDD-规则与脚本/
    ├── 00-包入口.md
    ├── MANIFEST.json
    ├── AGENTS.md                     ← 公共层约定
    ├── 工作流-双机交接规则.md          ← 规则的母版（各项目根放同内容副本）
    ├── bin\打包进度.py、bin\接手进度.py  ← 标准脚本（模板或指定项目）
    └── 装交接.py                      ← 对新项目跑一次，自动建 bin/收件箱/发件箱

用法：
  python bin\\打包引导包.py --list                    # 只看会装什么
  python bin\\打包引导包.py                           # 自动取 公共层/bin/模板 或桌面同级项目
  python bin\\打包引导包.py --from ..\\<某项目>
  python bin\\打包引导包.py --out 引导包
"""
import argparse
import hashlib
import json
import os
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent        # 公共层 bin/
ROOT = HERE.parent                            # 公共层根
STD = ("打包进度.py", "接手进度.py")
ROOT_FILES = ("AGENTS.md", "工作流-双机交接规则.md")
TEMPLATE = ROOT / "bin" / "模板"              # 标准脚本的唯一来源（2026-11-25 起）


def default_src() -> Path:
    """标准脚本从哪取：先模板；没有就取桌面同级第一个带 bin/打包进度.py 的项目。"""
    if all((TEMPLATE / n).is_file() for n in STD):
        return TEMPLATE
    for base in [ROOT.parent] + desktop_dirs():
        for p in sorted(base.glob("*/bin/" + STD[0])):
            return p.parent.parent
    return ROOT.parent          # 交给 find_sources 报明确错误

for _s in (sys.stdout, sys.stderr):
    try:
        if _s.isatty():
            _s.reconfigure(errors="replace")
        else:
            _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}" if u != "B" else f"{n} B"
        n /= 1024


def sha(b):
    return hashlib.sha256(b).hexdigest()


def find_sources(src_project: Path):
    """返回 [(包内路径, 本机路径, bytes)]。

    ``src_project`` 可以是「带 bin/ 的项目根」，也可以直接是 ``公共层\\bin\\模板``（标准脚本的唯一来源）。
    """
    out = []
    for name in ROOT_FILES:
        p = ROOT / name
        if not p.is_file():
            sys.exit(f"公共层缺少 {name}：{p}")
        out.append((name, p))
    for name in STD:
        for cand in (src_project / name, src_project / "bin" / name):
            if cand.is_file():
                out.append((f"bin/{name}", cand))
                break
        else:
            sys.exit(f"{src_project} 里没有 {name}；用 --from 指定公共层\\bin\\模板 或一个带标准脚本的项目")
    p = HERE / "装交接.py"
    if not p.is_file():
        sys.exit(f"公共层缺少 bin/装交接.py：{p}")
    out.append(("装交接.py", p))
    return out


def desktop_dirs():
    """本机桌面可能被 OneDrive 重定向（本机 = C:\\Users\\<u>\\OneDrive\\Desktop），两个都试。"""
    out = [Path.home() / "OneDrive" / "Desktop", Path.home() / "Desktop"]
    return [p for p in out if p.is_dir()]


def drift_check(chosen: Path):
    """各项目的标准脚本必须字节一致；不一致就报出来（不静默挑一个）。"""
    want = sha(chosen.read_bytes())
    rows, bad = [], []
    for base in [ROOT] + desktop_dirs():
        for p in sorted(base.glob("*/bin/" + chosen.name)):
            if p.resolve() == chosen.resolve():
                continue
            same = sha(p.read_bytes()) == want
            rows.append((p.parent.parent.name, same))
            if not same:
                bad.append(str(p))
    return rows, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default=None,
                    help="从哪取标准脚本；默认 公共层\\bin\\模板\\，没有就取桌面同级第一个带标准脚本的项目")
    ap.add_argument("--out", default=None, help="输出目录，默认 公共层/引导包")
    ap.add_argument("--list", action="store_true", help="只报账，不产包")
    a = ap.parse_args()

    if a.src:
        src = Path(a.src).resolve()
    else:
        src = default_src()
    items = find_sources(src)

    chosen = next(p for name, p in items if name == "bin/打包进度.py")
    rows, bad = drift_check(chosen)
    if bad:
        print("✗ 标准脚本在各项目间不一致，拒绝打引导包：")
        for p in bad:
            print("   ", p)
        sys.exit(1)

    print(f"公共层：{ROOT}")
    print(f"标准脚本来自：{src}")
    for name, p in items:
        print(f"  {name:<28} {human(p.stat().st_size):>9}  sha256={sha(p.read_bytes())[:8]}")
    if rows:
        print(f"另外 {len(rows)} 个项目的副本与之一致（已核对 sha256）")

    if a.list:
        print("\n（--list：未写任何文件）")
        return

    out_dir = Path(a.out).resolve() if a.out else ROOT / "引导包"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    pkg = f"引导-{time.strftime('%Y%m%d')}-规则与脚本"
    zip_path = out_dir / f"{pkg}.zip"
    n = 2
    while zip_path.exists():
        zip_path = out_dir / f"{pkg}-{n}.zip"
        n += 1
    pkg = zip_path.stem

    entries, total = [], 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name, p in items:
            data = p.read_bytes()
            z.writestr(f"{pkg}/{name}", data)
            entries.append({"path": name, "bytes": len(data), "sha256": sha(data)})
            total += len(data)

        lines = [
            f"# 00 · 引导包（{pkg}）", "",
            f"- 类型：**引导包**（规则与脚本），不是进度包；不含任何项目数据",
            f"- 来源机标签：**{tag()}**　　打包时间：{time.strftime('%Y-%m-%d %H:%M')}",
            f"- 文件数：**{len(entries)}**　　解压后：**{human(total)}**", "",
            "## 装到一台新机器 / 一个新项目", "",
            "```bash",
            "python 装交接.py <项目根目录> --patch-agents   # 或 --append-agents",
            "```", "",
            "它会建 `bin/`、`收件箱/`、`发件箱/`，拷两份标准脚本进去，并写两个 README。",
            "`--patch-agents` 只对已知措辞的 AGENTS.md 生效；没有 AGENTS.md 的项目直接不加。", "",
            "## 内容", "",
            "| 文件 | 用途 |", "|---|---|",
            "| `工作流-双机交接规则.md` | 规则的母版（各项目根放同内容副本） |",
            "| `AGENTS.md` | 公共层约定 |",
            "| `bin/打包进度.py`、`bin/接手进度.py` | 标准脚本（scope / 签名 / sha256） |",
            "| `装交接.py` | 给新项目铺交接 |", "",
            "## 注意", "",
            "- 各项目的标准脚本必须与包内这几份**字节一致**；否则接手方会因新旧行为不同而出错。",
            "- 引导包不含 `本机项目清单.md`（只对来源机有效）、`tools/`（平台件）。",
        ]
        entry = "\n".join(lines).encode("utf-8")
        z.writestr(f"{pkg}/00-包入口.md", entry)
        man = {"package": pkg, "kind": "bootstrap", "tag": tag(),
               "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "mode": "bootstrap",
               "totals": {"files": len(entries) + 2, "uncompressed_bytes": total},
               "files": entries + [{"path": "00-包入口.md", "bytes": len(entry),
                                    "sha256": sha(entry), "role": "entry"}]}
        z.writestr(f"{pkg}/MANIFEST.json", json.dumps(man, ensure_ascii=False, indent=2).encode("utf-8"))

    print(f"\n已打包：{zip_path}")
    print(f"  {len(entries)} 个载荷 / 解压后 {human(total)} / 压缩包 {human(zip_path.stat().st_size)}")


def tag():
    import platform
    if platform.system() == "Darwin":
        return "mac"
    m = platform.machine().lower()
    return "x86" if m in ("x86_64", "amd64", "i386", "i686") else (m or "unknown")


if __name__ == "__main__":
    main()
