// Source-text regex test, same convention as LoginScreen.test.tsx.
// Usage: `npx tsx opc/plugins/office_ui/frontend_src/nodes/NodesPanel.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'NodesPanel.tsx'), 'utf-8')

assert.match(source, /onRefresh\(\)/, 'NodesPanel must call onRefresh to reload')
assert.match(source, /未检测到本机 SkyPilot|not detected/i, 'NodesPanel must render an unavailable message')
assert.doesNotMatch(source, /sky (start|stop|launch)/, 'NodesPanel must stay read-only — no start/stop/launch actions')
assert.doesNotMatch(source, /VisualSocketClient/, 'NodesPanel must stay presentational — no direct wsClient dependency')

console.log('NodesPanel.test.tsx passed')
