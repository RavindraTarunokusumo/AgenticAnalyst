import type { BriefListItem } from '../api'
import { EmptyState } from './EmptyState'
import { ErrorState } from './ErrorState'
import { LoadingState } from './LoadingState'

interface BriefListProps {
  items: BriefListItem[] | null
  loading: boolean
  error: string | null
  selectedId: string | null
  onSelect: (id: string) => void
}

export function BriefList({ items, loading, error, selectedId, onSelect }: BriefListProps) {
  if (loading) {
    return <LoadingState label="Loading briefs..." />
  }
  if (error !== null) {
    return <ErrorState message={error} />
  }
  if (items === null || items.length === 0) {
    return <EmptyState message="No briefs yet for this cadence." />
  }

  return (
    <ul className="divide-y divide-slate-100">
      {items.map((item) => {
        const isSelected = item.id === selectedId
        return (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onSelect(item.id)}
              className={
                isSelected
                  ? 'w-full px-4 py-3 text-left bg-slate-100'
                  : 'w-full px-4 py-3 text-left hover:bg-slate-50'
              }
            >
              <div className="text-sm font-medium text-slate-900">
                {item.covered_start} to {item.covered_end}
              </div>
              <div className="text-xs text-slate-400">
                Created {new Date(item.created_at).toLocaleString()}
              </div>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
