// Source-text regex test — matches the LoginScreen.test.tsx convention.
// Usage: `npx tsx opc/plugins/office_ui/frontend_src/auth/Root.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'Root.tsx'), 'utf-8')

assert.doesNotMatch(source, /LoginScreen/, 'Root must not reference LoginScreen (auth removed)')
assert.doesNotMatch(source, /getStoredToken/, 'Root must not reference getStoredToken (auth removed)')
assert.match(source, /<App\s*\/>/, 'Root must render App directly')

console.log('Root.test.tsx passed')
