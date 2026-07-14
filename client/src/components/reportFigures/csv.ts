// Minimal quote-aware CSV parser for report figure sidecar files.

export type CsvRow = Record<string, string | number>

export interface CsvTable {
  headers: string[]
  rows: CsvRow[]
}

export function parseCsv(text: string): CsvTable {
  const lines: string[][] = []
  let field = ''
  let record: string[] = []
  let inQuotes = false

  const pushField = () => { record.push(field); field = '' }
  const pushRecord = () => {
    if (record.length > 1 || record[0] !== '') lines.push(record)
    record = []
  }

  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++ } else { inQuotes = false }
      } else {
        field += c
      }
    } else if (c === '"') {
      inQuotes = true
    } else if (c === ',') {
      pushField()
    } else if (c === '\n') {
      pushField(); pushRecord()
    } else if (c !== '\r') {
      field += c
    }
  }
  if (field !== '' || record.length) { pushField(); pushRecord() }

  if (lines.length === 0) return { headers: [], rows: [] }
  const headers = lines[0]
  const rows = lines.slice(1).map((cells) => {
    const row: CsvRow = {}
    headers.forEach((h, i) => {
      const v = cells[i] ?? ''
      const n = v === '' ? NaN : Number(v)
      row[h] = Number.isNaN(n) ? v : n
    })
    return row
  })
  return { headers, rows }
}
