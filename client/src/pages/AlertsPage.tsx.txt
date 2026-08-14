import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, Plus, Trash2, Play, ToggleLeft, ToggleRight, ChevronDown, ChevronUp } from 'lucide-react'
import {
  fetchAlertRules, fetchAlertHistory, createAlertRule,
  updateAlertRule, deleteAlertRule, acknowledgeAlert, testAlertRule,
} from '../api/client'
import type { AlertRule, AlertHistory, AlertRuleCreateRequest } from '../api/client'
import AlertRuleForm from '../components/AlertRuleForm'
import PageGuide from '../components/PageGuide'
import './AlertsPage.css'

const CONDITION_LABELS: Record<string, string> = {
  materiality_spike: 'Materiality Spike',
  volume_surge: 'Volume Surge',
  new_entity: 'New Entity',
  new_event: 'New Event',
}

const SEVERITY_COLORS: Record<string, string> = {
  info: '#2563eb',
  warning: '#d97706',
  critical: '#dc2626',
}

export default function AlertsPage() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<'rules' | 'history'>('rules')
  const [showForm, setShowForm] = useState(false)
  const [editingRule, setEditingRule] = useState<AlertRule | null>(null)
  const [expandedAlert, setExpandedAlert] = useState<string | null>(null)
  const [historyOffset, setHistoryOffset] = useState(0)

  const { data: rules = [], isLoading: rulesLoading } = useQuery({
    queryKey: ['alerts', 'rules'],
    queryFn: fetchAlertRules,
  })

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ['alerts', 'history', historyOffset],
    queryFn: () => fetchAlertHistory({ limit: 20, offset: historyOffset }),
    enabled: activeTab === 'history',
  })

  const invalidateAlerts = () => {
    queryClient.invalidateQueries({ queryKey: ['alerts'] })
  }

  const handleCreateOrUpdate = async (data: AlertRuleCreateRequest) => {
    if (editingRule) {
      await updateAlertRule(editingRule.id, data)
    } else {
      await createAlertRule(data)
    }
    setShowForm(false)
    setEditingRule(null)
    invalidateAlerts()
  }

  const handleDelete = async (ruleId: string) => {
    if (!confirm('Delete this alert rule?')) return
    await deleteAlertRule(ruleId)
    invalidateAlerts()
  }

  const handleToggle = async (rule: AlertRule) => {
    await updateAlertRule(rule.id, { is_enabled: !rule.is_enabled })
    invalidateAlerts()
  }

  const handleTest = async (ruleId: string) => {
    const result = await testAlertRule(ruleId)
    if (result.triggered) {
      alert(`Alert triggered: ${result.alert?.title}`)
    } else {
      alert(result.message || 'Condition not met')
    }
    invalidateAlerts()
  }

  const handleAcknowledge = async (alertId: string) => {
    await acknowledgeAlert(alertId)
    invalidateAlerts()
  }

  return (
    <div className="alerts-page">
      <div className="page-header">
        <div className="header-content">
          <div>
            <h1><Bell size={24} /> Alerts</h1>
            <p>Configure alert rules and review triggered notifications</p>
          </div>
          {activeTab === 'rules' && (
            <button className="create-button" onClick={() => { setEditingRule(null); setShowForm(true) }}>
              <Plus size={18} /> Create Rule
            </button>
          )}
        </div>

        <PageGuide page="alerts" />

        <div className="tab-bar">
          <button
            className={`tab ${activeTab === 'rules' ? 'active' : ''}`}
            onClick={() => setActiveTab('rules')}
          >
            Rules ({rules.length})
          </button>
          <button
            className={`tab ${activeTab === 'history' ? 'active' : ''}`}
            onClick={() => setActiveTab('history')}
          >
            History {historyData?.total ? `(${historyData.total})` : ''}
          </button>
        </div>
      </div>

      {/* Rules Tab */}
      {activeTab === 'rules' && (
        <div className="rules-grid">
          {rulesLoading ? (
            <div className="loading-state">Loading rules...</div>
          ) : rules.length === 0 ? (
            <div className="empty-state">
              <Bell size={40} />
              <p>No alert rules configured</p>
              <button className="create-button" onClick={() => setShowForm(true)}>
                <Plus size={18} /> Create your first rule
              </button>
            </div>
          ) : (
            rules.map((rule: AlertRule) => (
              <div key={rule.id} className={`rule-card ${!rule.is_enabled ? 'disabled' : ''}`}>
                <div className="rule-card-header">
                  <div className="rule-card-title">
                    <span
                      className="severity-indicator"
                      style={{ background: SEVERITY_COLORS[rule.severity] }}
                    />
                    <h3>{rule.name}</h3>
                  </div>
                  <div className="rule-card-actions">
                    <button
                      className="icon-btn"
                      title="Test rule"
                      onClick={() => handleTest(rule.id)}
                    >
                      <Play size={14} />
                    </button>
                    <button
                      className="icon-btn"
                      title={rule.is_enabled ? 'Disable' : 'Enable'}
                      onClick={() => handleToggle(rule)}
                    >
                      {rule.is_enabled ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
                    </button>
                    <button
                      className="icon-btn danger"
                      title="Delete"
                      onClick={() => handleDelete(rule.id)}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>

                {rule.description && (
                  <p className="rule-card-desc">{rule.description}</p>
                )}

                <div className="rule-card-meta">
                  <span className="meta-badge condition">
                    {CONDITION_LABELS[rule.condition_type] || rule.condition_type}
                  </span>
                  {'country' in rule.condition_params && rule.condition_params.country ? (
                    <span className="meta-badge country">{String(rule.condition_params.country)}</span>
                  ) : null}
                  {'category' in rule.condition_params && rule.condition_params.category ? (
                    <span className="meta-badge category">{String(rule.condition_params.category)}</span>
                  ) : null}
                  <span className="meta-badge channels">
                    {(rule.channels || []).join(', ')}
                  </span>
                </div>

                <div className="rule-card-footer">
                  <span className="rule-card-time">
                    {rule.last_triggered_at
                      ? `Last triggered: ${new Date(rule.last_triggered_at).toLocaleString()}`
                      : 'Never triggered'}
                  </span>
                  <button
                    className="edit-link"
                    onClick={() => { setEditingRule(rule); setShowForm(true) }}
                  >
                    Edit
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* History Tab */}
      {activeTab === 'history' && (
        <div className="history-list">
          {historyLoading ? (
            <div className="loading-state">Loading history...</div>
          ) : !historyData?.alerts?.length ? (
            <div className="empty-state">
              <Bell size={40} />
              <p>No alerts have been triggered yet</p>
            </div>
          ) : (
            <>
              {historyData.alerts.map((alert: AlertHistory) => (
                <div
                  key={alert.id}
                  className={`history-card ${!alert.acknowledged ? 'unread' : ''}`}
                >
                  <div
                    className="history-card-main"
                    onClick={() => setExpandedAlert(expandedAlert === alert.id ? null : alert.id)}
                  >
                    <span
                      className="severity-indicator"
                      style={{ background: SEVERITY_COLORS[alert.severity] }}
                    />
                    <div className="history-card-content">
                      <div className="history-card-title">{alert.title}</div>
                      <div className="history-card-message">{alert.message}</div>
                      <div className="history-card-time">
                        {alert.triggered_at
                          ? new Date(alert.triggered_at).toLocaleString()
                          : ''}
                      </div>
                    </div>
                    <div className="history-card-right">
                      {!alert.acknowledged && (
                        <button
                          className="ack-button"
                          onClick={e => { e.stopPropagation(); handleAcknowledge(alert.id) }}
                        >
                          Acknowledge
                        </button>
                      )}
                      {expandedAlert === alert.id ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                    </div>
                  </div>

                  {expandedAlert === alert.id && alert.context_data && (
                    <div className="history-card-context">
                      <table>
                        <tbody>
                          {Object.entries(alert.context_data).map(([key, value]) => (
                            <tr key={key}>
                              <td className="context-key">{key}</td>
                              <td className="context-value">{String(value)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ))}

              {/* Pagination */}
              {historyData.total > 20 && (
                <div className="history-pagination">
                  <button
                    disabled={historyOffset === 0}
                    onClick={() => setHistoryOffset(Math.max(0, historyOffset - 20))}
                  >
                    Previous
                  </button>
                  <span>
                    {historyOffset + 1}–{Math.min(historyOffset + 20, historyData.total)} of {historyData.total}
                  </span>
                  <button
                    disabled={historyOffset + 20 >= historyData.total}
                    onClick={() => setHistoryOffset(historyOffset + 20)}
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Form Modal */}
      {showForm && (
        <AlertRuleForm
          rule={editingRule}
          onSubmit={handleCreateOrUpdate}
          onClose={() => { setShowForm(false); setEditingRule(null) }}
        />
      )}
    </div>
  )
}
