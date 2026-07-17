import { useState } from 'react'
import type { KeyboardEvent } from 'react'

interface KeywordChipsProps {
  keywords: string[]
  onChange: (next: string[]) => void
}

export function KeywordChips({ keywords, onChange }: KeywordChipsProps) {
  const [draft, setDraft] = useState('')

  function addKeyword() {
    const trimmed = draft.trim()
    if (trimmed === '') {
      return
    }
    if (keywords.some((keyword) => keyword.toLowerCase() === trimmed.toLowerCase())) {
      setDraft('')
      return
    }
    onChange([...keywords, trimmed])
    setDraft('')
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') {
      event.preventDefault()
      addKeyword()
    }
  }

  function removeKeyword(index: number) {
    onChange(keywords.filter((_, i) => i !== index))
  }

  return (
    <div className="space-y-3">
      {keywords.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {keywords.map((keyword, index) => (
            <li
              key={`${keyword}-${index}`}
              className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-sm text-slate-800"
            >
              <span>{keyword}</span>
              <button
                type="button"
                onClick={() => removeKeyword(index)}
                aria-label={`Remove ${keyword}`}
                className="rounded-full px-1 text-slate-500 hover:bg-slate-200 hover:text-slate-800"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex gap-2">
        <input
          type="text"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Add a keyword"
          className="min-w-0 flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={addKeyword}
          className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          disabled={draft.trim() === ''}
        >
          Add
        </button>
      </div>
    </div>
  )
}
