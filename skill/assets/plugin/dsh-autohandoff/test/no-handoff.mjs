// dsh-autohandoff 的 .no-handoff 退出机制测试（mock cordis ctx）
//   node no-handoff.mjs <带 .no-handoff 的目录>
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const dir = process.argv[2]
if (!dir) { console.error('用法: node no-handoff.mjs <目录>'); process.exit(2) }
mkdirSync(dir, { recursive: true })
writeFileSync(path.join(dir, '.no-handoff'), '')

const HERE = path.dirname(fileURLToPath(import.meta.url))
const mod = await import(pathToFileURL(path.join(HERE, '..', 'index.js')).href)

const listeners = new Map()
const infos = []
mod.apply({
  on: (e, fn) => listeners.set(e, fn),
  logger: { info: (m) => infos.push(m) },
  workingDirectory: { ensure: async () => dir },
}, { enabled: true, python: 'python' })

await listeners.get('agent/created')({ agent: {} })

const leaked = ['bin/打包进度.py', 'AGENTS.md', '收件箱', '发件箱']
  .filter((rel) => existsSync(path.join(dir, rel)))
console.log('logger:', infos.length ? infos.join(' | ') : '(无动作)')
console.log('泄漏文件:', leaked.length ? leaked.join(', ') : '无')
const pass = leaked.length === 0 && infos.length === 0
console.log(pass ? 'RESULT: PASS（.no-handoff 生效）' : 'RESULT: FAIL')
process.exit(pass ? 0 : 1)
