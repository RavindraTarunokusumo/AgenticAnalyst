import type { IngestionAttempt } from '../api'
import { EmptyState } from './EmptyState'
import { ErrorState } from './ErrorState'
import { LoadingState } from './LoadingState'

interface RecentActivityListProps {
  attempts: IngestionAttempt[] | null
  loading: boolean
  error: string | null
}

export function RecentActivityList({ attempts, loading, error }: RecentActivityListProps) {
  if (loading) {
    return <LoadingState label="Loading recent activity..." />
  }
  if (error !== null) {
    return <ErrorState message={error} />
  }
  if (attempts === null || attempts.length === 0) {
    return <EmptyState message="No ingestion attempts yet." />
  }

  return (
    <ul className="divide-y divide-slate-100">
      {attempts.map((attempt) => (
        <li key={attempt.id} className="px-3 py-2 text-sm">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-slate-900">{attempt.requested_url}</span>
            <span className="shrink-0 text-xs uppercase text-slate-500">{attempt.status}</span>
          </div>
          {attempt.error_summary !== null && (
            <p className="mt-1 text-xs text-red-600">{attempt.error_summary}</p>
          )}
          <p className="mt-1 text-xs text-slate-400">{new Date(attempt.started_at).toLocaleString()}</p>
        </li>
      ))}
    </ul>
  )
}
