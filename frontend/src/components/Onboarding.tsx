import { useState } from 'react'
import type { FormEvent } from 'react'
import type { Source } from '../api'
import { registerSource } from '../api'
import { ErrorState } from './ErrorState'

interface OnboardingProps {
  onRegistered: (source: Source, apiKey: string) => void
}

export function Onboarding({ onRegistered }: OnboardingProps) {
  const [name, setName] = useState('')
  const [domain, setDomain] = useState('')
  const [feedUrl, setFeedUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      // No dedicated stable_id field in this form (spec §3.1) - the
      // normalized domain is already a unique-ish slug, so it doubles as
      // the source's stable_id.
      const source = await registerSource(apiKey, {
        stable_id: domain,
        name,
        normalized_domain: domain,
        feeds: feedUrl.trim() === '' ? [] : [{ feed_url: feedUrl.trim() }],
      })
      localStorage.setItem('ae_api_key', apiKey)
      onRegistered(source, apiKey)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto max-w-md p-6">
      <h2 className="mb-1 text-lg font-semibold text-slate-900">Set up your first source</h2>
      <p className="mb-4 text-sm text-slate-500">
        AnalystEngine needs at least one source before it can ingest content.
      </p>

      <form onSubmit={(event) => void handleSubmit(event)} className="space-y-4">
        <div>
          <label htmlFor="onboarding-name" className="mb-1 block text-sm font-medium text-slate-700">
            Source name
          </label>
          <input
            id="onboarding-name"
            type="text"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label htmlFor="onboarding-domain" className="mb-1 block text-sm font-medium text-slate-700">
            Normalized domain
          </label>
          <input
            id="onboarding-domain"
            type="text"
            required
            placeholder="example.com"
            value={domain}
            onChange={(event) => setDomain(event.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label htmlFor="onboarding-feed" className="mb-1 block text-sm font-medium text-slate-700">
            Feed URL (optional)
          </label>
          <input
            id="onboarding-feed"
            type="text"
            value={feedUrl}
            onChange={(event) => setFeedUrl(event.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label htmlFor="onboarding-api-key" className="mb-1 block text-sm font-medium text-slate-700">
            API key
          </label>
          <input
            id="onboarding-api-key"
            type="password"
            required
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          />
        </div>

        {error !== null && <ErrorState message={error} />}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {submitting ? 'Registering...' : 'Register source'}
        </button>
      </form>
    </div>
  )
}
