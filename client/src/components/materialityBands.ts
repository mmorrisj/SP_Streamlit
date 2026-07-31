/**
 * Canonical materiality bands — client mirror of shared/utils/materiality_bands.py.
 *
 * Materiality is a 1.0-10.0 significance scale. Symbolic activity is a real
 * soft-power signal (narrative projection, signaling), so the UI gives each
 * band its own identity instead of treating low scores as "less important".
 */

export type MaterialityBand = 'symbolic' | 'developing' | 'substantive'

export const SYMBOLIC_MAX = 4.0
export const DEVELOPING_MAX = 7.0

export function bandFor(score: number | null | undefined): MaterialityBand | null {
  if (score == null) return null
  if (score < SYMBOLIC_MAX) return 'symbolic'
  if (score < DEVELOPING_MAX) return 'developing'
  return 'substantive'
}

export const BAND_LABELS: Record<MaterialityBand, string> = {
  symbolic: 'Symbolic',
  developing: 'Developing',
  substantive: 'Substantive',
}

// Badge colors: substantive = green, developing = amber, symbolic = blue.
// Blue (not gray) on purpose — symbolic gestures are signal, not noise.
export const BAND_BADGE: Record<MaterialityBand, { bg: string; fg: string }> = {
  symbolic: { bg: '#dbeafe', fg: '#1e40af' },
  developing: { bg: '#fef3c7', fg: '#92400e' },
  substantive: { bg: '#dcfce7', fg: '#166534' },
}

// Chart series colors per band (solid, chart-friendly)
export const BAND_COLORS: Record<MaterialityBand, string> = {
  symbolic: '#3b82f6',
  developing: '#f59e0b',
  substantive: '#16a34a',
}

export function badgeStyleFor(score: number | null | undefined): { backgroundColor: string; color: string } {
  const band = bandFor(score)
  if (!band) return { backgroundColor: '#f1f5f9', color: '#475569' }
  return { backgroundColor: BAND_BADGE[band].bg, color: BAND_BADGE[band].fg }
}
