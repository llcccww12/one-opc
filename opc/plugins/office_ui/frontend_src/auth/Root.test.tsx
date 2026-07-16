// Source-text regex test — matches the LoginScreen.test.tsx convention.
// Usage: `npx tsx opc/plugins/office_ui/frontend_src/auth/Root.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'Root.tsx'), 'utf-8')

assert.match(source, /<LoginScreen/, 'Root must render LoginScreen when unauthenticated')
assert.doesNotMatch(source, /BindNodePage/, 'Root must not reference BindNodePage (cloud VM code removed)')
assert.doesNotMatch(source, /getVmStatus/, 'Root must not reference getVmStatus (cloud VM code removed)')
assert.match(source, /<App\s*\/>/, 'Root must render App when authenticated')

console.log('Root.test.tsx passed')
