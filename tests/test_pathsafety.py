#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""路径安全回归测试 —— 只用标准库，不依赖任何第三方包。

跑法（在仓库根目录）：

    python -m unittest discover -s tests -v
    python tests/test_pathsafety.py

覆盖三件事：

1. `safe_rel()` 的拒绝/放行清单（反斜杠、UNC、盘符、绝对路径、`..` 越界）；
2. 恶意包把条目名写成字面反斜杠时，**不能**写到项目根之外；
3. 项目里已有指向根外的目录联接 / 符号链接时，**不**顺着它写出去。

第 3 条需要建链接的权限：建不出来就 `skipTest`（算跳过、不算失败）。
"""
import binascii
import hashlib
import importlib.util
import json
import os
import random
import shutil
import struct
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent          # <repo>/tests
REPO = HERE.parent                              # <repo>
SCRIPTS = REPO / "skill" / "assets" / "scripts"
RECEIVER = SCRIPTS / "接手进度.py"
PACKER = SCRIPTS / "打包进度.py"
PROJ = "测试项目"


def load_receiver():
    """按路径载入接手脚本（文件名是中文、不是包，不能用普通 import）。"""
    spec = importlib.util.spec_from_file_location("handoff_receiver_under_test", RECEIVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_zip(path, entries):
    """手拼一个 zip。

    为什么不用 `zipfile` 写：它在 Windows 上会把条目名里的 `\\` 归一成 `/`
    （`ZipInfo.__init__` 的行为），这样就没法造出“字面反斜杠”的恶意条目。
    这里直接写字节，才是真实的攻击面。
    """
    local, central, offset = [], [], 0
    for name, data in entries:
        nb = name.encode("utf-8")
        crc = binascii.crc32(data) & 0xFFFFFFFF
        # 0x800 = UTF-8 名称标记
        lh = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0x800, 0, 0, 0x21,
                         crc, len(data), len(data), len(nb), 0) + nb + data
        ch = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0x800, 0, 0, 0x21,
                         crc, len(data), len(data), len(nb), 0, 0, 0, 0, 0, offset) + nb
        local.append(lh)
        central.append(ch)
        offset += len(lh)
    cd = b"".join(central)
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(entries), len(entries),
                       len(cd), offset, 0)
    Path(path).write_bytes(b"".join(local) + cd + eocd)


def manifest_for(entries, scope):
    files = [{"path": n.split("/", 1)[1], "bytes": len(d),
              "sha256": hashlib.sha256(d).hexdigest()} for n, d in entries]
    return json.dumps({"package": "pkg", "scope": scope, "tag": "x86", "files": files},
                      ensure_ascii=False).encode("utf-8")


def make_link(link: Path, target: Path) -> bool:
    """建目录联接（Windows，免管理员）或符号链接（POSIX）；失败返回 False。"""
    try:
        if os.name == "nt":
            r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                               capture_output=True, text=True, errors="replace")
            return r.returncode == 0 and link.exists()
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def drop_link(link: Path) -> None:
    """删链接本身，绝不去动链接指向的内容。"""
    try:
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "rmdir", str(link)],
                           capture_output=True, text=True, errors="replace")
        elif link.is_symlink():
            link.unlink()
    except OSError:
        pass


class PathSafetyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_receiver()
        # 工作目录放在仓库内（沙箱只放行会话工作区；也方便失败时人工看现场）
        cls.work = REPO / (".tmp-tests-%d-%d" % (os.getpid(), random.randint(1000, 9999)))
        cls.work.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.work, ignore_errors=True)

    def project(self, name: str) -> Path:
        proj = self.work / name
        (proj / "bin").mkdir(parents=True, exist_ok=True)
        (proj / "收件箱").mkdir(exist_ok=True)
        shutil.copy2(PACKER, proj / "bin" / PACKER.name)
        shutil.copy2(RECEIVER, proj / "bin" / RECEIVER.name)
        return proj

    def run_receiver(self, proj: Path, zip_name: str):
        return subprocess.run([sys.executable, "bin/" + RECEIVER.name, "收件箱/" + zip_name],
                              cwd=proj, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    # ---- 1. safe_rel 的拒绝/放行清单
    def test_safe_rel(self):
        reject = ["..\\..\\evil.txt", "\\\\srv\\share\\x", "C:/windows/x", "/etc/passwd",
                  "../x", "a/../../b", "..", ""]
        keep = {"normal/file.txt": "normal/file.txt", "中文/文件.md": "中文/文件.md"}
        for name in reject:
            self.assertIsNone(self.mod.safe_rel(name), "应拒绝：%r" % name)
        for name, want in keep.items():
            self.assertEqual(self.mod.safe_rel(name), want)

    # ---- 2. 字面反斜杠条目：不能写到根外
    def test_backslash_entry_cannot_escape(self):
        proj = self.project("反斜杠")
        entries = [("pkg/00-包入口.md", b"# e\n"), ("pkg/ok.txt", b"legit\n"),
                   ("pkg/..\\..\\pwned.txt", b"pwned\n")]
        zp = proj / "收件箱" / "pkg.zip"
        make_zip(zp, entries + [("pkg/MANIFEST.json", manifest_for(entries, proj.name))])
        self.run_receiver(proj, "pkg.zip")
        for p in (self.work / "pwned.txt", proj.parent / "pwned.txt", proj / ".." / "pwned.txt"):
            self.assertFalse(Path(p).exists(), "越界写出去了：%s" % p)

    # ---- 3. 顺着链接写出去：必须被拒
    def test_link_escape_is_refused(self):
        outside = self.work / "outside"
        outside.mkdir(exist_ok=True)
        proj = self.project("链接")
        link = proj / "link"
        if not make_link(link, outside):
            self.skipTest("这台机器建不了目录链接（权限不足），跳过")
        try:
            entries = [("pkg/00-包入口.md", b"# e\n"), ("pkg/link/evil.txt", b"escaped\n")]
            zp = proj / "收件箱" / "pkg.zip"
            make_zip(zp, entries + [("pkg/MANIFEST.json", manifest_for(entries, proj.name))])
            self.run_receiver(proj, "pkg.zip")
            self.assertFalse((outside / "evil.txt").exists(),
                             "顺着链接写到项目根之外了：%s" % (outside / "evil.txt"))
        finally:
            drop_link(link)

    # ---- 4. 正常包仍然能打、能接（回归），且发件箱默认不动
    def _pack(self, proj):
        r = subprocess.run([sys.executable, "bin/" + PACKER.name, "--lite"], cwd=proj,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        pkgs = sorted((proj / "发件箱").glob("*.zip"))
        self.assertTrue(pkgs, "没有产出进度包")
        shutil.copy2(pkgs[0], proj / "收件箱" / pkgs[0].name)
        return pkgs[0]

    def test_normal_package_roundtrip(self):
        proj = self.project("正常")
        pkg = self._pack(proj)
        r2 = self.run_receiver(proj, pkg.name)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertTrue((proj / "收件箱" / ".已接手.json").is_file())
        self.assertTrue(list((proj / "收件箱").glob("接手记录-*.md")))
        # 发件箱默认保留：刚打出来的包还在
        self.assertTrue(pkg.exists(), "发件箱被默认清空了")

    # ---- 5. 越界条目 → 整包拒收：不写文件、不记签名
    def test_unsafe_entry_aborts_whole_package(self):
        proj = self.project("整包拒收")
        entries = [("pkg/00-包入口.md", b"# e\n"), ("pkg/ok.txt", b"legit\n"),
                   ("pkg/../../evil.txt", b"evil\n")]
        zp = proj / "收件箱" / "pkg.zip"
        make_zip(zp, entries + [("pkg/MANIFEST.json", manifest_for(entries, proj.name))])
        r = self.run_receiver(proj, "pkg.zip")
        self.assertNotEqual(r.returncode, 0, "应当拒收")
        self.assertFalse((proj / "ok.txt").exists(), "整包拒收时不应写入任何文件")
        self.assertFalse((proj / "收件箱" / ".已接手.json").exists(), "拒收不应记签名")

    # ---- 6. --clean-outbox 才清发件箱
    def test_clean_outbox_flag(self):
        proj = self.project("清发件箱")
        pkg = self._pack(proj)
        r = subprocess.run([sys.executable, "bin/" + RECEIVER.name,
                            "收件箱/" + pkg.name, "--clean-outbox"],
                           cwd=proj, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(pkg.exists(), "--clean-outbox 应当清掉发件箱 zip")


if __name__ == "__main__":
    unittest.main(verbosity=2)
