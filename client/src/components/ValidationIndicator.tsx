import React, { useState } from 'react'
import { CheckCircle, AlertCircle, XCircle, Loader2 } from 'lucide-react'
import { ValidationStatus } from '../api/client'
import './ValidationIndicator.css'

interface ValidationIndicatorProps {
  status: ValidationStatus
  issues?: string[]
  summary?: string
  claimsValidated?: number
  uncitedClaims?: number
  onClick?: () => void
}

const statusConfig = {
  green: {
    bg: '#dcfce7',
    border: '#22c55e',
    text: '#166534',
    label: 'Verified',
    Icon: CheckCircle,
  },
  yellow: {
    bg: '#fef9c3',
    border: '#eab308',
    text: '#854d0e',
    label: 'Issues',
    Icon: AlertCircle,
  },
  red: {
    bg: '#fee2e2',
    border: '#ef4444',
    text: '#991b1b',
    label: 'Problems',
    Icon: XCircle,
  },
  pending: {
    bg: '#f1f5f9',
    border: '#94a3b8',
    text: '#475569',
    label: 'Validating',
    Icon: Loader2,
  },
}

export function ValidationIndicator({
  status,
  issues = [],
  summary,
  claimsValidated,
  uncitedClaims,
  onClick,
}: ValidationIndicatorProps) {
  const [showTooltip, setShowTooltip] = useState(false)
  const config = statusConfig[status]
  const Icon = config.Icon

  const hasDetails = issues.length > 0 || summary || claimsValidated !== undefined

  return (
    <div
      className="validation-indicator-container"
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <span
        className={`validation-indicator ${status === 'pending' ? 'validating' : ''}`}
        style={{
          background: config.bg,
          border: `1px solid ${config.border}`,
          color: config.text,
          cursor: onClick || hasDetails ? 'pointer' : 'default',
        }}
        onClick={onClick}
        title={config.label}
      >
        <Icon
          size={12}
          className={status === 'pending' ? 'spin-animation' : ''}
        />
      </span>

      {showTooltip && hasDetails && (
        <div className="validation-tooltip">
          <div className="validation-tooltip-header">
            <Icon size={14} style={{ color: config.text }} />
            <span style={{ color: config.text, fontWeight: 600 }}>{config.label}</span>
          </div>

          {summary && (
            <div className="validation-tooltip-summary">{summary}</div>
          )}

          {(claimsValidated !== undefined || uncitedClaims !== undefined) && (
            <div className="validation-tooltip-stats">
              {claimsValidated !== undefined && (
                <span>Claims validated: {claimsValidated}</span>
              )}
              {uncitedClaims !== undefined && uncitedClaims > 0 && (
                <span className="uncited-warning">Uncited claims: {uncitedClaims}</span>
              )}
            </div>
          )}

          {issues.length > 0 && (
            <div className="validation-tooltip-issues">
              <div className="issues-header">Issues:</div>
              <ul>
                {issues.slice(0, 3).map((issue, i) => (
                  <li key={i}>{issue}</li>
                ))}
                {issues.length > 3 && (
                  <li className="more-issues">+{issues.length - 3} more...</li>
                )}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default ValidationIndicator
