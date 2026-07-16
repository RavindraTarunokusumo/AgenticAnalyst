import { useState } from 'react'
import type { FormEvent } from 'react'

interface ApiKeySettingsProps {
  apiKey: string | null
  onSave: (key: string) => void
}

export function ApiKeySettings({ apiKey, onSave }: ApiKeySettingsProps) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(apiKey ?? '')

  function handleOpen() {
    setDraft(apiKey ?? '')
    setOpen(true)
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    onSave(draft)
    setOpen(false)
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={handleOpen}
        className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
      >
        API key
      </button>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-2">
      <input
        type="password"
        aria-label="API key"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
      />
      <button
        type="submit"
        className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white"
      >
        Save
      </button>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="rounded-md px-3 py-1.5 text-sm text-slate-500 hover:text-slate-700"
      >
        Cancel
      </button>
    </form>
  )
}
