// Runs with `tsx` against node:assert/strict — matches repo convention for
// zero-framework tests. Usage: `npx tsx opc/plugins/office_ui/frontend_src/lib/vm.test.ts`
import assert from 'node:assert/strict'
import { getVmStatus, bindVm } from './vm'

async function run(): Promise<void> {
  let capturedUrl = ''
  let capturedMethod = ''
  let capturedAuth = ''
  ;(globalThis as any).fetch = async (url: string, init: RequestInit) => {
    capturedUrl = url
    capturedMethod = init.method as string
    capturedAuth = (init.headers as Record<string, string>).Authorization
    return {
      ok: true,
      json: async () => ({ ok: true, status: 'launching', cluster_name: 'opc-tenant-abc', error_message: null }),
    }
  }

  const bound = await bindVm('tok123')
  assert.equal(capturedUrl, '/api/vm/bind')
  assert.equal(capturedMethod, 'POST')
  assert.equal(capturedAuth, 'Bearer tok123')
  assert.equal(bound.status, 'launching')
  assert.equal(bound.cluster_name, 'opc-tenant-abc')

  ;(globalThis as any).fetch = async (url: string, init: RequestInit) => {
    capturedUrl = url
    capturedMethod = init.method as string
    return {
      ok: true,
      json: async () => ({ ok: true, status: 'ready', cluster_name: 'opc-tenant-abc', error_message: null }),
    }
  }
  const status = await getVmStatus('tok123')
  assert.equal(capturedUrl, '/api/vm/status')
  assert.equal(capturedMethod, 'GET')
  assert.equal(status.status, 'ready')

  ;(globalThis as any).fetch = async () => ({
    ok: false,
    json: async () => ({ ok: false, error: 'unauthorized' }),
  })
  const failed = await getVmStatus('bad-token')
  assert.equal(failed.status, 'error')
  assert.equal(failed.error_message, 'unauthorized')

  console.log('vm.test.ts passed')
}

run()
