#!/usr/bin/env python3
"""打包本项目进度，产出到本项目自己的 发件箱/。

一台机器上每个项目都是独立工作区：ROOT = 本脚本上一级目录（= 项目根），
打出来的包 `scope` 记的就是这个项目目录名，接手方据此拒绝"合错项目"。

用法：
  python3 bin/打包进度.py                    # 全量
  python3 bin/打包进度.py --lite             # 跳过 generate/3d 与 **/runs/
  python3 bin/打包进度.py --tag x86          # 手动指定来源机标签（默认自动探测）
  python3 bin/打包进度.py --exclude 某目录 --exclude 另一个
  python3 bin/打包进度.py --out ../发件箱     # 写到别处（默认本项目 发件箱/）
  python3 bin/打包进度.py --list             # 只报账：会打哪些文件、多大，不写 zip

产出：<out>/<项目名>-进度-YYYYMMDD-HHMM-<tag>.zip，内含 00-包入口.md + MANIFEST.json + 项目原样。
      文件名以**项目名开头**（2026-11-26 起）：批量传输时一眼能看出是哪个项目，日期用来判断新旧。
规则见工作区根的 `工作流-双机交接规则.md`。
"""
import argparse
import hashlib
import json
import os
import platform
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPE = os.path.basename(os.path.normpath(ROOT))

# 输出编码，两个坑一起处理（同 接手进度.py）：
#   1) Windows 控制台是 cp936，输出 GBK 没有的符号会直接抛 UnicodeEncodeError（是崩溃，不是乱码）；
#   2) 被 agent / 管道 / 重定向捕获时（非终端），cp936 字节会被读取端当 UTF-8 解成乱码
#      —— 2026-11-25 实测：在 pwsh 里读 `python bin\打包进度.py --list` 全是方块。
# 所以：终端（人看）保持控制台编码、只替换错误字符；非终端一律写 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream.isatty():
            _stream.reconfigure(errors="replace")
        else:
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

# 注意：这里**不**排除 "tools" —— 平台件已统一到 `公共层\tools`（不在任何项目内，本来就不会进包），
# 项目自己的 `tools\` 是项目资产：里面的构建脚本必须跟着包走（2026-11-25 修）。
IGNORE_DIRS = {"收件箱", "发件箱", ".dsh", ".local", ".git", "node_modules",
               ".venv", "venv", "__pycache__", ".idea", ".vscode", ".pytest_cache"}
IGNORE_SUFFIX = (".zip", ".tar.gz", ".tgz", ".7z", ".dmg", ".pyc", ".pyo")
IGNORE_NAMES = {".DS_Store", "Thumbs.db"}
# 包自身的元数据绝不能当载荷收进来：项目根若残留上一手的 00-包入口.md，
# 会和本脚本新写的同名文件撞名 —— MANIFEST 出现两条同名条目，接手方必然校验失败。
ROOT_META = {"00-包入口.md", "MANIFEST.json"}
LITE_EXTRA_DIRS = {os.path.join("generate", "3d")}
LITE_EXTRA_NAME = "runs"


def detect_tag():
    if platform.system() == "Darwin":
        return "mac"
    m = platform.machine().lower()
    if m in ("x86_64", "amd64", "i386", "i686"):
        return "x86"
    return m or "unknown"


def collect(root, lite=False, extra_exclude=()):
    out = []
    extra = {os.path.normpath(e) for e in extra_exclude}
    for dp, dns, fns in os.walk(root):
        rel_dir = os.path.relpath(dp, root)
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in sorted(dns):
            full = os.path.normpath(os.path.join(rel_dir, d))
            if d in IGNORE_DIRS or full in extra:
                continue
            if lite and (full in LITE_EXTRA_DIRS or d == LITE_EXTRA_NAME):
                continue
            keep.append(d)
        dns[:] = keep
        for fn in sorted(fns):
            if fn in IGNORE_NAMES or fn.endswith(IGNORE_SUFFIX):
                continue
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if rel in ROOT_META:  # 只排除根级，子目录里同名文件照收
                continue
            out.append((p, rel))
    return out


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}" if u != "B" else f"{n} B"
        n /= 1024


def summarize(files):
    tops, total = {}, 0
    for path, rel in files:
        n = os.path.getsize(path)
        total += n
        top = rel.split("/")[0]
        tops[top] = tops.get(top, 0) + n
    return tops, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lite", action="store_true", help="跳过 generate/3d 与 **/runs/")
    ap.add_argument("--tag", default=None, help="来源机标签，默认自动探测")
    ap.add_argument("--out", default=None, help="输出目录，默认本项目 发件箱/")
    ap.add_argument("--exclude", action="append", default=[], help="额外排除（相对项目根）")
    ap.add_argument("--list", action="store_true", help="只报账，不写 zip")
    ap.add_argument("--allow-foreign-out", action="store_true",
                    help="允许 --out 指向别的项目的 收件箱/发件箱（默认拒绝，防串门）")
    a = ap.parse_args()

    tag = a.tag or detect_tag()
    files = collect(ROOT, lite=a.lite, extra_exclude=a.exclude)
    if not files:
        sys.exit("没有可打包的文件")

    tops, total = summarize(files)

    if a.list:
        print(f"项目：{SCOPE}（{ROOT}）")
        print(f"scope 将写入 MANIFEST：{SCOPE}")
        print(f"模式：{'lite' if a.lite else 'full'}　会打包 {len(files)} 个文件 / {human(total)}")
        print("顶层：")
        for k in sorted(tops, key=lambda x: -tops[x]):
            print(f"  {human(tops[k]):>9}  {k}")
        print("\n（--list：未写任何文件）")
        return

    out_dir = a.out or os.path.join(ROOT, "发件箱")
    # 唯一能把包"送错门"的口子就是 --out：写到自己项目以外任何一个 收件箱/发件箱 都拦下。
    # （写到 U 盘、共享目录、旧包归档目录不受影响 —— 那些不叫 收件箱/发件箱。）
    out_abs = os.path.abspath(out_dir)
    if (os.path.basename(out_abs) in ("收件箱", "发件箱")
            and os.path.dirname(out_abs) != os.path.abspath(ROOT)
            and not a.allow_foreign_out):
        sys.exit(
            f"拒绝输出到别人的收件箱/发件箱：{out_abs}\n"
            f"  本项目自己的是：{os.path.join(ROOT, '发件箱')}\n"
            f"  确实要写到别的项目的收发件箱，加 --allow-foreign-out。")
    os.makedirs(out_dir, exist_ok=True)

    stamp = time.strftime("%Y%m%d-%H%M")
    # 2026-11-26 起：项目名打头，避免批量传输时只有时间戳分不清是谁的包
    base_pkg = f"{SCOPE}-进度-{stamp}-{tag}"
    pkg = base_pkg
    seq = 2
    while os.path.exists(os.path.join(out_dir, pkg + ".zip")):
        pkg = f"{base_pkg}-{seq}"
        seq += 1
    zip_path = os.path.join(out_dir, pkg + ".zip")

    t0 = time.time()
    entries = []

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as z:
        for path, rel in files:
            data = open(path, "rb").read()
            z.writestr(f"{pkg}/{rel}", data)
            entries.append({"path": rel, "bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()})

    # 自动入口
    lines = [
        f"# 00 · 包入口（{pkg}）", "",
        f"- 来源机标签：**{tag}**　　打包时间：{time.strftime('%Y-%m-%d %H:%M')}"
        f"　　模式：{'精简 (--lite)' if a.lite else '全量'}",
        f"- 范围：**只含本项目 `{SCOPE}/`**（MANIFEST 的 `scope` = `{SCOPE}`，与项目不符的包会被接手脚本拒绝）",
        f"- 文件数：**{len(entries)}**　　解压后：**{human(total)}**",
        "- 交接规则：见工作区根目录 `工作流-双机交接规则.md`", "",
        "## 接手三步", "",
        "```bash",
        f"cd {SCOPE}",
        f"python3 bin/接手进度.py 收件箱/{pkg}.zip    # macOS / Linux",
        f"python  bin\\接手进度.py 收件箱\\{pkg}.zip    # Windows",
        "```", "",
        "脚本先按 `MANIFEST.json` 逐文件校验、核对 `scope`、查 `.已接手.json` 签名，再合并解压并写接手记录。", "",
        "## 顶层内容", "",
        "| 目录/文件 | 体积 |", "|---|---|",
    ]
    for k in sorted(tops, key=lambda x: -tops[x]):
        lines.append(f"| `{k}` | {human(tops[k])} |")
    lines += ["", "## 注意", "",
              "- 平台二进制（`tools/`）、`收件箱/` `发件箱/`、缓存均已排除，包内不会出现旧包。",
              "- 私有 GT / 标准答案若在项目里，包内就有，别把包发给不该看答案的人。"]
    entry = "\n".join(lines).encode("utf-8")

    manifest = {
        "package": pkg, "scope": SCOPE, "tag": tag,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": "lite" if a.lite else "full",
        "totals": {"files": len(entries) + 2, "uncompressed_bytes": total},
        "files": entries + [
            {"path": "00-包入口.md", "bytes": len(entry),
             "sha256": hashlib.sha256(entry).hexdigest(), "role": "entry"}],
    }
    with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr(f"{pkg}/00-包入口.md", entry)
        z.writestr(f"{pkg}/MANIFEST.json",
                   json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))

    size = os.path.getsize(zip_path)
    print(f"已打包：{zip_path}")
    print(f"  scope={SCOPE}  {len(entries)} 个文件 / 解压后 {human(total)} / 压缩包 {human(size)} / 用时 {time.time()-t0:.1f}s")
    print(f"  顶层：{', '.join(sorted(tops, key=lambda x: -tops[x])[:6])}")


if __name__ == "__main__":
    main()
