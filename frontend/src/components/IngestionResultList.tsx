import type { IngestionResult } from '../api'

const STATUS_STYLES: Record<string, string> = {
  success: 'bg-green-50 text-green-700',
  duplicate: 'bg-amber-50 text-amber-700',
  failed: 'bg-red-50 text-red-700',
}

interface IngestionResultListProps {
  results: IngestionResult[]
  // Uploaded files come back as the synthetic `upload://<hash>` candidate_url
  // (spec §4.1) - this maps that url to the filename the panel already had
  // in local state, purely for display (no new backend field).
  displayNames?: Record<string, string>
}

export function IngestionResultList({ results, displayNames }: IngestionResultListProps) {
  if (results.length === 0) {
    return null
  }

  return (
    <ul className="mt-3 space-y-2">
      {results.map((result, index) => {
        const label = displayNames?.[result.candidate_url] ?? result.candidate_url
        const style = STATUS_STYLES[result.status] ?? 'bg-slate-50 text-slate-700'
        return (
          <li key={`${result.candidate_url}-${index}`} className={`rounded-md px-3 py-2 text-sm ${style}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="truncate">{label}</span>
              <span className="shrink-0 text-xs font-medium uppercase">{result.status}</span>
            </div>
            {result.error_summary !== null && <p className="mt-1 text-xs">{result.error_summary}</p>}
          </li>
        )
      })}
    </ul>
  )
}
