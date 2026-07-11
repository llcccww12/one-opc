// Source-text regex test, same convention as LoginScreen.test.tsx.
// Usage: `npx tsx opc/plugins/office_ui/frontend_src/auth/IdentityMenu.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'IdentityMenu.tsx'), 'utf-8')

assert.match(source, /getStoredUsername\(\)/, 'IdentityMenu must read the stored username')
assert.match(source, /if \(!username\) return null/, 'IdentityMenu must render nothing in anonymous mode')
assert.match(source, /clearSession\(\)/, 'IdentityMenu must clear the session on logout')
assert.match(source, /window\.location\.reload\(\)/, 'IdentityMenu must reload the page after logout')
assert.match(source, /<SettingsPanel/, 'IdentityMenu must mount SettingsPanel')
assert.doesNotMatch(source, /VisualSocketClient/, 'IdentityMenu must stay presentational — no direct wsClient dependency')

console.log('IdentityMenu.test.tsx passed')
