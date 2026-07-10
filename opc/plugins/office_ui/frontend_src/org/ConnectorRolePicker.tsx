import { useEffect, useMemo, useState } from 'react'
import type { ConnectorInfo, OrgRole } from '../types/visual'

interface ConnectorRolePickerProps {
  connector: ConnectorInfo
  roles: OrgRole[]
  onClose: () => void
  onSave: (roleIds: string[]) => void
}

export function ConnectorRolePicker({ connector, roles, onClose, onSave }: ConnectorRolePickerProps) {
  const initiallySelected = useMemo(
    () => new Set(roles.filter(role => connector.actions.some(action => role.tools.includes(action))).map(role => role.role_id)),
    [roles, connector],
  )
  const [selected, setSelected] = useState<Set<string>>(initiallySelected)

  useEffect(() => {
    setSelected(initiallySelected)
  }, [initiallySelected])

  const toggle = (roleId: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(roleId)) next.delete(roleId)
      else next.add(roleId)
      return next
    })
  }

  return (
    <div className="org-create-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="org-create-modal" role="dialog" aria-modal="true" aria-labelledby="connector-role-picker-title" onMouseDown={e => e.stopPropagation()}>
        <div className="org-create-header">
          <div>
            <span className="org-create-eyebrow">{connector.name}</span>
            <h3 id="connector-role-picker-title" className="org-create-title">Roles with access</h3>
          </div>
          <button type="button" className="org-create-close" onClick={onClose} aria-label="Close">x</button>
        </div>

        <div className="org-create-panel">
          {roles.length > 0 ? (
            <div className="org-create-member-list">
              {roles.map(role => (
                <label key={role.role_id} className="org-conn-role-row">
                  <input type="checkbox" checked={selected.has(role.role_id)} onChange={() => toggle(role.role_id)} />
                  <span>{role.name}</span>
                </label>
              ))}
            </div>
          ) : (
            <div className="myorg-empty-hint">No roles yet.</div>
          )}
        </div>

        <div className="org-create-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={() => onSave(Array.from(selected))}>Save</button>
        </div>
      </div>
    </div>
  )
}
