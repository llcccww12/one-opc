// Source-text regex test — matches the App.test.tsx convention for
// components that reference browser globals and can't be rendered under
// plain Node without a DOM. Usage: `npx tsx opc/plugins/office_ui/frontend_src/auth/LoginScreen.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'LoginScreen.tsx'), 'utf-8')

assert.match(source, /login\(username, inviteCode\)/, 'LoginScreen must call login() in login mode')
assert.match(source, /register\(username, inviteCode\)/, 'LoginScreen must call register() in register mode')
assert.match(source, /storeSession\(/, 'LoginScreen must persist the session token on success')
assert.match(source, /validateCredentials\(/, 'LoginScreen must validate input before submitting')
assert.match(source, /onAuthenticated\(\)/, 'LoginScreen must notify its parent once authenticated')

console.log('LoginScreen.test.tsx passed')
