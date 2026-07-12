// Source-text regex test — matches LoginScreen.test.tsx's convention for
// components that touch browser globals and can't be rendered under plain
// Node without a DOM.
// Usage: `npx tsx opc/plugins/office_ui/frontend_src/auth/SettingsPanel.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'SettingsPanel.tsx'), 'utf-8')

assert.match(source, /if \(!open\) return null/, 'SettingsPanel must not render when closed')
assert.match(source, /onRequestLlmConfig\(\)/, 'SettingsPanel must request current config on open')
assert.match(source, /onSaveLlmConfig\(/, 'SettingsPanel must call onSaveLlmConfig on save')
assert.match(source, /settings-backdrop/, 'SettingsPanel must use a lighter backdrop (not the heavy org-create one)')
assert.match(source, /settings-modal/, 'SettingsPanel must use its own modal panel class')
assert.match(source, /type="password"/, 'API key field must be a password input')
assert.doesNotMatch(source, /VisualSocketClient/, 'SettingsPanel must stay presentational — no direct wsClient dependency')

console.log('SettingsPanel.test.tsx passed')
