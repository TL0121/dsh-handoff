/**
 * dsh-autohandoff — 新项目自动铺「双机交接」。
 *
 * 触发点：`agent/created`（任何会话/子代理创建时）。取该会话的工作目录，若它满足
 *   1) 是桌面的一级子目录（= 一个项目根，与 `公共层\` 同级）,
 *   2) 不在排除名单里（公共层 + 配置里的非项目目录）,
 *   3) 还没有 `bin\打包进度.py`,
 * 就调用 `公共层\bin\装交接.py <目录> --append-agents --init-agents`：
 *   bin\打包进度.py、bin\接手进度.py、收件箱\、发件箱\、两个 README，以及 AGENTS.md 的
 *   「交接」+「共用工具」两节（没有 AGENTS.md 时新建骨架）。
 *
 * 为什么用会话创建当触发点：目录是用户/代理随时建的，没有可靠的"新建目录"事件；
 * 而一个目录真正变成"项目"，是第一次在它里面开会话的那一刻 —— 那时铺正要紧。
 *
 * 幂等：已经铺过的目录不会重复动作（一次进程内记住，且 `bin\打包进度.py` 本身就是判据）。
 * 审计：每次动作（含失败）追加到 `公共层\_日志\自动交接.log`。
 */
import { spawn } from 'node:child_process'
import { appendFile, mkdir } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const name = 'dsh-autohandoff'
export const inject = ['workingDirectory']

const HERE = path.dirname(fileURLToPath(import.meta.url))        // 公共层\plugins\dsh-autohandoff
const LAYER = path.resolve(HERE, '..', '..')                    // 公共层
const DESKTOP = path.dirname(LAYER)                             // 桌面
const INSTALLER = path.join(LAYER, 'bin', '装交接.py')
const LOG_FILE = path.join(LAYER, '_日志', '自动交接.log')

// 公共层本身永远不铺；其余非项目目录按机器不同，写进 cordis.patch.yml 的 config.exclude
const HARD_EXCLUDE = new Set(['公共层'])

export function apply(ctx, config = {}) {
  const enabled = config.enabled !== false
  // 解释器候选：配置的优先；Windows 上 `python`，macOS 往往只有 `python3`
  const preferred = process.platform === 'darwin' ? 'python3' : 'python'
  const pythonBins = []
  for (const bin of [config.python, preferred, 'python3', 'python']) {
    if (typeof bin === 'string' && bin.length > 0 && !pythonBins.includes(bin)) pythonBins.push(bin)
  }
  const excludes = new Set([...HARD_EXCLUDE, ...(Array.isArray(config.exclude) ? config.exclude : [])])
  const done = new Set()

  async function log(line) {
    try {
      await mkdir(path.dirname(LOG_FILE), { recursive: true })
      await appendFile(LOG_FILE, `[${new Date().toISOString()}] ${line}\n`, 'utf8')
    } catch {
      /* 日志写不进去不影响主流程 */
    }
  }

  function projectNeedingHandoff(cwd) {
    if (typeof cwd !== 'string' || cwd.length === 0) return null
    const dir = path.resolve(cwd)
    if (path.dirname(dir).toLowerCase() !== DESKTOP.toLowerCase()) return null
    if (excludes.has(path.basename(dir))) return null
    // 显式退出：目录里放一个 .no-handoff 文件，这个目录就永远不被铺交接
    if (existsSync(path.join(dir, '.no-handoff'))) return null
    if (existsSync(path.join(dir, 'bin', '打包进度.py'))) return null
    return dir
  }

  function spawnInstaller(bin, dir, stdio) {
    return new Promise((resolve) => {
      let child
      try {
        child = spawn(bin, [INSTALLER, dir, '--append-agents', '--init-agents'], {
          cwd: LAYER,
          windowsHide: true,
          stdio,
        })
      } catch (error) {
        // 沙箱里带管道 stdio 的 spawn 会同步抛 EPERM
        resolve({ ok: false, out: String(error), spawnError: error })
        return
      }
      let out = ''
      child.stdout?.on('data', (chunk) => { out += chunk })
      child.stderr?.on('data', (chunk) => { out += chunk })
      child.on('error', (error) => resolve({ ok: false, out: String(error), spawnError: error }))
      child.on('close', (code) => resolve({ ok: code === 0, code, out }))
    })
  }

  async function runInstaller(dir) {
    let result = null
    for (const bin of pythonBins) {
      result = await spawnInstaller(bin, dir, ['ignore', 'pipe', 'pipe'])
      if (result.spawnError && result.spawnError.code === 'EPERM') {
        // 沙箱不放行管道：退化成 ignore（拿不到输出，但动作照做）
        result = await spawnInstaller(bin, dir, ['ignore', 'ignore', 'ignore'])
        result.out = `${result.out}\n(沙箱禁管道，未捕获脚本输出；以 bin/打包进度.py 是否出现为准)`.trim()
      }
      // 这个解释器不存在（macOS 没有 python / Windows 只有 python.exe 之类）→ 换下一个
      if (result.spawnError && result.spawnError.code === 'ENOENT') continue
      break
    }
    const landed = existsSync(path.join(dir, 'bin', '打包进度.py'))
    const out = result ? result.out : `找不到可用的 Python（试过：${pythonBins.join(', ')}）`
    return { ok: Boolean(result && result.ok) && landed, out, landed }
  }

  ctx.on('agent/created', async ({ agent }) => {
    if (!enabled) return
    try {
      const cwd = await ctx.workingDirectory.ensure(agent)
      const dir = projectNeedingHandoff(cwd)
      if (dir === null || done.has(dir)) return
      done.add(dir)
      const { ok, out } = await runInstaller(dir)
      await log(`${ok ? 'OK  ' : 'FAIL'} ${dir}\n${out.trim()}`)
      ctx.logger?.info?.(`autohandoff: ${ok ? '已铺交接' : '铺交接失败'} ${dir}`)
    } catch (error) {
      await log(`ERR  ${error instanceof Error ? error.message : String(error)}`)
    }
  })
}
