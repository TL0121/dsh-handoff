#!/usr/bin/env python3
"""给一个项目铺「独立收发」：bin/ + 收件箱/ + 发件箱/ + 两个 README（可改 AGENTS.md）。

用法（在引导包解压目录里，或在公共层 bin/ 里）：
  python 装交接.py <项目根目录>
  python 装交接.py <项目根目录> --append-agents   # 在 AGENTS.md 末尾追加交接 + 共用工具小节
  python 装交接.py <项目根目录> --init-agents     # 没有 AGENTS.md 就新建一份（新项目用）
  python 装交接.py <项目根目录> --patch-agents    # 替换旧版已知措辞的「范围」两条
  python 装交接.py <项目根目录> --list            # 只报账
  python 装交接.py --scan                         # 扫描桌面：哪些项目还没有交接（只列）
  python 装交接.py --scan --apply                 # 扫描并当场补齐（dsh-autohandoff 插件也调这条）

只做加法：不删任何文件；已存在的 bin 脚本会被标准版覆盖。
标准脚本优先取 `公共层\\bin\\模板\\`，所以公共层单独拷到新机器也能铺项目。
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # 公共层\bin（或引导包根）
LAYER = HERE.parent                             # 公共层
STD = ("打包进度.py", "接手进度.py")

for _s in (sys.stdout, sys.stderr):
    try:
        if _s.isatty():
            _s.reconfigure(errors="replace")
        else:
            _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

INBOX_README = """# 收件箱 · {name}

对端机器传来的**本项目**进度包放在这里，命名 `<项目名>-进度-YYYYMMDD-HHMM-<来源机>.zip`。

接手（在**本项目根目录**跑）：

```
python3 bin/接手进度.py 收件箱/<包>.zip        # macOS / Linux
python  bin\\接手进度.py 收件箱\\<包>.zip        # Windows
```

脚本会依次做四件事，任何一条不过就**不落盘**：

1. **scope 校验** —— 包的 `MANIFEST.scope` 必须是 `{name}`，否则拒绝（挡住"把别的项目的包合进这里"）；
2. **签名查重** —— 查本目录下的 `.已接手.json`，同一个包（字节相同）再合直接拒；
3. **逐文件 sha256** —— 按 `MANIFEST.json` 校验，不一致即中止；
4. 合并解压，并在这里写 `接手记录-YYYYMMDD-HHMM.md`。

只看不写：`python bin\\接手进度.py <包> --dry-run`。

## 两条硬规矩

- `.已接手.json` 由脚本自动维护，**别删** —— 删了同一个包就能再合一遍，把文件覆盖回旧版。
- 接手完就把包移走（删掉或移进 `_已接手/`）：收件箱里只放"待接手"。

历史包与接手记录可以随时删，不影响项目本身。只加 `--force` 才能绕过 1、2 两条（脚本会写明后果）。
"""

OUTBOX_README = """# 发件箱 · {name}

离开本机前，在**本项目根目录**跑：

```
# 用你平台上的那个解释器：macOS / Linux 是 python3，Windows 是 python
python3 bin/打包进度.py --lite               # macOS / Linux：跳过 **/runs/ 与 generate/3d
python  bin\\打包进度.py --lite               # Windows：同上
python3 bin/打包进度.py --list               # 只报账（会打哪些文件、多大），不写 zip
python3 bin/打包进度.py --exclude <目录>      # 额外排除（相对项目根，可重复）
```

产出 `<项目名>-进度-YYYYMMDD-HHMM-<来源机>.zip`，`MANIFEST.scope` = `{name}`，入口文档里写明"只含本项目"。
接手方如果项目不符会被拒绝。

## 本项目体积（**全量口径**，未计 `--lite` 与 `--exclude`：{files} 个文件 / {total}）

| 顶层 | 文件数 | 体积 |
|---|---|---|
{rows}

`bin/`、`收件箱/`、`发件箱/`、`.dsh/`、`.local/`、缓存与 `*.zip` 由脚本自动排除，不会进包。

**本项目的建议命令**：{hint}

`bin/接手进度.py` **默认不动 发件箱/**（里面可能是打好、还没送出去的包）。
确认里面的旧包都不要了，再显式加 `--clean-outbox`；它只清第一层 zip，README 与子目录不受影响。

包打好后由人从本目录拷到对端；本目录永不入包。
"""

AGENTS_OLD = [
    "- `..\\<其它项目>\\`、`..\\公共层\\`、`..\\tools\\` 一律**只读**；确实要动，先问用户。",
    "- 双机打包 / 接手**不在本对话做**：那是 `公共层` 那个工作区的事（`bin\\打包进度.py` 的 ROOT 由脚本位置推导，越界写会被沙箱拦）。",
]
AGENTS_NEW = """- **本项目自带一套交接**（2026-11-25 起）：`bin\\打包进度.py`、`bin\\接手进度.py`、`收件箱\\`、`发件箱\\`。
  打包与接手都在**本项目根目录**里跑，包只含本项目（`MANIFEST.scope = {name}`）。
  - 离开前：`python bin\\打包进度.py --lite`
  - 接手时：`python bin\\接手进度.py 收件箱\\<包>.zip`（先 scope 校验、再查 `.已接手.json` 签名、再逐文件 sha256）
  - 只看不写：`python bin\\打包进度.py --list` / `python bin\\接手进度.py <包> --dry-run`
- `..\\公共层\\`（共用工具 `tools\\`、规则、引导包）与 `..\\<其它项目>\\` 一律**只读**；
  确实要动，先问用户。其它项目也各有自己的一套收发件箱，**互不代打、互不代接**。
- 共用工具只有一份、在 `..\\公共层\\tools\\`：`..\\公共层\\tools\\<解释器包装> <脚本>` / `..\\公共层\\tools\\<无头程序包装> <参数>`；
  临时目录自动落 `本目录\\.dsh\\tmp`。**不要**把 tools 复制进本项目。"""

AGENTS_APPEND = """
## 交接（2026-11-25 起，本项目自带）

- 离开前：`python bin\\打包进度.py --lite`（大件要不要带，见 `发件箱\\README.md`）
- 接手时：`python bin\\接手进度.py 收件箱\\<包>.zip`（scope 校验 + `.已接手.json` 签名 + 逐文件 sha256）
- 只看不写：`python bin\\打包进度.py --list` / `python bin\\接手进度.py <包> --dry-run`
- 包只含本项目（`MANIFEST.scope = {name}`），别的项目的包会被拒绝；同一个包接两次也会被签名拦住。
"""

SKIP = {"bin", "收件箱", "发件箱", ".dsh", "__pycache__", "node_modules", ".git", ".local"}

# 桌面上不算项目、不该铺交接的目录（每台机器不同，所以默认留空）：
# 本脚本用 `--exclude <名字>` 追加；插件侧在 `cordis.patch.yml` 的 `config.exclude` 里配。
DEFAULT_EXCLUDE: set = set()

# 新项目的 AGENTS.md 骨架：交接 + 共用工具 + 范围。正文由项目自己后面补。
# 说明：`tools\` 下的包装器是本机自备的平台件（示例为 Windows 的 .cmd）；
# 别的机器按自己的实际命令替换，别把平台件复制进项目。
AGENTS_TOOLS = """
## 共用工具（本机唯一一份：`..\\公共层\\tools\\`，**别复制进本项目**）

```cmd
..\\公共层\\tools\\<解释器包装> <脚本.py>        :: 例如 py.cmd → 固定版本的 Python + 常用库
..\\公共层\\tools\\<专用程序包装> <参数>          :: 例如某渲染器的 .cmd → 系统安装的无头程序
```

临时目录自动落 `本目录\\.dsh\\tmp`（沙箱不放行系统 Temp）；`..\\公共层\\` 只读，规则见 `..\\公共层\\AGENTS.md`。
"""

AGENTS_SKELETON = """# {name} · 本工作区约定

> 这份文件只在「以 `{name}\\` 为工作区」的对话里生效（AGENTS.md 由 DSH 自动注入）。
> 2026-11-25 由 `公共层\\bin\\装交接.py` 生成骨架，**项目正文请往下补**：这是什么、先读什么、已知坑。

## 交接（本项目自带）

- 离开前：`python bin\\打包进度.py --lite`
- 接手时：`python bin\\接手进度.py 收件箱\\<包>.zip`（scope 校验 + `.已接手.json` 签名 + 逐文件 sha256）
- 只看不写：`python bin\\打包进度.py --list` / `python bin\\接手进度.py <包> --dry-run`
- 包只含本项目（`MANIFEST.scope = {name}`）；别的项目的包会被拒绝，同一个包接两次会被签名拦住。
{extra}"""


# ---- macOS 口径（2026-11-26 加）：x86 的模板全是 Windows 措辞（`公共层\tools\py.cmd`、`python bin\…`），
# 直接铺到 Mac 上等于教错命令。这里按平台换掉文案；x86 行为与原文完全一致（不进入这个分支）。
# 结构层面的差异只有两条：① 解释器是 `python3`；② 平台件在工作区根 `../tools/`，不在 `公共层/tools/`。
if sys.platform == "darwin":
    AGENTS_NEW = """- **本项目自带一套交接**（2026-11-25 起）：`bin/打包进度.py`、`bin/接手进度.py`、`收件箱/`、`发件箱/`。
  打包与接手都在**本项目根目录**里跑，包只含本项目（`MANIFEST.scope = {name}`）。
  - 离开前：`python3 bin/打包进度.py --lite`
  - 接手时：`python3 bin/接手进度.py 收件箱/<包>.zip`（先 scope 校验、再查 `.已接手.json` 签名、再逐文件 sha256）
  - 只看不写：`python3 bin/打包进度.py --list` / `python3 bin/接手进度.py <包> --dry-run`
- `../公共层/`（规则、脚本母版、插件源、引导包）与 `../<其它项目>/` 一律**只读**；
  确实要动，先问用户。其它项目也各有自己的一套收发件箱，**互不代打、互不代接**。
- 平台件在本工作区根 `../tools/`（解释器/渲染器各机自备，例如 macOS 的 `/Applications/<App>.app`，ffmpeg 在 `../tools/bin/ffmpeg`）；
  临时目录落 `本目录/.dsh/tmp`。**不要**把 tools 复制进本项目。"""

    AGENTS_APPEND = """
## 交接（2026-11-25 起，本项目自带）

- 离开前：`python3 bin/打包进度.py --lite`（大件要不要带，见 `发件箱/README.md`）
- 接手时：`python3 bin/接手进度.py 收件箱/<包>.zip`（scope 校验 + `.已接手.json` 签名 + 逐文件 sha256）
- 只看不写：`python3 bin/打包进度.py --list` / `python3 bin/接手进度.py <包> --dry-run`
- 包只含本项目（`MANIFEST.scope = {name}`），别的项目的包会被拒绝；同一个包接两次也会被签名拦住。
"""

    AGENTS_TOOLS = """
## 共用工具（macOS：规则/母版在 `../公共层/`，平台件在 `../tools/`，**别复制进本项目**）

```bash
../tools/bin/ffmpeg -version                                             # 例如：视频工具
/Applications/<App>.app/Contents/MacOS/<bin> -b --python <脚本.py>        # 例如：无头渲染器
python3 bin/打包进度.py --list                                           # 交接脚本只用标准库
```

临时目录落 `本目录/.dsh/tmp`；`../公共层/` 只读，规则见 `../公共层/AGENTS.md`。
"""

    AGENTS_SKELETON = """# {name} · 本工作区约定

> 这份文件只在「以 `{name}/` 为工作区」的对话里生效（AGENTS.md 由 DSH 自动注入）。
> 2026-11-26 由 `../公共层/bin/装交接.py` 生成骨架，**项目正文请往下补**：这是什么、先读什么、已知坑。

## 交接（本项目自带）

- 离开前：`python3 bin/打包进度.py --lite`
- 接手时：`python3 bin/接手进度.py 收件箱/<包>.zip`（scope 校验 + `.已接手.json` 签名 + 逐文件 sha256）
- 只看不写：`python3 bin/打包进度.py --list` / `python3 bin/接手进度.py <包> --dry-run`
- 包只含本项目（`MANIFEST.scope = {name}`）；别的项目的包会被拒绝，同一个包接两次也会被签名拦住。
{extra}"""

    HINT = "python3 bin/打包进度.py --lite"
else:
    HINT = "python bin\\打包进度.py --lite"


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}" if u != "B" else f"{n} B"
        n /= 1024


def find_std():
    """标准脚本：优先 `公共层\\bin\\模板\\`，其次引导包/项目 bin/，再退回桌面上任意项目。"""
    cands = [HERE / "模板", HERE / "bin", HERE]
    # 桌面可能被 OneDrive 重定向（本机 = C:\Users\<u>\OneDrive\Desktop）
    for desk in (LAYER.parent, Path.home() / "OneDrive" / "Desktop", Path.home() / "Desktop"):
        if desk.is_dir():
            cands += sorted(desk.glob("*/bin"))
    for c in cands:
        if all((c / n).is_file() for n in STD):
            return c
    sys.exit("找不到标准脚本（打包进度.py / 接手进度.py）：公共层\\bin\\模板\\ 应有这两份，"
             "或把本脚本放回归导包根目录（旁边有 bin/）再跑。")


def survey(root: Path):
    files = total = 0
    tops = {}
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP]
        for fn in fns:
            p = Path(dp) / fn
            if not p.is_file():
                continue
            n = p.stat().st_size
            files += 1
            total += n
            t = tops.setdefault(p.relative_to(root).parts[0], [0, 0])
            t[0] += 1
            t[1] += n
    return files, total, tops


def write_agents(root: Path, name: str, *, patch: bool, append: bool, init: bool) -> None:
    p = root / "AGENTS.md"
    if not p.is_file():
        if init:
            p.write_text(AGENTS_SKELETON.format(name=name, extra=AGENTS_TOOLS), encoding="utf-8")
            print("  新建 AGENTS.md（交接 + 共用工具骨架，正文待补）")
        else:
            print("  ! 没有 AGENTS.md，跳过（新项目加 --init-agents）")
        return

    t = p.read_text(encoding="utf-8")
    if patch and all(s in t for s in AGENTS_OLD):
        t = t.replace(AGENTS_OLD[0], AGENTS_NEW.format(name=name)).replace(AGENTS_OLD[1], "")
        p.write_text(t.replace("\n\n\n", "\n\n"), encoding="utf-8")
        print("  AGENTS.md 的「范围」两条已改成本项目自带交接")
        return

    changed = False
    has_handoff = any(k in t for k in ("## 交接（2026-11-25 起", "## 交接（本项目自带）",
                                       "本项目自带一套交接", "bin\\打包进度.py",
                                       # macOS 口径（2026-11-26 加）：正斜杠路径与 v2 标题也要认，
                                       # 否则重跑会往已经写好的 AGENTS.md 里再追加一节
                                       "bin/打包进度.py", "每个项目独立收发", "本项目自带"))
    has_tools = "共用工具" in t or "公共层\\tools\\py.cmd" in t
    if not has_handoff:
        if not t.endswith("\n"):
            t += "\n"
        t += AGENTS_APPEND.format(name=name)
        changed = True
        print("  AGENTS.md 末尾追加交接小节")
    if not has_tools:
        if not t.endswith("\n"):
            t += "\n"
        t += AGENTS_TOOLS
        changed = True
        print("  AGENTS.md 末尾追加共用工具小节")
    if changed:
        p.write_text(t, encoding="utf-8")
    elif append:
        print("  AGENTS.md 已有交接与共用工具小节，跳过")


def scaffold(root: Path, hint: str, *, patch: bool, append: bool, init: bool, quiet: bool = False) -> None:
    name = root.name
    src = find_std()
    (root / "bin").mkdir(exist_ok=True)
    (root / "收件箱").mkdir(exist_ok=True)
    (root / "发件箱").mkdir(exist_ok=True)

    for f in STD:
        shutil.copy2(src / f, root / "bin" / f)
        if not quiet:
            print(f"  写入 bin/{f}  ({(root / 'bin' / f).stat().st_size} B)")

    files, total, tops = survey(root)
    rows = "\n".join(f"| `{k}` | {v[0]} | {human(v[1])} |"
                     for k, v in sorted(tops.items(), key=lambda kv: -kv[1][1])[:6])
    (root / "收件箱" / "README.md").write_text(INBOX_README.format(name=name), encoding="utf-8")
    (root / "发件箱" / "README.md").write_text(
        OUTBOX_README.format(name=name, files=files, total=human(total), rows=rows, hint=hint),
        encoding="utf-8")
    if not quiet:
        print(f"  写入 收件箱/README.md、发件箱/README.md（{files} 文件 / {human(total)}）")

    write_agents(root, name, patch=patch, append=append, init=init)


def scan(apply: bool, hint: str, extra_exclude, desktop=None) -> int:
    """扫桌面一级目录：还没有 bin\\打包进度.py 的列出来（--apply 就补齐）。"""
    desk = Path(desktop).resolve() if desktop else LAYER.parent
    if not desk.is_dir():
        sys.exit(f"找不到桌面目录：{desk}")
    if desktop is None and (not (LAYER / "AGENTS.md").is_file() or not (LAYER / "bin" / "模板").is_dir()):
        sys.exit(f"--scan 要在 公共层 里跑（当前脚本所在目录 {LAYER} 不像公共层）。\n"
                 f"       把本脚本放回 公共层\\bin\\，或用 --desktop <桌面路径> 指定要扫哪个目录。")
    exclude = {"公共层"} | set(DEFAULT_EXCLUDE) | set(extra_exclude or ())
    todo, opted_out = [], []
    for d in sorted(desk.iterdir()):
        if not d.is_dir() or d.name.startswith(".") or d.name in exclude:
            continue
        if (d / ".no-handoff").is_file():     # 显式退出：别给这个目录铺交接
            opted_out.append(d.name)
            continue
        if (d / "bin" / "打包进度.py").is_file():
            continue
        todo.append(d)

    print(f"桌面：{desk}")
    print(f"排除：{', '.join(sorted(exclude))}")
    if opted_out:
        print(f"按 .no-handoff 退出（不铺）：{len(opted_out)} 个 —— {', '.join(opted_out)}")
    if not todo:
        print("所有一级目录都已有交接脚本（或已按 .no-handoff 退出）。" if opted_out
              else "所有一级目录都已有交接脚本。")
        return 0
    for d in todo:
        print(f"  {'补齐' if apply else '缺'}  {d.name}")
        if apply:
            scaffold(d, hint, patch=False, append=True, init=True)
    if not apply:
        print(f"\n共 {len(todo)} 个待补；加 --apply 当场补齐。")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?")
    ap.add_argument("--patch-agents", action="store_true")
    ap.add_argument("--append-agents", action="store_true")
    ap.add_argument("--init-agents", action="store_true", help="没有 AGENTS.md 就新建骨架（新项目用）")
    ap.add_argument("--hint", default=HINT)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--scan", action="store_true", help="扫描桌面一级目录，列出缺交接的项目")
    ap.add_argument("--apply", action="store_true", help="配合 --scan：真的写文件")
    ap.add_argument("--exclude", action="append", help="--scan 时额外排除的目录名（可重复）")
    ap.add_argument("--desktop", default=None, help="--scan 扫描哪个目录（默认 公共层 的上一级）")
    a = ap.parse_args()

    if a.scan:
        raise SystemExit(scan(a.apply, a.hint, a.exclude, a.desktop))

    if not a.root:
        ap.error("需要 <项目根目录>，或用 --scan")

    root = Path(a.root).resolve()
    if not root.is_dir():
        sys.exit(f"不是目录：{root}")

    if a.list:
        print(f"项目：{root.name}（{root}）")
        print(f"标准脚本来自：{find_std()}")
        print("将写入：bin/打包进度.py、bin/接手进度.py、收件箱/README.md、发件箱/README.md")
        print(f"AGENTS.md：{'有' if (root / 'AGENTS.md').is_file() else '无（--init-agents 会新建）'}")
        print("（--list：未写任何文件）")
        return

    scaffold(root, a.hint, patch=a.patch_agents, append=a.append_agents, init=a.init_agents)
    print(f"\n完成：{root}")


if __name__ == "__main__":
    main()
