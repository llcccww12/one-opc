/**
 * ModernLayout - 摩登极简风布局原型
 * 加入 react-bits 动画组件和独特排版
 */
import { motion } from 'framer-motion'
import BlurText from '../BlurText'

// ── 顶部 Logo 组件 ─────────────────────────────────────
export function Logo() {
  return (
    <div className="flex items-center gap-3">
      <motion.div
        className="text-2xl font-extrabold tracking-tight"
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.6, ease: 'easeOut' }}
      >
        <span className="bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 bg-clip-text text-transparent">
          Open
        </span>
        <span className="text-gray-900">OPC</span>
      </motion.div>
      <motion.div
        className="w-2.5 h-2.5 rounded-full bg-green-500"
        animate={{
          boxShadow: [
            '0 0 0 0 rgba(16, 185, 129, 0.4)',
            '0 0 0 8px rgba(16, 185, 129, 0)',
            '0 0 0 0 rgba(16, 185, 129, 0)',
          ],
        }}
        transition={{ duration: 2, repeat: Infinity }}
      />
    </div>
  )
}

// ── 导航标签组件 ───────────────────────────────────────
export function NavTabs({
  active,
  onChange,
}: {
  active: string
  onChange: (tab: string) => void
}) {
  const tabs = ['Workspace', 'Office', 'Org']

  return (
    <div className="flex items-center gap-1 p-1 bg-gray-100/80 rounded-xl">
      {tabs.map((tab) => (
        <motion.button
          key={tab}
          className={`
            relative px-6 py-2.5 text-sm font-medium rounded-lg transition-colors
            ${active === tab ? 'text-gray-900' : 'text-gray-500 hover:text-gray-700'}
          `}
          onClick={() => onChange(tab)}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
        >
          {active === tab && (
            <motion.div
              className="absolute inset-0 bg-white rounded-lg shadow-sm"
              layoutId="activeTab"
              transition={{ type: 'spring', bounce: 0.2, duration: 0.6 }}
            />
          )}
          <span className="relative z-10">{tab}</span>
        </motion.button>
      ))}
    </div>
  )
}

// ── 会话列表组件（带动画） ─────────────────────────────
export function AnimatedSessionList({
  sessions,
  activeId,
  onSelect,
}: {
  sessions: Array<{ id: string; title: string; status: string; time: string }>
  activeId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <div className="space-y-2">
      {sessions.map((session, index) => (
        <motion.div
          key={session.id}
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: index * 0.1, duration: 0.3 }}
        >
          <motion.button
            className={`
              w-full p-4 rounded-xl text-left transition-all
              ${activeId === session.id
                ? 'bg-indigo-50 border-2 border-indigo-200'
                : 'bg-white border border-gray-100 hover:border-gray-200'
              }
            `}
            onClick={() => onSelect(session.id)}
            whileHover={{ y: -2, boxShadow: '0 8px 24px rgba(0, 0, 0, 0.08)' }}
            whileTap={{ scale: 0.98 }}
          >
            <div className="flex items-center justify-between">
              <span className="font-medium text-gray-900">{session.title}</span>
              <span className="text-xs text-gray-400">{session.time}</span>
            </div>
            <div className="mt-2 flex items-center gap-2">
              <span className={`
                w-2 h-2 rounded-full
                ${session.status === 'running' ? 'bg-blue-500' : ''}
                ${session.status === 'pending' ? 'bg-yellow-500' : ''}
                ${session.status === 'done' ? 'bg-green-500' : ''}
              `} />
              <span className="text-xs text-gray-500">{session.status}</span>
            </div>
          </motion.button>
        </motion.div>
      ))}
    </div>
  )
}

// ── 看板卡片组件 ───────────────────────────────────────
export function KanbanCard({
  title,
  id,
  status,
}: {
  title: string
  id: string
  status: string
}) {
  return (
    <motion.div
      className="p-4 bg-white rounded-xl border border-gray-100 cursor-pointer"
      whileHover={{
        y: -4,
        boxShadow: '0 12px 40px rgba(0, 0, 0, 0.1)',
        borderColor: 'rgba(99, 102, 241, 0.3)',
      }}
      transition={{ duration: 0.2 }}
    >
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-mono text-gray-400">{id}</span>
        <motion.button
          className="w-6 h-6 flex items-center justify-center rounded-md text-gray-400 hover:text-indigo-500 hover:bg-indigo-50"
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.9 }}
        >
          ▶
        </motion.button>
      </div>
      <h4 className="font-medium text-gray-900 mb-2">{title}</h4>
      <div className="flex items-center gap-2">
        <span className={`
          w-2 h-2 rounded-full
          ${status === 'todo' ? 'bg-gray-300' : ''}
          ${status === 'progress' ? 'bg-yellow-500' : ''}
          ${status === 'done' ? 'bg-green-500' : ''}
        `} />
        <span className="text-xs text-gray-500 capitalize">{status}</span>
      </div>
    </motion.div>
  )
}

// ── 聊天输入框组件（底部悬浮） ─────────────────────────
export function FloatingComposer() {
  return (
    <motion.div
      className="fixed bottom-6 left-1/2 -translate-x-1/2 w-full max-w-2xl px-4"
      initial={{ y: 100, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ delay: 0.5, duration: 0.5, ease: 'easeOut' }}
    >
      <div className="bg-white rounded-2xl shadow-lg border border-gray-100 p-4">
        <div className="flex items-end gap-3">
          <div className="flex-1 min-h-[40px] max-h-[120px] overflow-auto">
            <div
              className="text-gray-900 outline-none min-h-[40px] flex items-center"
              contentEditable
              data-placeholder="Message..."
            />
          </div>
          <motion.button
            className="w-10 h-10 rounded-xl bg-gradient-to-r from-indigo-500 to-purple-500 text-white flex items-center justify-center flex-shrink-0"
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
            </svg>
          </motion.button>
        </div>
        <div className="mt-3 flex items-center gap-4 text-xs text-gray-400">
          <span className="flex items-center gap-1">
            <span className="font-medium text-indigo-500">MODE</span>
            Task
          </span>
          <span className="flex items-center gap-1">
            <span className="font-medium text-indigo-500">AGENT</span>
            OpenOPC Native
          </span>
        </div>
      </div>
    </motion.div>
  )
}

// ── 标题动画组件 ───────────────────────────────────────
export function AnimatedHeading({
  text,
  className = '',
}: {
  text: string
  className?: string
}) {
  return (
    <BlurText
      text={text}
      animateBy="words"
      direction="top"
      className={`text-3xl font-bold text-gray-900 ${className}`}
      delay={100}
    />
  )
}

// ── 统计卡片组件 ───────────────────────────────────────
export function StatCard({
  label,
  value,
  icon,
}: {
  label: string
  value: number | string
  icon?: React.ReactNode
}) {
  return (
    <motion.div
      className="p-4 bg-white rounded-xl border border-gray-100"
      whileHover={{ y: -2, boxShadow: '0 8px 24px rgba(0, 0, 0, 0.06)' }}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-gray-500 mb-1">{label}</p>
          <p className="text-2xl font-bold text-gray-900">{value}</p>
        </div>
        {icon && (
          <div className="w-10 h-10 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-500">
            {icon}
          </div>
        )}
      </div>
    </motion.div>
  )
}
