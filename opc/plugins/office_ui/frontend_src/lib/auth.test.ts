// Runs with `tsx` against node:assert/strict — matches repo convention for
// zero-framework tests. Usage: `npx tsx opc/plugins/office_ui/frontend_src/lib/auth.test.ts`
import assert from 'node:assert/strict'
import { validateCredentials, register, login } from './auth'

assert.equal(validateCredentials('', 'code'), '请输入用户名')
assert.equal(validateCredentials('alice', ''), '请输入邀请码')
assert.equal(validateCredentials('alice', 'code'), null)

async function run(): Promise<void> {
  let capturedUrl = ''
  let capturedBody = ''
  ;(globalThis as any).fetch = async (url: string, init: RequestInit) => {
    capturedUrl = url
    capturedBody = init.body as string
    return {
      ok: true,
      json: async () => ({ ok: true, token: 'tok123', user_id: 'user-123' }),
    }
  }
  const result = await register('alice', 'invite1')
  assert.equal(capturedUrl, '/api/register')
  assert.deepEqual(JSON.parse(capturedBody), { username: 'alice', invite_code: 'invite1' })
  assert.equal(result.ok, true)
  assert.equal(result.token, 'tok123')
  assert.equal(result.userId, 'user-123')

  ;(globalThis as any).fetch = async () => ({
    ok: false,
    json: async () => ({ ok: false, error: 'bad code' }),
  })
  const failed = await login('alice', 'wrong')
  assert.equal(failed.ok, false)
  assert.equal(failed.error, 'bad code')

  console.log('auth.test.ts passed')
}

run()
