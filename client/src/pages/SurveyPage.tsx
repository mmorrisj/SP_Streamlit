import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Star, CheckCircle2, BarChart3 } from 'lucide-react'
import { toast } from 'sonner'
import { submitSurveyResponse, fetchSurveyResults, type SurveyAnswers } from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import PageGuide from '../components/PageGuide'
import './Pages.css'
import './SurveyPage.css'

/**
 * Question set for the demo feedback survey. Keys are stable identifiers that
 * end up in survey_responses.answers, so rename labels freely but keep keys.
 */
const FEATURE_RATINGS: { key: string; label: string; hint: string }[] = [
  { key: 'dashboard', label: 'Dashboard & intelligence feed', hint: 'Latest narratives, activity indicators, trends' },
  { key: 'events', label: 'Events & materiality', hint: 'Consolidated events, scores, lifecycle phases' },
  { key: 'research_agent', label: 'Research & Agent assistants', hint: 'Question answering over the corpus' },
  { key: 'reports', label: 'Reports', hint: 'Publication reports and Insight Reports' },
  { key: 'navigation', label: 'Ease of navigation', hint: 'Finding your way around the platform' },
  { key: 'trust', label: 'Trust in the analysis', hint: 'Confidence in AI-generated content given the cited sources' },
]

const WOULD_USE_OPTIONS = [
  { value: 'yes', label: 'Yes' },
  { value: 'maybe', label: 'Maybe' },
  { value: 'no', label: 'No' },
]

function StarRating({ value, onChange, name }: { value: number | null; onChange: (v: number) => void; name: string }) {
  const [hover, setHover] = useState<number | null>(null)
  const active = hover ?? value ?? 0
  return (
    <div className="survey-stars" role="radiogroup" aria-label={name} onMouseLeave={() => setHover(null)}>
      {[1, 2, 3, 4, 5].map(n => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={value === n}
          aria-label={`${n} of 5`}
          className={`survey-star ${n <= active ? 'filled' : ''}`}
          onMouseEnter={() => setHover(n)}
          onClick={() => onChange(n)}
        >
          <Star size={22} fill={n <= active ? 'currentColor' : 'none'} />
        </button>
      ))}
    </div>
  )
}

function ResultsPanel() {
  const { data, isLoading, error } = useQuery({ queryKey: ['survey-results'], queryFn: fetchSurveyResults })
  if (isLoading) return <div className="survey-results-loading">Loading responses…</div>
  if (error || !data) return <div className="survey-results-loading">Could not load responses.</div>

  const { summary, responses } = data
  const labelFor = (key: string) => FEATURE_RATINGS.find(f => f.key === key)?.label || key
  const textFeedback = responses.filter(r => r.answers.most_valuable || r.answers.missing_confusing)

  return (
    <div className="survey-results">
      <div className="survey-summary-row">
        <div className="survey-summary-stat">
          <span className="survey-summary-value">{summary.count}</span>
          <span className="survey-summary-label">responses</span>
        </div>
        <div className="survey-summary-stat">
          <span className="survey-summary-value">{summary.avg_overall ?? '—'}</span>
          <span className="survey-summary-label">avg overall (of 5)</span>
        </div>
        {WOULD_USE_OPTIONS.map(o => (
          <div className="survey-summary-stat" key={o.value}>
            <span className="survey-summary-value">{summary.would_use_counts[o.value] || 0}</span>
            <span className="survey-summary-label">would use: {o.label.toLowerCase()}</span>
          </div>
        ))}
      </div>

      {Object.keys(summary.rating_averages).length > 0 && (
        <div className="survey-avg-bars">
          {Object.entries(summary.rating_averages).map(([key, avg]) => (
            <div className="survey-avg-bar-row" key={key}>
              <span className="survey-avg-bar-label">{labelFor(key)}</span>
              <div className="survey-avg-bar-track">
                <div className="survey-avg-bar-fill" style={{ width: `${(avg / 5) * 100}%` }} />
              </div>
              <span className="survey-avg-bar-value">{avg.toFixed(1)}</span>
            </div>
          ))}
        </div>
      )}

      {textFeedback.length > 0 && (
        <div className="survey-comments">
          <h3>Written feedback</h3>
          {textFeedback.map(r => (
            <div className="survey-comment-card" key={r.id}>
              <div className="survey-comment-meta">
                {r.display_name || r.username || 'Anonymous'}
                {r.answers.respondent_role ? ` — ${r.answers.respondent_role}` : ''}
                {r.created_at ? ` · ${new Date(r.created_at).toLocaleString()}` : ''}
                {r.overall_rating != null ? ` · ${r.overall_rating}/5 overall` : ''}
              </div>
              {r.answers.most_valuable && (
                <p><strong>Most valuable:</strong> {r.answers.most_valuable}</p>
              )}
              {r.answers.missing_confusing && (
                <p><strong>Missing / confusing:</strong> {r.answers.missing_confusing}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function SurveyPage() {
  const { user } = useAuth()
  const canViewResults = user?.role === 'admin' || user?.role === 'analyst'
  const [showResults, setShowResults] = useState(false)

  const [overall, setOverall] = useState<number | null>(null)
  const [ratings, setRatings] = useState<Record<string, number>>({})
  const [wouldUse, setWouldUse] = useState<string | null>(null)
  const [mostValuable, setMostValuable] = useState('')
  const [missingConfusing, setMissingConfusing] = useState('')
  const [respondentRole, setRespondentRole] = useState('')
  const [submitted, setSubmitted] = useState(false)

  const hasAnyAnswer = useMemo(
    () =>
      overall !== null ||
      Object.keys(ratings).length > 0 ||
      wouldUse !== null ||
      mostValuable.trim() !== '' ||
      missingConfusing.trim() !== '',
    [overall, ratings, wouldUse, mostValuable, missingConfusing]
  )

  const mutation = useMutation({
    mutationFn: submitSurveyResponse,
    onSuccess: () => setSubmitted(true),
    onError: () => toast.error('Could not submit your feedback — please try again.'),
  })

  const submit = () => {
    if (!hasAnyAnswer) {
      toast.warning('Answer at least one question before submitting.')
      return
    }
    const answers: SurveyAnswers = {
      ratings,
      would_use: wouldUse ?? undefined,
      most_valuable: mostValuable.trim() || undefined,
      missing_confusing: missingConfusing.trim() || undefined,
      respondent_role: respondentRole.trim() || undefined,
    }
    mutation.mutate({ overall_rating: overall, answers })
  }

  const reset = () => {
    setOverall(null)
    setRatings({})
    setWouldUse(null)
    setMostValuable('')
    setMissingConfusing('')
    setRespondentRole('')
    setSubmitted(false)
  }

  return (
    <div className="page">
      <header className="page-header">
        <h1>Feedback</h1>
        <p>Tell us what worked and what didn't — your feedback shapes what gets built next</p>
      </header>

      <PageGuide page="survey" />

      {canViewResults && (
        <div className="survey-tabs">
          <button className={`survey-tab ${!showResults ? 'active' : ''}`} onClick={() => setShowResults(false)}>
            Give feedback
          </button>
          <button className={`survey-tab ${showResults ? 'active' : ''}`} onClick={() => setShowResults(true)}>
            <BarChart3 size={14} /> Responses
          </button>
        </div>
      )}

      {showResults && canViewResults ? (
        <ResultsPanel />
      ) : submitted ? (
        <div className="survey-thanks">
          <CheckCircle2 size={40} />
          <h2>Thank you!</h2>
          <p>Your feedback has been recorded.</p>
          <button className="survey-secondary-btn" onClick={reset}>
            Submit another response
          </button>
        </div>
      ) : (
        <div className="survey-form">
          <div className="survey-section">
            <label className="survey-question">Overall, how would you rate the platform?</label>
            <StarRating value={overall} onChange={setOverall} name="Overall rating" />
          </div>

          <div className="survey-section">
            <label className="survey-question">How useful did you find each area?</label>
            <div className="survey-feature-grid">
              {FEATURE_RATINGS.map(f => (
                <div className="survey-feature-row" key={f.key}>
                  <div className="survey-feature-text">
                    <span className="survey-feature-label">{f.label}</span>
                    <span className="survey-feature-hint">{f.hint}</span>
                  </div>
                  <StarRating
                    value={ratings[f.key] ?? null}
                    onChange={v => setRatings(prev => ({ ...prev, [f.key]: v }))}
                    name={f.label}
                  />
                </div>
              ))}
            </div>
          </div>

          <div className="survey-section">
            <label className="survey-question">Would you use this platform in your own work?</label>
            <div className="survey-choice-row">
              {WOULD_USE_OPTIONS.map(o => (
                <button
                  key={o.value}
                  type="button"
                  className={`survey-choice ${wouldUse === o.value ? 'selected' : ''}`}
                  onClick={() => setWouldUse(o.value)}
                >
                  {o.label}
                </button>
              ))}
            </div>
          </div>

          <div className="survey-section">
            <label className="survey-question" htmlFor="survey-valuable">
              What was most valuable to you?
            </label>
            <textarea
              id="survey-valuable"
              rows={3}
              maxLength={2000}
              placeholder="The feature, view, or insight you'd come back for…"
              value={mostValuable}
              onChange={e => setMostValuable(e.target.value)}
            />
          </div>

          <div className="survey-section">
            <label className="survey-question" htmlFor="survey-missing">
              What was missing, confusing, or didn't work?
            </label>
            <textarea
              id="survey-missing"
              rows={3}
              maxLength={2000}
              placeholder="Anything that slowed you down or that you expected to find…"
              value={missingConfusing}
              onChange={e => setMissingConfusing(e.target.value)}
            />
          </div>

          <div className="survey-section">
            <label className="survey-question" htmlFor="survey-role">
              Your role or organization <span className="survey-optional">(optional)</span>
            </label>
            <input
              id="survey-role"
              type="text"
              maxLength={200}
              placeholder="e.g. Regional analyst, Policy office…"
              value={respondentRole}
              onChange={e => setRespondentRole(e.target.value)}
            />
          </div>

          <div className="survey-actions">
            <button className="survey-submit-btn" onClick={submit} disabled={mutation.isPending}>
              {mutation.isPending ? 'Submitting…' : 'Submit feedback'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
