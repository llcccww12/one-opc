/**
 * OpenOPC 摩登极简风设计系统
 *
 * 风格定义：
 * - 配色：白色为主背景，深色文字，点缀色克制使用
 * - 圆角：小圆角（6-8px），友好有机
 * - 字体：大标题，高可读性，Inter/SF Pro
 * - 留白：大量留白，呼吸感
 * - 动画：微妙的过渡动画
 */

export const theme = {
  // 颜色系统
  colors: {
    // 背景色
    bg: {
      primary: '#ffffff',
      secondary: '#f8fafc',
      tertiary: '#f1f5f9',
      elevated: '#ffffff',
    },

    // 文字色
    text: {
      primary: '#0f172a',
      secondary: '#64748b',
      muted: '#94a3b8',
      inverse: '#ffffff',
    },

    // 边框色
    border: {
      default: '#e2e8f0',
      hover: '#cbd5e1',
      focus: '#6366f1',
    },

    // 强调色（克制使用）
    accent: {
      primary: '#6366f1',
      light: '#eef2ff',
      dark: '#4f46e5',
    },

    // 状态色
    status: {
      success: '#10b981',
      warning: '#f59e0b',
      error: '#ef4444',
      info: '#3b82f6',
    },
  },

  // 圆角
  borderRadius: {
    sm: '6px',
    md: '8px',
    lg: '12px',
    xl: '16px',
    full: '9999px',
  },

  // 字体
  fontSize: {
    xs: '12px',
    sm: '14px',
    base: '16px',
    lg: '18px',
    xl: '24px',
    '2xl': '32px',
    '3xl': '40px',
    '4xl': '48px',
  },

  // 字体权重
  fontWeight: {
    normal: '400',
    medium: '500',
    semibold: '600',
    bold: '700',
  },

  // 间距
  spacing: {
    xs: '4px',
    sm: '8px',
    md: '12px',
    lg: '16px',
    xl: '24px',
    '2xl': '32px',
    '3xl': '48px',
  },

  // 阴影
  boxShadow: {
    sm: '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
    md: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
    lg: '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
    xl: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)',
  },

  // 过渡
  transition: {
    fast: '150ms ease',
    normal: '200ms ease',
    slow: '300ms ease',
  },

  // 布局
  layout: {
    sidebar: '280px',
    header: '56px',
    contentMaxWidth: '1200px',
  },
} as const

// 导出 CSS 变量格式
export const cssVariables = `
  :root {
    /* 背景色 */
    --bg-primary: ${theme.colors.bg.primary};
    --bg-secondary: ${theme.colors.bg.secondary};
    --bg-tertiary: ${theme.colors.bg.tertiary};
    --bg-elevated: ${theme.colors.bg.elevated};

    /* 文字色 */
    --text-primary: ${theme.colors.text.primary};
    --text-secondary: ${theme.colors.text.secondary};
    --text-muted: ${theme.colors.text.muted};
    --text-inverse: ${theme.colors.text.inverse};

    /* 边框色 */
    --border-default: ${theme.colors.border.default};
    --border-hover: ${theme.colors.border.hover};
    --border-focus: ${theme.colors.border.focus};

    /* 强调色 */
    --accent-primary: ${theme.colors.accent.primary};
    --accent-light: ${theme.colors.accent.light};
    --accent-dark: ${theme.colors.accent.dark};

    /* 状态色 */
    --status-success: ${theme.colors.status.success};
    --status-warning: ${theme.colors.status.warning};
    --status-error: ${theme.colors.status.error};
    --status-info: ${theme.colors.status.info};

    /* 圆角 */
    --radius-sm: ${theme.borderRadius.sm};
    --radius-md: ${theme.borderRadius.md};
    --radius-lg: ${theme.borderRadius.lg};
    --radius-xl: ${theme.borderRadius.xl};
    --radius-full: ${theme.borderRadius.full};

    /* 字体 */
    --font-xs: ${theme.fontSize.xs};
    --font-sm: ${theme.fontSize.sm};
    --font-base: ${theme.fontSize.base};
    --font-lg: ${theme.fontSize.lg};
    --font-xl: ${theme.fontSize.xl};
    --font-2xl: ${theme.fontSize['2xl']};
    --font-3xl: ${theme.fontSize['3xl']};

    /* 间距 */
    --spacing-xs: ${theme.spacing.xs};
    --spacing-sm: ${theme.spacing.sm};
    --spacing-md: ${theme.spacing.md};
    --spacing-lg: ${theme.spacing.lg};
    --spacing-xl: ${theme.spacing.xl};
    --spacing-2xl: ${theme.spacing['2xl']};

    /* 阴影 */
    --shadow-sm: ${theme.boxShadow.sm};
    --shadow-md: ${theme.boxShadow.md};
    --shadow-lg: ${theme.boxShadow.lg};
    --shadow-xl: ${theme.boxShadow.xl};

    /* 过渡 */
    --transition-fast: ${theme.transition.fast};
    --transition-normal: ${theme.transition.normal};
    --transition-slow: ${theme.transition.slow};

    /* 布局 */
    --layout-sidebar: ${theme.layout.sidebar};
    --layout-header: ${theme.layout.header};
    --layout-content-max-width: ${theme.layout.contentMaxWidth};
  }
`
