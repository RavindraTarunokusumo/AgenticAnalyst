import { useState } from 'react'
import type { FormEvent } from 'react'
import type { IngestionResult, Source } from '../api'
import { ingestFile, ingestUrls, registerSource } from '../api'
import { ErrorState } from './ErrorState'
import { IngestionResultList } from './IngestionResultList'

type Mode = 'links' | 'feed' | 'file'

// Plan's Task 9 interface names this prop `sourceId`, but the "add feed"
// mode needs stable_id/name/normalized_domain too (POST /sources requires
// all three even when re-registering an existing source - see
// upsert_source, api/app.py:371) - the full Source is passed instead of
// just its id.
interface AddContentPanelProps {
  apiKey: string
  source: Source
  onSubmitted: () => void
}

function parseUrls(raw: string): string[] {
  return raw
    .split(/[\n,]/)
    .map((entry) => entry.trim())
    .filter((entry) => entry !== '')
}

// A wrong/expired key never reaches IngestionService (spec §7) - _require_key
// rejects with 401/403 and no IngestionResultResponse body, so this is
// distinguished from a per-item ingestion failure by message content alone.
function isAuthError(message: string): boolean {
  return /\b401\b|\b403\b|api key/i.test(message)
}

export function AddContentPanel({ apiKey, source, onSubmitted }: AddContentPanelProps) {
  const [mode, setMode] = useState<Mode>('links')
  const [linksInput, setLinksInput] = useState('')
  const [feedUrlInput, setFeedUrlInput] = useState('')
  const [file, setFile] = useState<File | null>(null)

  const [submitting, setSubmitting] = useState(false)
  const [panelError, setPanelError] = useState<string | null>(null)
  const [results, setResults] = useState<IngestionResult[]>([])
  const [displayNames, setDisplayNames] = useState<Record<string, string>>({})
  const [feedMessage, setFeedMessage] = useState<string | null>(null)

  function handleModeChange(next: Mode) {
    setMode(next)
    setPanelError(null)
    setResults([])
    setFeedMessage(null)
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (mode === 'file' && file === null) {
      setPanelError('Choose a file to upload.')
      return
    }
    const urls = mode === 'links' ? parseUrls(linksInput) : []
    if (mode === 'links' && urls.length === 0) {
      setPanelError('Enter at least one URL.')
      return
    }

    setPanelError(null)
    setResults([])
    setFeedMessage(null)
    setSubmitting(true)
    try {
      if (mode === 'links') {
        setResults(await ingestUrls(apiKey, source.id, urls))
      } else if (mode === 'feed') {
        const updated = await registerSource(apiKey, {
          stable_id: source.stable_id,
          name: source.name,
          normalized_domain: source.normalized_domain,
          feeds: [{ feed_url: feedUrlInput.trim() }],
        })
        setFeedMessage(`Feed registered on ${updated.name}.`)
      } else if (file !== null) {
        const result = await ingestFile(apiKey, source.id, file)
        setResults([result])
        setDisplayNames({ [result.candidate_url]: file.name })
      }
      onSubmitted()
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setPanelError(isAuthError(message) ? 'Check your API key.' : message)
      onSubmitted()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <div className="flex gap-1 border-b border-slate-200" role="tablist">
        {(
          [
            ['links', 'Paste link(s)'],
            ['feed', 'Add feed'],
            ['file', 'Upload file'],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={mode === value}
            onClick={() => handleModeChange(value)}
            className={
              mode === value
                ? 'border-b-2 border-slate-900 px-3 py-2 text-sm font-medium text-slate-900'
                : 'border-b-2 border-transparent px-3 py-2 text-sm font-medium text-slate-500 hover:text-slate-700'
            }
          >
            {label}
          </button>
        ))}
      </div>

      <form onSubmit={(event) => void handleSubmit(event)} className="mt-3 space-y-3">
        {mode === 'links' && (
          <textarea
            required
            rows={4}
            placeholder="https://example.com/article-1, https://example.com/article-2"
            value={linksInput}
            onChange={(event) => setLinksInput(event.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        )}

        {mode === 'feed' && (
          <input
            type="text"
            required
            placeholder="https://example.com/feed.xml"
            value={feedUrlInput}
            onChange={(event) => setFeedUrlInput(event.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        )}

        {mode === 'file' && (
          <input
            type="file"
            accept=".pdf,.txt,application/pdf,text/plain"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            className="w-full text-sm"
          />
        )}

        <button
          type="submit"
          disabled={submitting}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {submitting ? 'Submitting...' : 'Submit'}
        </button>
      </form>

      {panelError !== null && <ErrorState message={panelError} />}
      {feedMessage !== null && (
        <p className="mt-3 rounded-md bg-green-50 px-3 py-2 text-sm text-green-700">{feedMessage}</p>
      )}
      <IngestionResultList results={results} displayNames={displayNames} />
    </div>
  )
}
