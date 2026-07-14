// Chart builders for report figures. A builder is chosen by sniffing the
// sidecar CSV's column signature (plus filename guards for shapes recharts
// can't express well — heatmaps, maps, network graphs stay as PNGs).
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, Legend, ScatterChart, Scatter, ZAxis, Cell, ReferenceLine,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
} from 'recharts'
import type { CsvRow, CsvTable } from './csv'

export const ACTOR_COLORS: Record<string, string> = {
  China: '#C8102E',
  Iran: '#1B7A3D',
  Russia: '#1F4E9C',
  Turkey: '#E08A1E',
  'United States': '#4A5568',
}
const GRAY = '#e3e3e0'
const MUTED = '#94a3b8'
const NAVY = '#1a365d'

export interface FigureContext {
  /** accent color for single-actor reports (from the report slug) */
  accent: string
  filename: string
  /** when set, drillable charts open the evidence panel for a clicked item */
  onDrill?: (payload: { name: string; actor?: string }) => void
}

export interface Builder {
  key: string
  render: (t: CsvTable, ctx: FigureContext) => React.ReactNode
}

const has = (t: CsvTable, ...cols: string[]) => cols.every((c) => t.headers.includes(c))
const num = (v: string | number | undefined) => (typeof v === 'number' ? v : 0)
const str = (v: string | number | undefined) => String(v ?? '')

const monthTick = (v: string | number) => {
  const d = new Date(str(v))
  if (Number.isNaN(d.getTime())) return str(v)
  return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
}

const truncate = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + '…' : s)

const compact = (v: number) => (v >= 1000 ? `${v / 1000}k` : String(v))

/** Nice 1-3-10 log ticks covering the data range. */
const logTicks = (values: number[]): number[] => {
  const pos = values.filter((v) => v > 0)
  if (!pos.length) return []
  const lo = Math.min(...pos), hi = Math.max(...pos)
  const ticks: number[] = []
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
    for (const m of [1, 3]) {
      const t = m * 10 ** e
      if (t >= lo * 0.9 && t <= hi * 1.1) ticks.push(t)
    }
  }
  return ticks
}

const pctTick = (v: number) => `${Math.round(v * 100)}%`

const tooltipStyle = {
  contentStyle: { fontSize: 12, borderRadius: 8, border: '1px solid #e2e8f0' },
  labelStyle: { color: NAVY, fontWeight: 600 },
}

const actorColor = (name: string, ctx: FigureContext) => ACTOR_COLORS[name] ?? ctx.accent

/** Which headers are actor names (for wide actor-matrix tables). */
const actorCols = (t: CsvTable) => t.headers.filter((h) => h in ACTOR_COLORS)

// ---------------------------------------------------------------- builders

/** Multi-actor monthly lines: (initiating_country, month, third). */
const actorMonthlyLines: Builder = {
  key: 'actor-monthly-lines',
  render: (t) => {
    const actors = [...new Set(t.rows.map((r) => str(r.initiating_country)))].sort()
    const byMonth = new Map<string, CsvRow>()
    for (const r of t.rows) {
      const m = str(r.month)
      if (!byMonth.has(m)) byMonth.set(m, { month: m })
      byMonth.get(m)![str(r.initiating_country)] = num(r.third)
    }
    const data = [...byMonth.values()].sort((a, b) => str(a.month).localeCompare(str(b.month)))
    return (
      <ResponsiveContainer width="100%" height={360}>
        <LineChart data={data} margin={{ top: 8, right: 24, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="#f1f5f9" />
          <XAxis dataKey="month" tickFormatter={monthTick} tick={{ fontSize: 11, fill: MUTED }} />
          <YAxis tick={{ fontSize: 11, fill: MUTED }} />
          <Tooltip {...tooltipStyle} labelFormatter={monthTick} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <ReferenceLine x="2024-12-01" stroke="#bbbbbb" strokeDasharray="4 3" />
          {actors.map((a) => (
            <Line key={a} type="monotone" dataKey={a} stroke={ACTOR_COLORS[a] ?? MUTED}
              strokeWidth={2} dot={false} activeDot={{ r: 5 }} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    )
  },
}

/** Generic time series: (month, <numeric cols>). */
const timeline: Builder = {
  key: 'timeline',
  render: (t, ctx) => {
    const series = t.headers.filter((h) => h !== 'month')
    const data = [...t.rows].sort((a, b) => str(a.month).localeCompare(str(b.month)))
    const colorFor = (s: string, i: number) =>
      s === 'raw' ? '#9ca3af' : i === 0 ? ctx.accent : ['#64748b', '#0e7490'][i % 2]
    return (
      <ResponsiveContainer width="100%" height={340}>
        <LineChart data={data} margin={{ top: 8, right: 24, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="#f1f5f9" />
          <XAxis dataKey="month" tickFormatter={monthTick} tick={{ fontSize: 11, fill: MUTED }} />
          <YAxis tick={{ fontSize: 11, fill: MUTED }} />
          <Tooltip {...tooltipStyle} labelFormatter={monthTick} />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {series.map((s, i) => (
            <Line key={s} type="monotone" dataKey={s} stroke={colorFor(s, i)}
              strokeWidth={2} strokeDasharray={s === 'raw' ? '5 4' : undefined}
              dot={false} activeDot={{ r: 5 }} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    )
  },
}

/** Theater provenance quadrant: (initiating_country, recipient, raw, corr_share). */
const quadrantMulti: Builder = {
  key: 'quadrant-multi',
  render: (t) => {
    const actors = [...new Set(t.rows.map((r) => str(r.initiating_country)))].sort()
    const ticks = logTicks(t.rows.map((r) => num(r.raw)))
    return (
      <ResponsiveContainer width="100%" height={430}>
        <ScatterChart margin={{ top: 8, right: 24, bottom: 34, left: 0 }}>
          <CartesianGrid stroke="#f1f5f9" />
          <XAxis type="number" dataKey="raw" name="raw docs" scale="log" domain={['auto', 'auto']}
            ticks={ticks} tickFormatter={compact} tick={{ fontSize: 11, fill: MUTED }}
            label={{ value: 'raw media volume (docs, log scale)', position: 'bottom', offset: 18, fontSize: 11, fill: MUTED }} />
          <YAxis type="number" dataKey="corr_share" name="corroborated share" domain={[0, 1]}
            tickFormatter={pctTick} tick={{ fontSize: 11, fill: MUTED }} />
          <ZAxis range={[70, 71]} />
          <ReferenceLine y={0.5} stroke="#bbbbbb" strokeDasharray="4 3" />
          <Tooltip {...tooltipStyle} cursor={{ strokeDasharray: '3 3' }}
            formatter={(value?: number | string, name?: string) =>
              name === 'corroborated share' ? pctTick(Number(value ?? 0)) : Number(value ?? 0).toLocaleString()}
            labelFormatter={() => ''}
            content={undefined} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {actors.map((a) => (
            <Scatter key={a} name={a}
              data={t.rows.filter((r) => str(r.initiating_country) === a)
                .map((r) => ({ ...r, label: `${a} → ${str(r.recipient)}` }))}
              fill={ACTOR_COLORS[a] ?? MUTED} fillOpacity={0.85} />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    )
  },
}

/** Single-actor quadrant: (recipient, raw, third_party_share). */
const quadrantSingle: Builder = {
  key: 'quadrant-single',
  render: (t, ctx) => (
    <ResponsiveContainer width="100%" height={390}>
      <ScatterChart margin={{ top: 8, right: 24, bottom: 34, left: 0 }}>
        <CartesianGrid stroke="#f1f5f9" />
        <XAxis type="number" dataKey="raw" name="raw docs" scale="log" domain={['auto', 'auto']}
          ticks={logTicks(t.rows.map((r) => num(r.raw)))} tickFormatter={compact}
          tick={{ fontSize: 11, fill: MUTED }}
          label={{ value: 'raw media volume (docs, log scale)', position: 'bottom', offset: 18, fontSize: 11, fill: MUTED }} />
        <YAxis type="number" dataKey="third_party_share" name="third-party share" domain={[0, 1]}
          tickFormatter={pctTick} tick={{ fontSize: 11, fill: MUTED }} />
        <ZAxis range={[70, 71]} />
        <ReferenceLine y={0.5} stroke="#bbbbbb" strokeDasharray="4 3" />
        <Tooltip {...tooltipStyle} cursor={{ strokeDasharray: '3 3' }}
          formatter={(value?: number | string, name?: string) =>
            name === 'third-party share' ? pctTick(Number(value ?? 0)) : Number(value ?? 0).toLocaleString()} />
        <Scatter name="recipient" data={t.rows.map((r) => ({ ...r, label: str(r.recipient) }))}
          fill={ctx.accent} fillOpacity={0.8} />
      </ScatterChart>
    </ResponsiveContainer>
  ),
}

/** Raw vs corroborated leaderboard: (actor|initiating_country|recipient, raw, third|corroborated). */
const leaderboard: Builder = {
  key: 'leaderboard',
  render: (t, ctx) => {
    const nameCol = ['actor', 'initiating_country', 'recipient'].find((c) => t.headers.includes(c))!
    const valCol = t.headers.includes('third') ? 'third' : 'corroborated'
    const data = [...t.rows].sort((a, b) => num(b[valCol]) - num(a[valCol]))
    const height = Math.max(220, data.length * 44 + 70)
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 40, bottom: 4, left: 30 }}>
          <CartesianGrid stroke="#f1f5f9" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 11, fill: MUTED }}
            tickFormatter={(v: number) => v.toLocaleString()} />
          <YAxis type="category" dataKey={nameCol} width={110} tick={{ fontSize: 12, fill: '#334155' }} />
          <Tooltip {...tooltipStyle}
            formatter={(value?: number | string) => Number(value ?? 0).toLocaleString()} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="raw" name="raw volume" fill={GRAY} barSize={12} radius={[0, 4, 4, 0]} />
          <Bar dataKey={valCol} name="third-party corroborated" fill={NAVY} barSize={12} radius={[0, 4, 4, 0]}>
            {data.map((r, i) => (
              <Cell key={i} fill={actorColor(str(r[nameCol]), ctx)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    )
  },
}

/** Initiative gate funnel: (actor, total, corroborated, high_material). */
const gate: Builder = {
  key: 'gate',
  render: (t, ctx) => (
    <ResponsiveContainer width="100%" height={340}>
      <BarChart data={t.rows} margin={{ top: 8, right: 24, bottom: 4, left: 0 }}>
        <CartesianGrid stroke="#f1f5f9" vertical={false} />
        <XAxis dataKey="actor" tick={{ fontSize: 12, fill: '#334155' }} />
        <YAxis tick={{ fontSize: 11, fill: MUTED }} tickFormatter={(v: number) => v.toLocaleString()} />
        <Tooltip {...tooltipStyle} formatter={(value?: number | string) => Number(value ?? 0).toLocaleString()} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="total" name="all extracted" fill={GRAY} radius={[4, 4, 0, 0]} />
        <Bar dataKey="corroborated" name="corroborated (≥50% 3rd-party, ≥3 outlets)" radius={[4, 4, 0, 0]}>
          {t.rows.map((r, i) => <Cell key={i} fill={actorColor(str(r.actor), ctx)} fillOpacity={0.5} />)}
        </Bar>
        <Bar dataKey="high_material" name="+ high-material (≥6)" radius={[4, 4, 0, 0]}>
          {t.rows.map((r, i) => <Cell key={i} fill={actorColor(str(r.actor), ctx)} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  ),
}

/** Category signature: (initiating_country, category, share). */
const categorySignature: Builder = {
  key: 'category-signature',
  render: (t) => {
    const actors = [...new Set(t.rows.map((r) => str(r.initiating_country)))].sort()
    const cats = ['Diplomacy', 'Economic', 'Social', 'Military']
    const data = cats.map((c) => {
      const row: CsvRow = { category: c }
      for (const a of actors) {
        const m = t.rows.find((r) => str(r.initiating_country) === a && str(r.category) === c)
        row[a] = m ? Math.round(num(m.share) * 1000) / 10 : 0
      }
      return row
    })
    return (
      <ResponsiveContainer width="100%" height={360}>
        <BarChart data={data} margin={{ top: 8, right: 24, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="#f1f5f9" vertical={false} />
          <XAxis dataKey="category" tick={{ fontSize: 12, fill: '#334155' }} />
          <YAxis unit="%" tick={{ fontSize: 11, fill: MUTED }} />
          <Tooltip {...tooltipStyle} formatter={(value?: number | string) => `${value ?? 0}%`} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {actors.map((a) => (
            <Bar key={a} dataKey={a} fill={ACTOR_COLORS[a] ?? MUTED} radius={[4, 4, 0, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    )
  },
}

/** Wide actor matrix: (first categorical col, China, Iran, ... ) -> grouped bars. */
const actorMatrix: Builder = {
  key: 'actor-matrix',
  render: (t) => {
    const acts = actorCols(t)
    const nameCol = t.headers.find((h) => !(h in ACTOR_COLORS))!
    const height = Math.max(260, t.rows.length * (acts.length * 13 + 14) + 80)
    return (
      <ResponsiveContainer width="100%" height={Math.min(height, 620)}>
        <BarChart data={t.rows} layout="vertical" margin={{ top: 8, right: 32, bottom: 4, left: 40 }}>
          <CartesianGrid stroke="#f1f5f9" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 11, fill: MUTED }}
            tickFormatter={(v: number) => v.toLocaleString()} />
          <YAxis type="category" dataKey={nameCol} width={130}
            tick={{ fontSize: 11, fill: '#334155' }} />
          <Tooltip {...tooltipStyle} formatter={(value?: number | string) => Number(value ?? 0).toLocaleString()} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {acts.map((a) => (
            <Bar key={a} dataKey={a} fill={ACTOR_COLORS[a]} barSize={10} radius={[0, 3, 3, 0]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    )
  },
}

/** Category radar: (category, share, avg_share). */
const radar: Builder = {
  key: 'radar',
  render: (t, ctx) => {
    // shares may be stored as 0–1 fractions or 0–100 percents; adapt
    const maxV = Math.max(...t.rows.map((r) => Math.max(num(r.share), num(r.avg_share))))
    const fmt = (v: number) => (maxV > 1.5 ? `${Math.round(v)}%` : pctTick(v))
    return (
      <ResponsiveContainer width="100%" height={360}>
        <RadarChart data={t.rows} margin={{ top: 12, right: 30, bottom: 4, left: 30 }}>
          <PolarGrid stroke="#e2e8f0" />
          <PolarAngleAxis dataKey="category" tick={{ fontSize: 12, fill: '#334155' }} />
          <PolarRadiusAxis tick={false} axisLine={false} />
          <Radar name="this actor" dataKey="share" stroke={ctx.accent} fill={ctx.accent} fillOpacity={0.35} />
          <Radar name="all-actor average" dataKey="avg_share" stroke="#94a3b8" fill="#94a3b8" fillOpacity={0.15} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Tooltip {...tooltipStyle} formatter={(value?: number | string) => fmt(Number(value ?? 0))} />
        </RadarChart>
      </ResponsiveContainer>
    )
  },
}

/** Two-column simple bar: (name, value). */
const simpleBar: Builder = {
  key: 'simple-bar',
  render: (t, ctx) => {
    const [nameCol, valCol] = t.headers
    const data = [...t.rows].sort((a, b) => num(b[valCol]) - num(a[valCol])).slice(0, 20)
    const height = Math.max(220, data.length * 26 + 60)
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 40, bottom: 4, left: 60 }}>
          <CartesianGrid stroke="#f1f5f9" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 11, fill: MUTED }}
            tickFormatter={(v: number) => v.toLocaleString()} />
          <YAxis type="category" dataKey={nameCol} width={150}
            tick={{ fontSize: 11, fill: '#334155' }}
            tickFormatter={(v: string) => truncate(String(v), 24)} />
          <Tooltip {...tooltipStyle} formatter={(value?: number | string) => Number(value ?? 0).toLocaleString()} />
          <Bar dataKey={valCol} barSize={14} radius={[0, 4, 4, 0]}>
            {data.map((r, i) => (
              <Cell key={i} fill={ACTOR_COLORS[str(r[nameCol])] ?? ctx.accent} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    )
  },
}

/** Initiative/megadeal bars: (canonical_name|event_name, material_score, [actor cols...]).
 *  Clickable: each bar drills into the event's source documents. */
const initiativeBars: Builder = {
  key: 'initiative-bars',
  render: (t, ctx) => {
    const nameCol = t.headers.includes('canonical_name') ? 'canonical_name' : 'event_name'
    const actorCol = ['initiating_country', 'actor'].find((c) => t.headers.includes(c))
    const data = [...t.rows]
      .sort((a, b) => num(b.material_score) - num(a.material_score))
      .slice(0, 20)
    const height = Math.max(260, data.length * 30 + 60)
    const drill = (r: CsvRow) => ctx.onDrill?.({
      name: str(r[nameCol]),
      actor: actorCol ? str(r[actorCol]) : undefined,
    })
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 30, bottom: 4, left: 10 }}>
          <CartesianGrid stroke="#f1f5f9" horizontal={false} />
          <XAxis type="number" domain={[0, 10]} tick={{ fontSize: 11, fill: MUTED }}
            label={{ value: 'material score (1–10)', position: 'insideBottom', offset: -2, fontSize: 11, fill: MUTED }} />
          <YAxis type="category" dataKey={nameCol} width={300}
            tick={{ fontSize: 10.5, fill: '#334155' }}
            tickFormatter={(v: string) => truncate(String(v), 46)} />
          <Tooltip {...tooltipStyle}
            formatter={(value?: number | string) => value ?? ''}
            labelFormatter={(label: string) => `${label} — click bar for sources`} />
          <Bar dataKey="material_score" barSize={16} radius={[0, 4, 4, 0]}
            cursor={ctx.onDrill ? 'pointer' : undefined}
            onClick={(entry: { payload?: CsvRow }) => entry?.payload && drill(entry.payload)}>
            {data.map((r, i) => (
              <Cell key={i} fill={actorCol ? actorColor(str(r[actorCol]), ctx) : ctx.accent} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    )
  },
}

/** Narrative themes: (label, dominant, n_events, n_recipients, coherence). */
const themes: Builder = {
  key: 'themes',
  render: (t, ctx) => {
    const data = [...t.rows].sort((a, b) => num(b.n_recipients) - num(a.n_recipients))
    const height = Math.max(260, data.length * 30 + 60)
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 40, bottom: 4, left: 10 }}>
          <CartesianGrid stroke="#f1f5f9" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 11, fill: MUTED }}
            label={{ value: 'distinct MENA recipients touched', position: 'insideBottom', offset: -2, fontSize: 11, fill: MUTED }} />
          <YAxis type="category" dataKey="label" width={260}
            tick={{ fontSize: 10.5, fill: '#334155' }}
            tickFormatter={(v: string) => truncate(String(v), 40)} />
          <Tooltip {...tooltipStyle} />
          <Bar dataKey="n_recipients" barSize={16} radius={[0, 4, 4, 0]}>
            {data.map((r, i) => (
              <Cell key={i} fill={actorColor(str(r.dominant), ctx)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    )
  },
}

// ---------------------------------------------------------------- selection

/** Filenames whose shapes recharts can't honestly reproduce — keep the PNG. */
const PNG_ONLY = /heatmap|geo|network|lorenz|tempo|changepoint/i

export function pickBuilder(filename: string, t: CsvTable): Builder | null {
  if (PNG_ONLY.test(filename) || t.rows.length === 0) return null

  if (has(t, 'initiating_country', 'month', 'third')) return actorMonthlyLines
  if (has(t, 'initiating_country', 'recipient', 'raw', 'corr_share')) return quadrantMulti
  if (has(t, 'recipient', 'raw', 'third_party_share')) return quadrantSingle
  if (has(t, 'actor', 'total', 'corroborated', 'high_material')) return gate
  if (has(t, 'initiating_country', 'category', 'share')) return categorySignature
  if (has(t, 'category', 'share', 'avg_share')) return radar
  if (has(t, 'label', 'dominant', 'n_events', 'n_recipients')) return themes
  if (has(t, 'material_score') && (has(t, 'canonical_name') || has(t, 'event_name'))) return initiativeBars
  if (has(t, 'raw') && (has(t, 'third') || has(t, 'corroborated'))
      && ['actor', 'initiating_country', 'recipient'].some((c) => t.headers.includes(c))) return leaderboard
  if (has(t, 'month')) return timeline
  if (actorCols(t).length >= 2 && t.headers.length - actorCols(t).length === 1
      && t.rows.length <= 12) return actorMatrix
  if (t.headers.length === 2 && t.rows.length > 0
      && typeof t.rows[0][t.headers[0]] === 'string'
      && typeof t.rows[0][t.headers[1]] === 'number') return simpleBar

  return null
}
