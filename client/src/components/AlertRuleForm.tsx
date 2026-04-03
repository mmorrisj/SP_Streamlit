import { useState, useEffect } from 'react'
import { X } from 'lucide-react'
import type { AlertRule, AlertRuleCreateRequest } from '../api/client'
import './AlertRuleForm.css'

const CONDITION_TYPES = [
  { value: 'materiality_spike', label: 'Materiality Spike', description: 'Z-score on daily materiality scores' },
  { value: 'volume_surge', label: 'Document Volume Surge', description: 'Z-score on daily document counts' },
  { value: 'new_entity', label: 'New Entity Detected', description: 'New person, org, or company appears' },
  { value: 'new_event', label: 'New Event Detected', description: 'New event with optional materiality filter' },
]

const INFLUENCERS = ['China', 'Iran', 'Russia', 'Turkey', 'United States']
const CATEGORIES = ['Economic', 'Social', 'Military', 'Diplomacy']
const SEVERITY_OPTIONS = ['info', 'warning', 'critical']
const ENTITY_TYPES = ['person', 'organization', 'company']

interface AlertRuleFormProps {
  rule?: AlertRule | null
  onSubmit: (data: AlertRuleCreateRequest) => void
  onClose: () => void
}

export default function AlertRuleForm({ rule, onSubmit, onClose }: AlertRuleFormProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [conditionType, setConditionType] = useState('materiality_spike')
  const [severity, setSeverity] = useState('info')
  const [cooldown, setCooldown] = useState(60)

  // Condition params
  const [country, setCountry] = useState('')
  const [category, setCategory] = useState('')
  const [thresholdZ, setThresholdZ] = useState(2.0)
  const [windowDays, setWindowDays] = useState(30)
  const [entityType, setEntityType] = useState('')
  const [minMateriality, setMinMateriality] = useState(3.0)

  // Channels
  const [inApp, setInApp] = useState(true)
  const [slack, setSlack] = useState(false)
  const [email, setEmail] = useState(false)
  const [slackWebhook, setSlackWebhook] = useState('')
  const [emailAddress, setEmailAddress] = useState('')

  // Populate for editing
  useEffect(() => {
    if (rule) {
      setName(rule.name)
      setDescription(rule.description || '')
      setConditionType(rule.condition_type)
      setSeverity(rule.severity)
      setCooldown(rule.cooldown_minutes)

      const p = rule.condition_params
      setCountry((p.country as string) || '')
      setCategory((p.category as string) || '')
      setThresholdZ((p.threshold_z as number) || 2.0)
      setWindowDays((p.window_days as number) || 30)
      setEntityType((p.entity_type as string) || '')
      setMinMateriality((p.min_materiality as number) || 3.0)

      setInApp(rule.channels.includes('in_app'))
      setSlack(rule.channels.includes('slack'))
      setEmail(rule.channels.includes('email'))
      setSlackWebhook((rule.channel_config.slack_webhook_url as string) || '')
      setEmailAddress((rule.channel_config.email as string) || '')
    }
  }, [rule])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    const conditionParams: Record<string, unknown> = {}
    if (country) conditionParams.country = country

    if (conditionType === 'materiality_spike' || conditionType === 'volume_surge') {
      conditionParams.threshold_z = thresholdZ
      conditionParams.window_days = windowDays
      if (conditionType === 'materiality_spike' && category) {
        conditionParams.category = category
      }
    } else if (conditionType === 'new_entity') {
      if (entityType) conditionParams.entity_type = entityType
    } else if (conditionType === 'new_event') {
      conditionParams.min_materiality = minMateriality
    }

    const channels: string[] = []
    if (inApp) channels.push('in_app')
    if (slack) channels.push('slack')
    if (email) channels.push('email')

    const channelConfig: Record<string, unknown> = {}
    if (slack && slackWebhook) channelConfig.slack_webhook_url = slackWebhook
    if (email && emailAddress) channelConfig.email = emailAddress

    onSubmit({
      name,
      description: description || undefined,
      condition_type: conditionType,
      condition_params: conditionParams,
      channels,
      channel_config: channelConfig,
      severity,
      cooldown_minutes: cooldown,
    })
  }

  const needsZScore = conditionType === 'materiality_spike' || conditionType === 'volume_surge'

  return (
    <div className="alert-form-overlay" onClick={onClose}>
      <div className="alert-form-modal" onClick={e => e.stopPropagation()}>
        <div className="alert-form-header">
          <h2>{rule ? 'Edit Alert Rule' : 'Create Alert Rule'}</h2>
          <button className="alert-form-close" onClick={onClose}><X size={20} /></button>
        </div>

        <form onSubmit={handleSubmit} className="alert-form-body">
          {/* Name */}
          <div className="form-group">
            <label>Rule Name *</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g., China Military Materiality Alert"
              required
            />
          </div>

          {/* Description */}
          <div className="form-group">
            <label>Description</label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Optional description of what this alert monitors"
              rows={2}
            />
          </div>

          {/* Condition Type */}
          <div className="form-group">
            <label>Condition Type *</label>
            <select value={conditionType} onChange={e => setConditionType(e.target.value)}>
              {CONDITION_TYPES.map(ct => (
                <option key={ct.value} value={ct.value}>{ct.label}</option>
              ))}
            </select>
            <span className="form-hint">
              {CONDITION_TYPES.find(ct => ct.value === conditionType)?.description}
            </span>
          </div>

          {/* Condition Parameters */}
          <fieldset className="form-fieldset">
            <legend>Condition Parameters</legend>

            <div className="form-row">
              <div className="form-group">
                <label>Country (optional)</label>
                <select value={country} onChange={e => setCountry(e.target.value)}>
                  <option value="">All countries</option>
                  {INFLUENCERS.map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>

              {conditionType === 'materiality_spike' && (
                <div className="form-group">
                  <label>Category (optional)</label>
                  <select value={category} onChange={e => setCategory(e.target.value)}>
                    <option value="">All categories</option>
                    {CATEGORIES.map(c => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            {needsZScore && (
              <div className="form-row">
                <div className="form-group">
                  <label>Z-Score Threshold</label>
                  <input
                    type="number"
                    step="0.1"
                    min="1"
                    max="5"
                    value={thresholdZ}
                    onChange={e => setThresholdZ(parseFloat(e.target.value))}
                  />
                  <span className="form-hint">Standard deviations above mean (2.0 = ~97th percentile)</span>
                </div>
                <div className="form-group">
                  <label>Window (days)</label>
                  <input
                    type="number"
                    min="7"
                    max="90"
                    value={windowDays}
                    onChange={e => setWindowDays(parseInt(e.target.value))}
                  />
                </div>
              </div>
            )}

            {conditionType === 'new_entity' && (
              <div className="form-group">
                <label>Entity Type (optional)</label>
                <select value={entityType} onChange={e => setEntityType(e.target.value)}>
                  <option value="">All types</option>
                  {ENTITY_TYPES.map(t => (
                    <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
                  ))}
                </select>
              </div>
            )}

            {conditionType === 'new_event' && (
              <div className="form-group">
                <label>Minimum Materiality Score</label>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  max="5"
                  value={minMateriality}
                  onChange={e => setMinMateriality(parseFloat(e.target.value))}
                />
              </div>
            )}
          </fieldset>

          {/* Severity */}
          <div className="form-group">
            <label>Severity</label>
            <div className="severity-selector">
              {SEVERITY_OPTIONS.map(s => (
                <button
                  key={s}
                  type="button"
                  className={`severity-option ${severity === s ? 'active' : ''} severity-${s}`}
                  onClick={() => setSeverity(s)}
                >
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Channels */}
          <fieldset className="form-fieldset">
            <legend>Notification Channels</legend>
            <div className="channel-checks">
              <label className="check-label">
                <input type="checkbox" checked={inApp} onChange={e => setInApp(e.target.checked)} />
                In-App
              </label>
              <label className="check-label">
                <input type="checkbox" checked={slack} onChange={e => setSlack(e.target.checked)} />
                Slack
              </label>
              <label className="check-label">
                <input type="checkbox" checked={email} onChange={e => setEmail(e.target.checked)} />
                Email
              </label>
            </div>

            {slack && (
              <div className="form-group">
                <label>Slack Webhook URL</label>
                <input
                  type="url"
                  value={slackWebhook}
                  onChange={e => setSlackWebhook(e.target.value)}
                  placeholder="https://hooks.slack.com/services/..."
                />
              </div>
            )}

            {email && (
              <div className="form-group">
                <label>Email Address</label>
                <input
                  type="email"
                  value={emailAddress}
                  onChange={e => setEmailAddress(e.target.value)}
                  placeholder="analyst@org.gov"
                />
              </div>
            )}
          </fieldset>

          {/* Cooldown */}
          <div className="form-group">
            <label>Cooldown (minutes)</label>
            <input
              type="number"
              min="5"
              max="1440"
              value={cooldown}
              onChange={e => setCooldown(parseInt(e.target.value))}
            />
            <span className="form-hint">Minimum time between triggers for this rule</span>
          </div>

          {/* Actions */}
          <div className="alert-form-actions">
            <button type="button" className="btn-cancel" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn-submit">
              {rule ? 'Update Rule' : 'Create Rule'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
