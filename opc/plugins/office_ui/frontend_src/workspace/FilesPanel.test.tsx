// Source-text regex test — matches the LoginScreen.test.tsx convention for
// components that touch browser globals and can't be rendered under plain
// Node without a DOM. Usage: `npx tsx opc/plugins/office_ui/frontend_src/workspace/FilesPanel.test.tsx`
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(join(__dirname, 'FilesPanel.tsx'), 'utf-8')

assert.match(source, /onNavigate\(/, 'FilesPanel must call onNavigate to change directory')
assert.match(source, /onDelete\(/, 'FilesPanel must call onDelete to remove an entry')
assert.match(source, /downloadUrlFor\(/, 'FilesPanel must build a download URL per entry, not hardcode one')
assert.doesNotMatch(source, /VisualSocketClient/, 'FilesPanel must stay presentational — no direct wsClient dependency')

console.log('FilesPanel.test.tsx passed')
