---
name: handoff
description: Use when work must move between machines (macOS and Windows) through the file system — packing a project's progress into a handoff zip, receiving such a zip, setting up per-project handoff rules, fixing packages that fail scope/signature/checksum, or when the user mentions 双机交接 / 打包进度 / 接手进度 / 引导包 / 交接规则. It installs or repairs the per-project bin scripts, the inbox/outbox layout, and the dsh-autohandoff auto-scaffold plugin.
---

# 双机交接（handoff）

一套"每个项目自己收发"的交接机制：规则 + 标准脚本 + 自动铺交接插件。
目标是**任何一台装了 DSH 的机器，拷一个目录就能用**，不依赖记忆或口头约定。

## 这套东西保证什么

- 每个项目是独立工作区根：`bin/打包进度.py`、`bin/接手进度.py`、`收件箱/`、`发件箱/`；
- 包只含本项目，`MANIFEST.json` 里写 `scope`（项目目录名）与逐文件 sha256；
- 接手四道关：**scope 一致 → 签名未接过 → 逐文件 sha256 → 合并解压**，任何一道不过都不落盘；
- 新项目第一次开会话时**自动铺**（插件 `dsh-autohandoff`），忘了铺也不用记；
- 规则文件有版本号，接手时自动按母版归一化（`--no-sync-rules` 可关）。

## 安装（一台新机器）

1. **装 skill**：在本目录里 `python3 install.py --apply --install-skill`（Windows 用 `python`）——
   它把自己同步到 `<DSH home>/skills/handoff`
   （Windows `%USERPROFILE%\.dsh\skills\handoff`，mac `~/.dsh/skills/handoff`）。幂等、不删除；
   手动 `cp -R skill ~/.dsh/skills/handoff` 等价。以后改了仓库，重跑这一条即可（DSH 会自动重扫，无需重启）。
2. **一条命令铺层**（只写 `桌面/公共层/`，不碰项目）：

   ```bash
   python3 ~/.dsh/skills/handoff/install.py                    # 先看（dry-run，默认）
   python3 ~/.dsh/skills/handoff/install.py --apply --smoke    # 真写 + 临时项目自测 8 项
   ```

   Windows 用 `python`。铺出：规则、`bin/装交接.py`、`bin/打包引导包.py`、`bin/模板/`（两个标准脚本）、
   `plugins/dsh-autohandoff/`、`_日志/ _历史/ 引导包/ 素材库/ 工具/`、`AGENTS.md` 骨架（已有则保留，要覆盖加 `--force-agents`）。
   幂等：重复跑只覆盖内容不同的文件，从不删除；`--with-references` 顺便铺「坑与教训」「迁移检查清单」到 `公共层/参考/`。
3. **项目变桌面同级**：每个项目是桌面的直接子目录；还嵌在旧工作区里的，`mv` 出来（只移动、不删除、核对文件数）。
   判据：目录里有 `bin/打包进度.py` 就是工作区根。
4. **补交接**：`python 公共层/bin/装交接.py --scan` 看谁缺 → `--scan --apply` 补齐；
   单个项目 `装交接.py <项目> --append-agents --init-agents`。
5. **装插件**（python 装不了，要在 DSH 里）：
   `plugin_manager(action="install_bundle", target="<桌面>/公共层/plugins/dsh-autohandoff")`；
   `application: restart-required` 就重启 DSH；插件设置里解释器默认自动试 `python3` / `python`。
6. **冒烟**：新建空目录 → 在里面开会话 → 应出现 `bin/`、收发箱与 AGENTS 两节；动作写在公共层 `_日志/自动交接.log`。
   没铺上就 `python 公共层/bin/装交接.py --scan --apply` 兜底。
7. **发布前**（改这套东西时）：`python bin/发布检查.py` —— 0 ERROR 才算干净。

## 日常两个动作

```bash
# 离开前（在要离开的项目根目录）
python bin/打包进度.py --list     # 只看不写
python bin/打包进度.py --lite     # → 发件箱/<项目名>-进度-YYYYMMDD-HHMM-<机器>.zip

# 到另一台（在对应的项目根目录）
python bin/接手进度.py 收件箱/<包>.zip --dry-run
python bin/接手进度.py 收件箱/<包>.zip
```

- 打包前先 `--list` 记文件数；包内条目数 = 文件数 + `00-包入口.md` + `MANIFEST.json`，对不上先查。
- 接手成功会把项目根规则按母版归一化；**发件箱默认保留**（可能是还没送出去的包），要清加 `--clean-outbox`。
- 接手完**再把项目 `bin/` 刷一遍**（`装交接.py <项目>`）：包里的脚本可能是对方打包时的旧版 ——
  `--scan --apply` 对已有脚本的项目无效，必须显式传项目名。

## 什么时候不要用

- 同一台机器内部搬文件：直接拷，不需要包。
- 平台二进制（渲染器、ffmpeg 等专用程序）：永远不进包，各机自备（`.local/`、`tools/` 均被排除）。
- 需要版本控制/多人协作的代码：用 git；这套机制只保证"整目录快照 + 可校验"。

## 排障

| 症状 | 先看 |
|---|---|
| `scope 不一致` 被拒 | 目标项目目录名与包内 `MANIFEST.scope` 不同（改名后尤其容易）；别用 `--force` 硬合 |
| `已经接过` 被拒 | `收件箱/.已接手.json` 里有同字节包的记录；真要再合加 `--force`，或换个包 |
| `sha256 不符` | 传输截断/被改；重传，不要强解 |
| 包里缺文件 | 打包时权限锁死的目录被**静默跳过**；`--list` 对文件数 |
| 接手后脚本变旧 | 包会覆盖 `bin/`；按上文"归一化"刷回来 |
| 输出是方块/乱码 | 脚本在非终端已强制 UTF-8；若仍出现，检查是否有旧版脚本 |
| 新项目没自动铺 | 插件未装/未重启；或目录不在桌面一级；或缺 `python`、或目录里有 `.no-handoff` |
| 改了规则/脚本但 agent 还用旧版 | 跑 `install.py --apply --install-skill` 刷新 skill 自身；公共层与项目副本另按 README「更新」第 2、3 步刷 |

## 参考

| 内容 | 文件 |
|---|---|
| 规则全文（目录布局、包格式、四道关、忽略清单、教训） | `references/交接规则.md` |
| 踩过的坑：症状 → 原因 → 修法 | `references/坑与教训.md` |
| 新机器/新项目的逐步清单（含双平台命令） | `references/迁移检查清单.md` |
| 脚本源码 | `assets/scripts/{装交接,打包进度,接手进度,打包引导包}.py` |
| 插件源码 | `assets/plugin/dsh-autohandoff/` |
