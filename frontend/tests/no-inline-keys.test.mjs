/** 护栏：前端源码里不许出现硬编码凭据（2026-08-25 开源审计）。
 *
 * 为什么需要测试钉住：把 key 写回源码**不会让任何功能坏掉**——地图照常渲染、构建照常
 * 通过、lint 也不管。唯一的后果是仓库里多了一个真值，而这在开源仓库里是不可逆的
 * （删掉文件也删不掉 git 历史）。没有征兆的问题必须靠护栏，不能靠记性。
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const srcDir = fileURLToPath(new URL('../src', import.meta.url))

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) out.push(...walk(path))
    else if (/\.(ts|tsx|js|jsx)$/.test(name)) out.push(path)
  }
  return out
}

const files = walk(srcDir).map((path) => [path.slice(srcDir.length + 1), readFileSync(path, 'utf8')])

test('前端源码不含 32 位 hex 字面量（高德 key / 安全密钥的形状）', () => {
  // 高德的 key 与安全密钥都是 32 位小写 hex。这条规则宽于「已知泄露值」——
  // 换了新 key 再硬编码一次同样会被抓住，否则护栏只防上一次的错。
  const hits = []
  for (const [name, text] of files) {
    for (const line of text.split('\n')) {
      const m = line.match(/['"`][0-9a-f]{32}['"`]/)
      if (m) hits.push(`${name}: ${m[0]}`)
    }
  }
  assert.deepEqual(hits, [], `疑似硬编码凭据，请改走环境变量（见 frontend/.env.example）：\n${hits.join('\n')}`)
})

test('曾经泄露过的两个高德值不得回到源码', () => {
  // 这两个值进过 git 历史（TripMap.tsx，2026-08-25 前），必须在控制台重置。
  // 即便重置了也不该再出现在源码里——留着这条断言是为了防「回滚时顺手带回来」。
  const leaked = ['ed9a6608256ee71b70b4f5a157460193', '746aca39a18383debae857c907f418c4']
  for (const [name, text] of files) {
    for (const value of leaked) {
      assert.ok(!text.includes(value), `${name} 出现了已泄露的高德凭据 ${value.slice(0, 8)}…`)
    }
  }
})

test('TripMap 的凭据全部来自构建期环境变量', () => {
  const tripMap = files.find(([name]) => name.endsWith('TripMap.tsx'))
  assert.ok(tripMap, '找不到 TripMap.tsx')
  const [, text] = tripMap
  assert.match(text, /import\.meta\.env\.VITE_AMAP_JS_KEY/, 'key 必须来自 VITE_AMAP_JS_KEY')
  assert.match(text, /import\.meta\.env\.VITE_AMAP_JS_SECURITY_CODE/, '安全密钥必须来自环境变量')
})

test('安全密钥只在 dev 分支使用，生产走 nginx 代理', () => {
  // 生产一旦内联安全密钥，它就随 bundle 发给每个访客——这正是要避免的事。
  // 判据是「读取安全密钥的那行必须在 import.meta.env.DEV 块里」。
  const [, text] = files.find(([name]) => name.endsWith('TripMap.tsx'))
  const devIdx = text.indexOf('import.meta.env.DEV')
  const codeIdx = text.indexOf('VITE_AMAP_JS_SECURITY_CODE')
  const elseIdx = text.indexOf('} else {', devIdx)
  assert.ok(devIdx !== -1 && codeIdx > devIdx && codeIdx < elseIdx,
    '安全密钥的读取必须落在 import.meta.env.DEV 分支内')
  assert.match(text, /serviceHost: `\$\{window\.location\.origin\}\/_AMapService`/,
    '生产必须走 _AMapService 代理')
})

test('缺 key 时不静默白屏：走 onFail 并留下排查线索', () => {
  const [, text] = files.find(([name]) => name.endsWith('TripMap.tsx'))
  assert.match(text, /if \(!AMAP_JS_KEY\)/, '必须显式判空')
  assert.match(text, /console\.error\([\s\S]{0,200}VITE_AMAP_JS_KEY/,
    '判空分支要在控制台说明缺了哪个变量——否则和「高德挂了」现象一样，没法排查')
})

test('.env.example 存在且不含真值', () => {
  const example = readFileSync(fileURLToPath(new URL('../.env.example', import.meta.url)), 'utf8')
  assert.match(example, /^VITE_AMAP_JS_KEY=\s*$/m, '模板里的值必须留空')
  assert.match(example, /^VITE_AMAP_JS_SECURITY_CODE=\s*$/m, '模板里的值必须留空')
  assert.ok(!/[0-9a-f]{32}/.test(example), '.env.example 不得含任何 32 位 hex 真值')
})
