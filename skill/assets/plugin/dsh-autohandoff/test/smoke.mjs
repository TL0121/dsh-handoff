// dsh-autohandoff 冒烟测试：mock 一个 cordis ctx，验证「新项目目录 → 自动铺交接」。
//
//   node 公共层\plugins\dsh-autohandoff\test\smoke.mjs <临时项目目录>
//
// 会在该目录里铺 bin\ / 收件箱\ / 发件箱\ / AGENTS.md，并检查幂等（第二次触发不再动作）。
// 沙箱里 `spawn` 带管道会抛 EPERM，插件会自动退化成 stdio:'ignore'，这正是要覆盖的路径。
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const testDir = process.argv[2]
if (!testDir) {
  console.error('用法: node smoke.mjs <测试项目目录>')
  process.exit(2)
}

const HERE = path.dirname(fileURLToPath(import.meta.url))       // …/plugins/dsh-autohandoff/test
const LAYER = path.resolve(HERE, '..', '..', '..')              // 公共层
const DESKTOP = path.dirname(LAYER)                             // 桌面
const INSTALLER = path.join(LAYER, 'bin', '装交接.py')

// 插件只给「桌面的一级子目录」铺交接；测试目录放错位置会静默 0 动作，这里直接说清
if (path.dirname(path.resolve(testDir)) !== DESKTOP) {
  console.error(`测试目录必须是 ${DESKTOP} 的一级子目录（插件只铺桌面一级目录）。`)
  console.error(`当前：${path.resolve(testDir)}`)
  process.exit(2)
}
if (!existsSync(INSTALLER)) {
  console.error(`找不到铺交接脚本：${INSTALLER}`)
  console.error('本自测要在 公共层\\plugins\\dsh-autohandoff\\test\\ 里跑；源码仓库里的副本不认识桌面。')
  process.exit(2)
}

const mod = await import(pathToFileURL(path.join(HERE, '..', 'index.js')).href)

const listeners = new Map()
const infos = []
const ctx = {
  on(event, fn) { listeners.set(event, fn) },
  logger: { info: (m) => infos.push(m), warn: (m) => infos.push('WARN ' + m) },
  workingDirectory: { ensure: async () => testDir },
}

mod.apply(ctx, { enabled: true, python: 'python' })
console.log('listeners:', [...listeners.keys()].join(','))

const fired = listeners.get('agent/created')
if (typeof fired !== 'function') {
  console.error('FAIL: 没有注册 agent/created')
  process.exit(1)
}

await fired({ agent: { fake: true } })

let bad = 0
for (const rel of ['bin/打包进度.py', 'bin/接手进度.py', '收件箱/README.md', '发件箱/README.md', 'AGENTS.md']) {
  const ok = existsSync(path.join(testDir, rel))
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${rel}`)
  if (!ok) bad++
}

const agents = existsSync(path.join(testDir, 'AGENTS.md'))
  ? readFileSync(path.join(testDir, 'AGENTS.md'), 'utf8')
  : ''
for (const section of ['## 交接', '## 共用工具']) {
  const ok = agents.includes(section)
  console.log(`${ok ? 'PASS' : 'FAIL'}  AGENTS.md 含 ${section}`)
  if (!ok) bad++
}

const before = infos.length
await fired({ agent: { fake: true } })
const idle = infos.length === before
console.log(`${idle ? 'PASS' : 'FAIL'}  第二次触发不再动作（幂等）`)
if (!idle) bad++

console.log('--- logger ---')
console.log(infos.join('\n') || '(空)')
console.log(bad === 0 ? 'RESULT: ALL PASS' : `RESULT: ${bad} FAIL`)
process.exit(bad === 0 ? 0 : 1)
