# dsh-handoff · 双机交接工具链

> 在 **macOS ⇄ Windows** 两台机器之间搬项目进度的最小机制：一套规则、四个标准脚本、一个自动铺交接的 DSH 插件。
> 目标是做成可开源分发的 **DSH skill**：拷 `skill/` 一个目录，任何一台装了 DSH 的机器就能用。
>
> 当前版本：**v3.6**（2026-11-26）· 状态：可公开分发（规则 + 脚本 + 插件 + skill 载荷，均无本机标识）
> 仓库：<https://github.com/TL0121/dsh-handoff> · 许可：MIT（© 2026 TL0121）

```bash
git clone https://github.com/TL0121/dsh-handoff.git
```

## 解决什么

两台机器来回切，最容易丢的不是文件，是**规矩**：

- 忘了在离开前打包 → 这一轮改动等于没交接；
- 把 A 项目的包丢进 B 项目 → 目录里凭空多一棵子树；
- 同一个包接两遍 → 文件被覆盖回旧版；
- 新项目没人铺 `bin/` 与 `收件箱/`，等到要交接才发现没工具；
- 两边脚本版本悄悄分叉，A 机打的包 B 机读不对。

这套东西用"**每个项目自己收发 + 包内 scope/签名/逐文件 sha256 + 自动铺交接**"把这五件事一次性钉死。

## 组成

| 部件 | 位置 | 一句话 |
|---|---|---|
| 规则 | `工作流-双机交接规则.md` | 目录布局、包格式、接手四道关、忽略清单、踩过的教训（版本号在首行） |
| 标准脚本 | `skill/assets/scripts/`（四个母版）；本仓库 `bin/` 只放开发工具 `发布检查.py` | 打包 / 接手 / 铺交接 / 发规则包；只用 Python 标准库，双平台 |
| 安装器 | `skill/install.py` | 一条命令铺 `桌面/公共层/`（规则 + 脚本 + 插件源码 + AGENTS 骨架），默认 dry-run，`--smoke` 当场自测 |
| 发布检查 | `bin/发布检查.py` | 开源前只读门禁：本机路径 / 个人信息 / 载荷缺件 / 规则不一致 |
| 插件 | `skill/assets/plugin/dsh-autohandoff/` | DSH Host 插件：桌面新目录第一次开会话时自动铺 `bin/`、收件箱、发件箱与 AGENTS 两节 |
| 开源载荷 | `skill/` | 装到别的机器就是拷这个目录（`SKILL.md` + `install.py` + `references/` + `assets/`） |

## 30 秒安装（在一台新机器上）

```bash
# 1) 把 skill/ 拷进 DSH 的 skills 目录（目录名就是 skill 名）
cp -R skill ~/.dsh/skills/handoff          # Windows: xcopy /E /I skill %USERPROFILE%\.dsh\skills\handoff

# 2) 一条命令铺好公共层，并当场自测（默认 dry-run，先看再写）
python3 ~/.dsh/skills/handoff/install.py                 # 只看会写什么
python3 ~/.dsh/skills/handoff/install.py --apply --smoke # 真写 + 铺临时项目验证 8 项

# 3) 装插件（python 不能替你在 DSH 里装；装完重启）
#    plugin_manager(action="install_bundle", target="<桌面>/公共层/plugins/dsh-autohandoff")
```

Windows 把 `python3` 换成 `python`、路径换 `%USERPROFILE%\.dsh\skills\handoff`。
安装器只写 `<桌面>/公共层/`，**不碰任何项目目录**；项目迁移与补交接见 `skill/references/迁移检查清单.md`。
装完想确认干净，跑一遍 `python bin/发布检查.py`（0 ERROR 才适合发出去）。

## 日常（两个动作）

```bash
# 离开一台机器前，在**要离开的项目**里
python bin/打包进度.py --list      # 先看会打什么、多大
python bin/打包进度.py --lite      # → 发件箱/<项目名>-进度-YYYYMMDD-HHMM-<机器>.zip

# 到另一台机器，在**对应的项目**里
python bin/接手进度.py 收件箱/<包>.zip --dry-run   # 只校验
python bin/接手进度.py 收件箱/<包>.zip             # 真接手（按母版归一化规则；发件箱默认保留）
```

四道关任何一道不过都不落盘：`scope` 一致 → `.已接手.json` 签名未接过 → 逐文件 sha256 → **路径预检**（越界整包拒收）。

## 自测（改这套东西时至少跑这些）

| 检查 | 命令 / 预期 |
|---|---|
| 新机器铺层 | `python skill/install.py --desktop <临时桌面> --apply --smoke` → 自测 8 项全 PASS |
| 新项目铺交接 | 临时目录跑 `装交接.py <dir> --init-agents` → 出现 `bin/`、收发箱、AGENTS 两节 |
| 包名 | 打包 → `发件箱/<项目名>-进度-YYYYMMDD-HHMM-<tag>.zip` |
| 接手四道关 | 改坏一个字节 → sha256 不符必须中止 |
| 规则归一化 | 包内规则旧、母版新 → 接手后项目根规则 = 母版；`--no-sync-rules` 可关 |
| 发件箱 | **默认保留**（里面可能是还没送出去的包）；加 `--clean-outbox` 才清第一层 zip |
| 双平台语法 | `python -m py_compile` 全部脚本；不出现 `python3` 以外的硬编码解释器名 |
| 幂等 | 对已有交接的项目再跑 `装交接.py` → AGENTS 不重复追加；`install.py` 第二次写 0 个文件 |
| 路径安全 | `python -m unittest discover -s tests -v` → 6 项全 ok（safe_rel 清单、反斜杠条目、目录链接逃逸、整包拒收、发件箱保留/清理、正常收发） |
| 发布门禁 | `python bin/发布检查.py` → 0 ERROR（WARN 逐条判断） |

## 目录

```
dsh-handoff/
├── 工作流-双机交接规则.md     ← 规则源（首行版本号，接手脚本按它比对）
├── bin/发布检查.py            ← 开源前门禁（只读，不参与交接）
├── tests/test_pathsafety.py   ← 路径安全回归（标准库 unittest，6 项）
├── skill/                     ← 开源载荷（安装单元，拷这一个目录就够）
│   ├── SKILL.md
│   ├── install.py             ← 一键铺公共层（dry-run 默认，--apply 真写，--smoke 自测）
│   ├── references/            ← 规则全文、坑与教训、迁移检查清单
│   └── assets/                ← 四个标准脚本 + 插件源码 + 公共层 AGENTS 骨架
├── CHANGELOG.md
└── LICENSE
```

## Roadmap

1. ~~`skill/SKILL.md` 补全安装与排障~~ —— 已完成（含安装器与 8 项自测）。
2. ~~一键安装 `install.py`~~ —— 已完成（`skill/install.py`）。
3. ~~排除名单去硬编码~~ —— 已完成（v3.4：`--exclude` + `cordis.patch.yml` 配置）。
4. 插件：日志轮转；`--scan` 与插件共用一份排除表。
5. README 双语；skill 图标与截图；GitHub Release。

## 许可

**MIT**，© 2026 **TL0121**（全文见 [LICENSE](LICENSE)）。

意思是：可以随便用、改、商用、再分发，只要保留版权声明与许可声明；不提供担保。
规则文档（`工作流-双机交接规则.md`）随仓库同 MIT。
