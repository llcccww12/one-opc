// Source-text regex test — matches the App.test.tsx convention for modules
// that wrap a live WebSocket and can't be exercised without a real socket.
// Usage: `npx tsx opc/plugins/office_ui/frontend_src/lib/wsClient.test.ts`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'wsClient.ts'), 'utf-8')

assert.match(source, /getLlmConfig\(\): void \{\s*this\.send\(\{ type: 'get_llm_config' \}\)/, 'getLlmConfig must send a get_llm_config message')
assert.match(source, /updateLlmConfig\(patch:/, 'updateLlmConfig must accept a patch object')
assert.match(source, /type: 'update_llm_config', patch/, 'updateLlmConfig must send patch in the payload')
assert.match(source, /onGetLlmConfig\?:/, 'SocketHandlers must declare onGetLlmConfig')
assert.match(source, /onUpdateLlmConfig\?:/, 'SocketHandlers must declare onUpdateLlmConfig')
assert.match(source, /case 'get_llm_config':\s*this\.handlers\.onGetLlmConfig\?\.\(parsed\.payload/, 'handleMessage must dispatch get_llm_config to onGetLlmConfig')
assert.match(source, /case 'update_llm_config':\s*this\.handlers\.onUpdateLlmConfig\?\.\(parsed\.payload/, 'handleMessage must dispatch update_llm_config to onUpdateLlmConfig')

// Verify VM credential code has been removed (local-only product).
assert.doesNotMatch(source, /getVmCredentials/, 'wsClient must not have getVmCredentials (cloud VM code removed)')
assert.doesNotMatch(source, /updateVmCredentials/, 'wsClient must not have updateVmCredentials (cloud VM code removed)')
assert.doesNotMatch(source, /onGetVmCredentials/, 'wsClient must not have onGetVmCredentials (cloud VM code removed)')
assert.doesNotMatch(source, /onUpdateVmCredentials/, 'wsClient must not have onUpdateVmCredentials (cloud VM code removed)')
assert.doesNotMatch(source, /vm_status_changed/, 'wsClient must not handle vm_status_changed (cloud VM code removed)')

console.log('wsClient.test.ts passed')
