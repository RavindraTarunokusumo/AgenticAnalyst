import type { Cadence } from '../api'

const CADENCES: Cadence[] = ['daily', 'weekly', 'monthly']

interface CadenceTabsProps {
  active: Cadence
  onChange: (cadence: Cadence) => void
}

export function CadenceTabs({ active, onChange }: CadenceTabsProps) {
  return (
    <div className="flex gap-1 border-b border-slate-200" role="tablist">
      {CADENCES.map((cadence) => {
        const isActive = cadence === active
        return (
          <button
            key={cadence}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(cadence)}
            className={
              isActive
                ? 'border-b-2 border-slate-900 px-4 py-2 text-sm font-medium capitalize text-slate-900'
                : 'border-b-2 border-transparent px-4 py-2 text-sm font-medium capitalize text-slate-500 hover:text-slate-700'
            }
          >
            {cadence}
          </button>
        )
      })}
    </div>
  )
}
