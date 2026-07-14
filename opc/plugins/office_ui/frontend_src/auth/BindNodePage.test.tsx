// Source-text regex test — matches the LoginScreen.test.tsx convention for
// components that reference browser globals and can't be rendered under
// plain Node without a DOM. Usage: `npx tsx opc/plugins/office_ui/frontend_src/auth/BindNodePage.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'BindNodePage.tsx'), 'utf-8')

assert.match(source, /bindVm\(token\)/, 'BindNodePage must call bindVm() to trigger launch/start')
assert.match(source, /getVmStatus\(token\)/, 'BindNodePage must poll getVmStatus() for progress')
assert.match(source, /onReady\(\)/, 'BindNodePage must notify its parent once the VM is ready')
assert.match(source, /setInterval\(refresh, POLL_INTERVAL_MS\)/, 'BindNodePage must poll while launching')
assert.match(source, /clearInterval\(/, 'BindNodePage must stop polling once resolved')

const refreshBody = source.slice(source.indexOf('const refresh ='), source.indexOf('useEffect('))
assert.match(
  refreshBody,
  /if \(result\.status === 'launching'[^)]*\)\s*{\s*startPolling\(\)/,
  'refresh() must resume polling if it observes status still launching (e.g. after a page reload mid-launch)',
)

console.log('BindNodePage.test.tsx passed')
