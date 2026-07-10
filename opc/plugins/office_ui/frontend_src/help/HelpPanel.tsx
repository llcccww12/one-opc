import { useState } from 'react'
import { MarkdownBody } from '../chat/MarkdownBody'
import { HELP_SECTIONS } from './helpContent'
import './help.css'

interface HelpPanelProps {
  open: boolean
  onClose: () => void
}

export function HelpPanel({ open, onClose }: HelpPanelProps) {
  const [activeId, setActiveId] = useState(HELP_SECTIONS[0].id)

  if (!open) return null

  const active = HELP_SECTIONS.find(section => section.id === activeId) ?? HELP_SECTIONS[0]

  return (
    <div className="help-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="help-panel" role="dialog" aria-modal="true" aria-labelledby="help-panel-title" onMouseDown={e => e.stopPropagation()}>
        <div className="help-header">
          <span id="help-panel-title" className="help-title">使用手册</span>
          <button type="button" className="help-close" onClick={onClose} aria-label="Close">x</button>
        </div>
        <div className="help-body">
          <nav className="help-nav">
            {HELP_SECTIONS.map(section => (
              <button
                key={section.id}
                className={`help-nav-item${section.id === activeId ? ' help-nav-item--active' : ''}`}
                onClick={() => setActiveId(section.id)}
              >
                {section.title}
              </button>
            ))}
          </nav>
          <div className="help-content">
            <MarkdownBody content={active.body} className="msg-content-agent help-markdown" collapseMode="never" />
          </div>
        </div>
      </div>
    </div>
  )
}
