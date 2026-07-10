/**
 * Animated Components - 使用 framer-motion 的动画组件
 */
import { motion, AnimatePresence } from 'framer-motion'
import { type ReactNode } from 'react'

// ── 渐入动画 ─────────────────────────────────────────
export function FadeIn({
  children,
  delay = 0,
  duration = 0.3,
  className = '',
}: {
  children: ReactNode
  delay?: number
  duration?: number
  className?: string
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration, ease: 'easeOut' }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

// ── 滑入动画 ─────────────────────────────────────────
export function SlideIn({
  children,
  direction = 'left',
  delay = 0,
  className = '',
}: {
  children: ReactNode
  direction?: 'left' | 'right' | 'up' | 'down'
  delay?: number
  className?: string
}) {
  const variants = {
    left: { initial: { x: -20, opacity: 0 }, animate: { x: 0, opacity: 1 } },
    right: { initial: { x: 20, opacity: 0 }, animate: { x: 0, opacity: 1 } },
    up: { initial: { y: -20, opacity: 0 }, animate: { y: 0, opacity: 1 } },
    down: { initial: { y: 20, opacity: 0 }, animate: { y: 0, opacity: 1 } },
  }

  const { initial, animate } = variants[direction]

  return (
    <motion.div
      initial={initial}
      animate={animate}
      transition={{ delay, duration: 0.4, ease: 'easeOut' }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

// ── 缩放动画 ─────────────────────────────────────────
export function ScaleIn({
  children,
  delay = 0,
  className = '',
}: {
  children: ReactNode
  delay?: number
  className?: string
}) {
  return (
    <motion.div
      initial={{ scale: 0.9, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ delay, duration: 0.3, ease: 'easeOut' }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

// ── 列表项动画 ───────────────────────────────────────
export function AnimatedListItem({
  children,
  index = 0,
  className = '',
}: {
  children: ReactNode
  index?: number
  className?: string
}) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{
        delay: index * 0.05,
        duration: 0.3,
        ease: 'easeOut',
      }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

// ── 悬停效果 ─────────────────────────────────────────
export function HoverScale({
  children,
  scale = 1.02,
  className = '',
}: {
  children: ReactNode
  scale?: number
  className?: string
}) {
  return (
    <motion.div
      whileHover={{ scale }}
      whileTap={{ scale: 0.98 }}
      transition={{ duration: 0.2 }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

// ── 呼吸灯效果 ───────────────────────────────────────
export function Pulse({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <motion.div
      animate={{
        boxShadow: [
          '0 0 0 0 rgba(99, 102, 241, 0)',
          '0 0 0 8px rgba(99, 102, 241, 0.1)',
          '0 0 0 0 rgba(99, 102, 241, 0)',
        ],
      }}
      transition={{ duration: 2, repeat: Infinity }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

// ── 打字机效果 ───────────────────────────────────────
export function Typewriter({
  text,
  speed = 50,
  className = '',
}: {
  text: string
  speed?: number
  className?: string
}) {
  return (
    <motion.span
      initial={{ width: 0 }}
      animate={{ width: '100%' }}
      transition={{ duration: text.length * speed / 1000 }}
      className={`overflow-hidden whitespace-nowrap ${className}`}
    >
      {text}
    </motion.span>
  )
}

// ── 渐变文字 ─────────────────────────────────────────
export function GradientText({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={`bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 bg-clip-text text-transparent ${className}`}
    >
      {children}
    </span>
  )
}

// ── 卡片悬浮效果 ─────────────────────────────────────
export function FloatingCard({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <motion.div
      whileHover={{
        y: -4,
        boxShadow: '0 12px 40px rgba(0, 0, 0, 0.12)',
      }}
      transition={{ duration: 0.3 }}
      className={`bg-white rounded-xl border border-gray-100 ${className}`}
    >
      {children}
    </motion.div>
  )
}

// ── 容器动画（用于列表） ─────────────────────────────
export const containerVariants = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: {
      staggerChildren: 0.05,
    },
  },
}

export const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0 },
}
