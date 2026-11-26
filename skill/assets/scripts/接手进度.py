#!/usr/bin/env python3
"""接手：校验并解压一个进度包，写接手记录（只服务本项目）。

ROOT = 本脚本上一级目录（= 项目根）。一道 scope 校验挡住"合错项目"，
一个签名文件挡住"同一个包合两遍"：

  * scope  —— 包内 MANIFEST 的 `scope` 与本项目目录名不符 → 拒绝（--force 可强解）；
  * 签名   —— 合完在包旁写 `.已接手.json`（包名 + 字节数 + sha256）；
              同一个包再来一次 → 拒绝（--force 可强解）。

接手记录写在包所在目录（通常就是本项目 收件箱/），不另建。

用法：
  python3 bin/接手进度.py 收件箱/<项目名>-进度-YYYYMMDD-HHMM-<机型>.zip
  python3 bin/接手进度.py <包> --dry-run        # 只校验（含 scope 与签名）不落盘
  python3 bin/接手进度.py <包> --force          # 校验/scope/签名不过也解压（**不豁免路径校验**）
  python3 bin/接手进度.py <包> --clean-outbox   # 顺手清掉本项目发件箱第一层的旧 zip

两条安全约定（2026-11-26 起）：

1. **包内路径先全量预检**：任何一条越界/非法（反斜杠、`..`、盘符、指向根外的链接）→
   整包拒收，一个文件都不写、不记签名、不清发件箱 —— 不留"半个包"的状态。
2. **发件箱默认不动**：`发件箱/` 里的 zip 可能是"打好还没发出去"的包，
   自动删会丢东西，所以只在显式加 `--clean-outbox` 时才清第一层的 zip。

规则见工作区根目录的 `工作流-双机交接规则.md`。
"""
import argparse
import hashlib
import json
import os
import posixpath
import re
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCOPE = os.path.basename(os.path.normpath(ROOT))
# 生成的文档里写的命令要跟本机平台一致：Windows 上 `python3` 是商店占位符（退出码 9009）
PY = "python" if os.name == "nt" else "python3"
SIGN_NAME = ".已接手.json"
OUTBOX = os.path.join(ROOT, "发件箱")
# 规则：母版在 公共层/，各项目根放同名副本（v3.2 口径）。接手后按版本号决定是否归一化。
LAYER = os.path.dirname(os.path.normpath(ROOT))
RULES_NAME = "工作流-双机交接规则.md"
MASTER_RULES = os.path.join(LAYER, "公共层", RULES_NAME)

# 输出编码，两个坑一起处理（同 打包进度.py）：
#   1) Windows 控制台默认 cp936（GBK）：遇到 GBK 里没有的符号不是"打成乱码"，而是直接
#      UnicodeEncodeError 崩掉 —— 实测 `python bin\接手进度.py` 会死在校验通过那一行；
#   2) 被 agent / 管道 / 重定向捕获时（非终端），cp936 字节会被读取端当 UTF-8 解成乱码。
# 所以：终端（人看）保持控制台编码、只替换错误字符；非终端一律写 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream.isatty():
            _stream.reconfigure(errors="replace")
        else:
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):  # 老 Python / 被重定向到不支持 reconfigure 的对象
        pass


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}" if u != "B" else f"{n} B"
        n /= 1024


def safe_rel(name):
    """把包内路径规范化成安全的相对路径；拒绝绝对路径、盘符、反斜杠与 .. 越界。

    包是不可信输入：`MANIFEST.json` 与 zip 条目都由打包方自己写，四道关（scope/签名/
    sha256/解压）挡不住"自己声明自己校验"的恶意包，路径安全只能靠这里。

    包内路径一律 POSIX 风格（打包端做了 `rel.replace(os.sep, "/")`）。Windows 上
    `os.path.join` 会把反斜杠当分隔符，所以反斜杠整条拒绝 —— 否则 `..\\..\\x` 会绕过
    posixpath 的检查、落到项目根之外。UNC（`\\\\srv\\share`）同一条顺带挡住。
    """
    if not name or "\\" in name:
        return None
    if name.startswith("/") or ":" in name.split("/")[0]:
        return None
    p = posixpath.normpath(name)
    if p in ("", ".", "..") or p.startswith("../") or p.startswith("/") or ":" in p.split("/")[0]:
        return None
    return p


def within_root(path):
    """解析符号链接后，目标必须仍在项目根内（写入前的第二道校验）。"""
    root = os.path.realpath(ROOT)
    target = os.path.realpath(path)
    return target == root or target.startswith(root + os.sep)


def file_sha(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def load_sign(sign_path):
    if not os.path.isfile(sign_path):
        return {}
    try:
        data = json.loads(open(sign_path, encoding="utf-8").read())
    except (ValueError, OSError):
        return {}
    return data.get("packages", {}) if isinstance(data, dict) else {}


def save_sign(sign_path, packages):
    tmp = sign_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "project": SCOPE, "packages": packages},
                  f, ensure_ascii=False, indent=2)
    os.replace(tmp, sign_path)


def clean_outbox(dry_run=False, enable=False):
    """清掉发件箱第一层的旧 zip —— **只在显式 `--clean-outbox` 时做**。

    为什么默认不动：`发件箱/` 里的 zip 可能是"打好、还没拷给对方"的包，
    接手成功并不代表它们已经送达；默认删会静默丢掉快照。
    只认第一层的 `*.zip`；README、子目录（如 `_历史/`）一律不动。
    返回 (个数, 总字节, 文件名列表)。
    """
    if not enable or not os.path.isdir(OUTBOX):
        return 0, 0, []
    victims = []
    for f in sorted(os.listdir(OUTBOX)):
        p = os.path.join(OUTBOX, f)
        if f.lower().endswith(".zip") and os.path.isfile(p):
            victims.append(f)
    total = sum(os.path.getsize(os.path.join(OUTBOX, f)) for f in victims)
    if not dry_run:
        for f in victims:
            os.remove(os.path.join(OUTBOX, f))
    return len(victims), total, victims


def _ver_of(text):
    """从规则文件首行抓版本号：`改版 v3.2` → (3, 2)；抓不到返回 None。"""
    m = re.search(r"改版\s*v(\d+)\.(\d+)", text) or re.search(r"v(\d+)\.(\d+)", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def sync_rules(payload, dry_run=False, no_sync=False):
    """接手后核对规则：包内那份 vs `公共层/工作流-双机交接规则.md`（母版）。

    返回 dict：status ∈ {no-master, no-pkg-rule, same, synced, would-sync,
                        keep-sync-off, pkg-newer, unknown}，供打印与接手记录使用。
    只做两个安全动作：母版**更新**时把母版覆盖回项目；包内版本**更新**时只告警不动手
    （那种情况说明对端先改了规则，应先把母版升上去，见规则 §4.0）。
    """
    pkg = next((data for rel, data in payload if rel == RULES_NAME), None)
    if not os.path.isfile(MASTER_RULES):
        return {"status": "no-master", "master": MASTER_RULES}
    master_bytes = open(MASTER_RULES, "rb").read()
    master_ver = _ver_of(master_bytes.decode("utf-8", "replace"))
    if pkg is None:
        return {"status": "no-pkg-rule", "master_ver": master_ver}
    pkg_ver = _ver_of(pkg.decode("utf-8", "replace"))

    if pkg == master_bytes:
        return {"status": "same", "ver": master_ver, "master_ver": master_ver}
    if pkg_ver and master_ver and pkg_ver > master_ver:
        return {"status": "pkg-newer", "pkg_ver": pkg_ver, "master_ver": master_ver}
    if pkg_ver is None or master_ver is None:
        return {"status": "unknown", "pkg_ver": pkg_ver, "master_ver": master_ver}
    if no_sync:
        return {"status": "keep-sync-off", "pkg_ver": pkg_ver, "master_ver": master_ver}
    if dry_run:
        return {"status": "would-sync", "pkg_ver": pkg_ver, "master_ver": master_ver}
    with open(os.path.join(ROOT, RULES_NAME), "wb") as f:
        f.write(master_bytes)
    return {"status": "synced", "pkg_ver": pkg_ver, "master_ver": master_ver}


def report_rules(r, dry_run=False):
    st = r["status"]
    if st == "no-master":
        print(f"\n规则：找不到母版 {r['master']}，跳过版本核对")
    elif st == "no-pkg-rule":
        print("\n规则：包内没有规则文件，未核对")
    elif st == "same":
        print(f"\n规则：与母版一致（v{r['ver'][0]}.{r['ver'][1]}）")
    elif st in ("synced", "would-sync"):
        pv, mv = r["pkg_ver"], r["master_ver"]
        verb = "将按母版归一化" if st == "would-sync" else "已按母版归一化"
        print(f"\n规则：包内 v{pv[0]}.{pv[1]} → 母版 v{mv[0]}.{mv[1]}，{verb}")
    elif st == "keep-sync-off":
        pv, mv = r["pkg_ver"], r["master_ver"]
        print(f"\n规则：包内 v{pv[0]}.{pv[1]} / 母版 v{mv[0]}.{mv[1]}，按 --no-sync-rules 未同步")
    elif st == "pkg-newer":
        pv, mv = r["pkg_ver"], r["master_ver"]
        print(f"\n规则：⚠ 包内 v{pv[0]}.{pv[1]} 比母版 v{mv[0]}.{mv[1]} 新 —— 未自动降级。")
        print("      先把这份规则升成母版（或合并对端的规则补丁包），再按 §4.0 ④ 归一化。")
    elif st == "unknown":
        print("\n规则：包内与母版不一致，但版本号解析不出 —— 请人工比对后再归一化")
    return st


def rules_line(r):
    """接手记录里那行规则说明。"""
    st = r["status"]
    if st == "same":
        return f"与母版一致（v{r['ver'][0]}.{r['ver'][1]}）"
    if st == "synced":
        p, m = r["pkg_ver"], r["master_ver"]
        return f"包内 v{p[0]}.{p[1]} → 母版 v{m[0]}.{m[1]}，**已按母版归一化**"
    if st == "pkg-newer":
        p, m = r["pkg_ver"], r["master_ver"]
        return f"⚠ 包内 v{p[0]}.{p[1]} 比母版 v{m[0]}.{m[1]} 新，**未自动降级**（需先升母版再归一化）"
    if st == "keep-sync-off":
        return "按 `--no-sync-rules` 未同步（与母版可能不一致）"
    if st == "no-master":
        return "找不到公共层母版，跳过核对"
    if st == "no-pkg-rule":
        return "包内没有规则文件，未核对"
    return "包内与母版不一致且版本号解析不出，需人工比对"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("package")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--clean-outbox", action="store_true", dest="clean_outbox",
                    help="接手后清掉 发件箱/ 第一层的旧 zip（默认保留：里面可能是还没发出去的包）")
    ap.add_argument("--keep-outbox", action="store_true",
                    help="已弃用（现在默认就保留；保留它是为了旧命令不报错）")
    ap.add_argument("--no-sync-rules", action="store_true",
                    help="接手后不按母版归一化项目根的规则文件（默认会，且只在母版更新时）")
    a = ap.parse_args()

    if not os.path.isfile(a.package):
        sys.exit(f"找不到包：{a.package}")

    pkg_file = os.path.basename(a.package)
    sign_path = os.path.join(os.path.dirname(os.path.abspath(a.package)), SIGN_NAME)
    zip_sha = file_sha(a.package)
    zip_bytes = os.path.getsize(a.package)

    t0 = time.time()
    with zipfile.ZipFile(a.package) as z:
        crc_bad = z.testzip()
        names = z.namelist()
        prefix = names[0].split("/")[0] if names else ""
        man_name = f"{prefix}/MANIFEST.json"
        if man_name not in names:
            sys.exit(f"包内缺少 {man_name}，不是本规则产出的进度包")
        manifest = json.loads(z.read(man_name).decode("utf-8"))

        print(f"本项目：{SCOPE}（{ROOT}）")
        print(f"包：{manifest.get('package')}　来源机：{manifest.get('tag')}　"
              f"模式：{manifest.get('mode')}　时间：{manifest.get('created')}")

        # ---- scope 校验：挡住"合错项目"
        pkg_scope = manifest.get("scope")
        if pkg_scope:
            print(f"scope：包={pkg_scope}　本项目={SCOPE}　"
                  f"{'一致' if pkg_scope == SCOPE else '✗ 不符'}")
            if pkg_scope != SCOPE and not a.force:
                sys.exit(
                    f"拒绝接手：这个包是给 `{pkg_scope}` 的，你正在 `{SCOPE}` 里接。\n"
                    f"  正确做法：把包放到 `{pkg_scope}/收件箱/`，在那个项目里跑它的 bin/接手进度.py。\n"
                    f"  确实要强解到本项目：加 --force（会把 {pkg_scope}/ 的内容铺进本项目，通常不是你要的）。")
        else:
            print("scope：（包内没有 scope 字段，按老包处理，跳过跨项目校验）")

        # ---- 签名校验：挡住"同一个包合两遍"
        packages = load_sign(sign_path)
        prev = packages.get(pkg_file)
        if prev and prev.get("sha256") == zip_sha and prev.get("bytes") == zip_bytes:
            print(f"签名：`{pkg_file}` 已于 {prev.get('merged_at')} 接手过")
            if not a.force:
                sys.exit(f"拒绝接手：这个包已经接手过了（{SIGN_NAME} 记录在 {prev.get('merged_at')}）。\n"
                         f"  确认要再合一遍：加 --force。")
        else:
            print(f"签名：{SIGN_NAME} 里没有这个包的记录（首次接手）")

        print(f"CRC：{'通过' if crc_bad is None else f'损坏 {crc_bad}'}")

        print(f"\n逐文件校验 {len(manifest['files'])} 个 …")
        bad, payload = [], []
        for e in manifest["files"]:
            name = f"{prefix}/{e['path']}"
            if name not in names:
                bad.append((e["path"], "缺失"))
                continue
            data = z.read(name)
            if len(data) != e["bytes"]:
                bad.append((e["path"], "大小不符"))
            elif hashlib.sha256(data).hexdigest() != e["sha256"]:
                bad.append((e["path"], "哈希不符"))
            else:
                payload.append((e["path"], data))

        if bad:
            print(f"  [X] {len(bad)} 处异常：")
            for p, why in bad[:15]:
                print(f"      {why}  {p}")
            if not a.force:
                sys.exit("校验未通过，已中止（确认要用 --force 强解）")
            print("  --force 已指定，继续解压")
        else:
            print("  [OK] 全部一致")

    # 路径预检（放在 dry-run 之前：只校验也该报出"这包接不了"）——
    # 任何一条越界/非法就整包拒收：不写文件、不记签名、不清发件箱，
    # 避免留下"半个包 + 已接手标记"的死状态。--force 不豁免这一条。
    skipped = {"00-包入口.md", "MANIFEST.json"}
    plans, unsafe = [], []
    for rel, data in payload:
        if rel in skipped:
            continue
        sr = safe_rel(rel)
        if sr is None or not within_root(os.path.join(ROOT, sr)):
            unsafe.append(rel)
        else:
            plans.append((sr, data))
    if unsafe:
        print(f"\n路径预检：{len(unsafe)} 条非法/越界路径 —— 整包拒收，未写入任何文件：")
        for p in unsafe[:10]:
            print(f"  - {p}")
        sys.exit("拒绝接手：包内含越界路径。--force 也不豁免这一条（绝不写到项目根之外）。\n"
                 "  多半是包被改过或来源不可信；请人工核对包内容后重新打包。")

    if a.dry_run:
        report_rules(sync_rules(payload, dry_run=True, no_sync=a.no_sync_rules), dry_run=True)
        n_prev, bytes_prev, _ = clean_outbox(dry_run=True, enable=a.clean_outbox)
        if not a.clean_outbox:
            print("\n发件箱：默认保留（要清加 --clean-outbox）")
        elif n_prev:
            print(f"\n发件箱：按 --clean-outbox，真接手后会清掉 {n_prev} 个 zip（{human(bytes_prev)}）")
        else:
            print("\n发件箱：没有 zip 可清")
        print(f"--dry-run：未落盘。用时 {time.time()-t0:.1f}s")
        return

    # 解压合并（plans 已在上面算好、校验过）
    written, overwritten = [], []
    for sr, data in plans:
        dst = os.path.join(ROOT, sr)
        if os.path.exists(dst):
            overwritten.append(sr)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(data)
        written.append(sr)

    # 规则归一化（v3.2 口径）：包内那份 vs 公共层母版；母版更新才覆盖，包内更新只告警
    rules = sync_rules(payload, no_sync=a.no_sync_rules)
    report_rules(rules)

    # 接手记录：写在包所在目录（通常就是 收件箱），不在项目里另建一份
    stamp = time.strftime("%Y%m%d-%H%M")
    rec_dir = os.path.dirname(os.path.abspath(a.package))
    rec = os.path.join(rec_dir, f"接手记录-{stamp}.md")
    with open(rec, "w", encoding="utf-8") as f:
        f.write(f"# 接手记录 {time.strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"- 项目：**{SCOPE}**\n")
        f.write(f"- 包：`{pkg_file}`　来源机：**{manifest.get('tag')}**　模式：{manifest.get('mode')}\n")
        f.write(f"- scope：包={manifest.get('scope')}　本项目={SCOPE}\n")
        f.write(f"- 写入 {len(written)} 个文件，覆盖 {len(overwritten)} 个\n")
        f.write(f"- 规则：{rules_line(rules)}\n")
        if overwritten:
            f.write("\n## 被覆盖的本机文件\n\n")
            for p in overwritten:
                f.write(f"- `{p}`\n")
        f.write("\n## 下一步\n\n"
                "1. 读包内 `00-包入口.md`（不落地，需要时从包里取）\n"
                "2. 按项目文档继续\n"
                f"3. 离开本机前在本项目跑 `{PY} bin/打包进度.py`（macOS/Linux 用 python3，Windows 用 python）\n")

    # 写签名（最后一步：解压成功才记）
    packages = load_sign(sign_path)
    packages[pkg_file] = {
        "sha256": zip_sha, "bytes": zip_bytes,
        "merged_at": time.strftime("%Y-%m-%d %H:%M"), "files": len(written),
        "package": manifest.get("package"), "scope": manifest.get("scope"),
    }
    save_sign(sign_path, packages)

    # ---- 收尾：发件箱默认保留（里面可能是还没送出去的包），只有显式 --clean-outbox 才清
    n_clean, bytes_clean, cleaned = clean_outbox(enable=a.clean_outbox)
    if not a.clean_outbox:
        print("\n发件箱：保留原样（要清加 --clean-outbox）")
    elif n_clean:
        print(f"\n发件箱：按 --clean-outbox 清掉 {n_clean} 个 zip（{human(bytes_clean)}）")
        for f in cleaned:
            print(f"  - {f}")
    else:
        print("\n发件箱：没有 zip 可清")

    if cleaned:
        with open(rec, "a", encoding="utf-8") as f:
            f.write(f"\n## 收尾\n\n- 按 --clean-outbox 清掉发件箱 zip {n_clean} 个（{human(bytes_clean)}）："
                    + "、".join(f"`{x}`" for x in cleaned) + "\n")

    print(f"\n写入 {len(written)} 个文件（其中覆盖 {len(overwritten)} 个）")
    print(f"接手记录：{rec}")
    print(f"签名：{sign_path}")
    print(f"用时 {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
