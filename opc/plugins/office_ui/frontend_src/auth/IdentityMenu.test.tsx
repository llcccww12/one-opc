// Source-text regex test.
// Usage: `npx tsx opc/plugins/office_ui/frontend_src/auth/IdentityMenu.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'IdentityMenu.tsx'), 'utf-8')

assert.doesNotMatch(source, /getStoredUsername/, 'IdentityMenu must not reference getStoredUsername (auth removed)')
assert.doesNotMatch(source, /clearSession/, 'IdentityMenu must not reference clearSession (auth removed)')
assert.doesNotMatch(source, /退出登录/, 'IdentityMenu must not show logout button (auth removed)')
assert.match(source, /<SettingsPanel/, 'IdentityMenu must mount SettingsPanel')
assert.match(source, /模型 \/ API Key 设置/, 'IdentityMenu must show settings trigger')
assert.doesNotMatch(source, /VisualSocketClient/, 'IdentityMenu must stay presentational — no direct wsClient dependency')

console.log('IdentityMenu.test.tsx passed')
