/**
 * ModernPreview - 摩登极简风布局预览
 */
import { motion } from 'framer-motion'
import { Logo, NavTabs, AnimatedSessionList, KanbanCard, FloatingComposer, AnimatedHeading, StatCard } from './ModernLayout'

const mockSessions = [
  { id: '1', title: 'New Chat', status: 'running', time: '5m' },
  { id: '2', title: 'Project Planning', status: 'pending', time: '1h' },
  { id: '3', title: 'Code Review', status: 'done', time: '2h' },
]

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.1 },
  },
}

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0 },
}

export default function ModernPreview() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100">
      {/* ── 顶部导航 ──────────────────────────────────── */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-gray-100">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <Logo />
          <NavTabs active="Workspace" onChange={() => {}} />
          <div className="flex items-center gap-4">
            <motion.button
              className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              Settings
            </motion.button>
            <motion.div
              className="w-9 h-9 rounded-full bg-gradient-to-r from-indigo-500 to-purple-500 flex items-center justify-center text-white font-medium"
              whileHover={{ scale: 1.1 }}
            >
              U
            </motion.div>
          </div>
        </div>
      </header>

      {/* ── 主内容区 ──────────────────────────────────── */}
      <main className="max-w-7xl mx-auto px-6 py-8">
        {/* 标题区域 */}
        <motion.div
          className="mb-8"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <AnimatedHeading text="Welcome back to OpenOPC" />
          <p className="mt-3 text-gray-500">Manage your AI agents and collaborate seamlessly.</p>
        </motion.div>

        {/* 统计卡片 */}
        <motion.div
          className="grid grid-cols-4 gap-4 mb-8"
          variants={container}
          initial="hidden"
          animate="show"
        >
          <motion.div variants={item}>
            <StatCard label="Active Agents" value={3} />
          </motion.div>
          <motion.div variants={item}>
            <StatCard label="Running Tasks" value={7} />
          </motion.div>
          <motion.div variants={item}>
            <StatCard label="Completed" value={42} />
          </motion.div>
          <motion.div variants={item}>
            <StatCard label="Skills" value={12} />
          </motion.div>
        </motion.div>

        {/* 两栏布局：会话列表 + 看板 */}
        <div className="grid grid-cols-12 gap-6">
          {/* 会话列表 */}
          <motion.div
            className="col-span-4"
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
          >
            <div className="bg-white rounded-2xl border border-gray-100 p-4">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-gray-900">Recent Sessions</h3>
                <motion.button
                  className="text-sm text-indigo-500 hover:text-indigo-600 font-medium"
                  whileHover={{ x: 4 }}
                >
                  View all →
                </motion.button>
              </div>
              <AnimatedSessionList
                sessions={mockSessions}
                activeId="1"
                onSelect={() => {}}
              />
            </div>
          </motion.div>

          {/* 看板 */}
          <motion.div
            className="col-span-8"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
          >
            <div className="grid grid-cols-3 gap-4">
              {/* TODO */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <span className="w-2 h-2 rounded-full bg-gray-300" />
                  <span className="text-sm font-medium text-gray-600">TODO</span>
                  <span className="text-xs text-gray-400 ml-auto">1</span>
                </div>
                <div className="space-y-3">
                  <KanbanCard id="OPC-1" title="New Chat" status="todo" />
                </div>
              </div>

              {/* IN PROGRESS */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <span className="w-2 h-2 rounded-full bg-yellow-500" />
                  <span className="text-sm font-medium text-gray-600">IN PROGRESS</span>
                  <span className="text-xs text-gray-400 ml-auto">0</span>
                </div>
                <div className="space-y-3">
                  <div className="h-24 rounded-xl border-2 border-dashed border-gray-200 flex items-center justify-center text-gray-400 text-sm">
                    Drop task here
                  </div>
                </div>
              </div>

              {/* DONE */}
              <div>
                <div className="flex items-center gap-2 mb-4">
                  <span className="w-2 h-2 rounded-full bg-green-500" />
                  <span className="text-sm font-medium text-gray-600">DONE</span>
                  <span className="text-xs text-gray-400 ml-auto">0</span>
                </div>
                <div className="space-y-3">
                  <div className="h-24 rounded-xl border-2 border-dashed border-gray-200 flex items-center justify-center text-gray-400 text-sm">
                    No completed tasks
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </main>

      {/* ── 底部悬浮输入框 ────────────────────────────── */}
      <FloatingComposer />
    </div>
  )
}
