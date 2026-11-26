# dsh-handoff · 双机交接工具链（源仓库）

> 这份文件只在「以 `dsh-handoff\` 为工作区」的对话里生效。
> 一句话：**这里开发这套东西本身**（规则 + 标准脚本 + 自动铺交接插件），打包成可开源分发的 DSH skill。

## 这是什么

两台机器（macOS ⇄ Windows）之间搬项目进度的一整套机制：

| 部件 | 位置 | 作用 |
|---|---|---|
| 规则 | `工作流-双机交接规则.md` | 什么时候打包、包长什么样、怎么接手、踩过的坑（版本号在首行） |
| 标准脚本 | `skill/assets/scripts/`（四个母版） | 打包 / 接手 / 铺交接 / 发规则包；只用 Python 标准库，双平台 |
| 安装器 | `skill/install.py` | 一条命令铺 `<桌面>/公共层/`，默认 dry-run，`--smoke` 当场自测 8 项 |
| 发布门禁 | `bin/发布检查.py` | 开源前只读检查：本机路径 / 个人信息 / 载荷缺件 / 规则不一致 |
| 插件 | `skill/assets/plugin/dsh-autohandoff/` | 新目录第一次开会话时自动铺交接，零记性 |
| 文档 | `skill/references/` | 规则全文、坑与教训、迁移检查清单 |

## 源与部署

```
本仓库 = 源（规则、脚本、插件、版本号、CHANGELOG、开源载荷）
   │  改完自测 → 同步
   ▼
<桌面>/公共层 = 使用者机器上的部署副本（各项目与插件都从它取）
```

- **只改本仓库**；使用者机器上的 `公共层/` 除「同步」动作之外视为只读。
- 同步方向永远 **本仓库 → 公共层**，反向不成立（防止把部署机上的临时改动当源）。
- 同步范围：规则、`bin/装交接.py`、`bin/打包引导包.py`、`bin/模板/` 两个脚本、`plugins/dsh-autohandoff/`。
- 同步后跑 `python bin/装交接.py <桌面>/<项目>` 把各项目的副本刷成同版本。

## 目录

```
dsh-handoff/
├── README.md  CHANGELOG.md  LICENSE  .gitignore  .gitattributes
├── 工作流-双机交接规则.md          ← 规则源（版本号在首行）
├── bin/发布检查.py                ← 开源前门禁（只读）
├── tests/test_pathsafety.py       ← 路径安全回归（标准库 unittest）
└── skill/                        ← ★ 开源载荷：装到别的机器就拷这个目录
    ├── SKILL.md                  ← DSH skill 入口（frontmatter: name/description）
    ├── install.py                ← 一键铺公共层
    ├── references/               ← 规则全文 / 坑与教训 / 迁移检查清单
    └── assets/
        ├── scripts/              ← 四个标准脚本
        ├── layer/AGENTS.md       ← 公共层 AGENTS 骨架
        └── plugin/dsh-autohandoff/
```

## 开发流程（每次改动都走一遍）

1. 改规则或标准脚本 → 规则首行 `改版 vX.Y` **必须** +0.1，改版行写清改了什么。
   （只改文档 / 安装器 / 发布检查这类不动标准脚本行为的，不升版本号，CHANGELOG 单独记一节。）
2. 自测：`install.py --apply --smoke`（8 项）、`装交接.py --scan`、`打包进度.py --list`、
   `python -m unittest discover -s tests -v`（路径安全 6 项）、`py_compile` 全部脚本。
3. 同步到使用者的 `公共层/`，再归一化各项目。
4. 重打引导包，必要时更新给对端的整包。
5. `CHANGELOG.md` 加一节。
6. 更新 `skill/` 里的副本（规则 / 脚本 / 插件三样都要跟）。
7. 发布前跑 `python bin/发布检查.py`：**0 ERROR** 才算干净；WARN 逐条判断。

## 红线

- **双平台**：脚本只用标准库；不写死绝对路径；`python`（x86）/`python3`（mac）都要能跑；
  字符串里不要出现只有一边存在的命令（`copy` vs `cp` 要分开写或加注释）。
- **向后兼容**：旧包名（`进度-…`）与旧规则版本仍要能接手；`.已接手.json` 的签名语义不能改。
- **规则单一权威**：母版在本仓库，各项目根放同内容副本，接手时按版本号自动归一化。
- **编码**：脚本输出在非终端时必须是 UTF-8；文本文件一律 UTF-8 无 BOM。
- **可公开**：代码与文档里不出现本机路径、用户名、机器名、其它项目的名字
  （本机专有名字写进 `.releaseignore`，该文件不进仓库）。
- **插件边界**：只监听 `agent/created`、只写桌面一级目录、认 `.no-handoff` 退出、失败不打断会话。

## 自测

```cmd
python skill\install.py --desktop <临时桌面> --apply --smoke
python <临时桌面>\公共层\bin\装交接.py --scan --desktop <临时桌面>
python -m unittest discover -s tests -v      :: 路径安全回归（6 项）
python bin\发布检查.py
```
