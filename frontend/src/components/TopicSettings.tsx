import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { Source, Topic } from '../api'
import {
  fetchTopicSources,
  registerSource,
  suggestKeywords,
  updateTopic,
} from '../api'
import { ErrorState } from './ErrorState'
import { KeywordChips } from './KeywordChips'
import { LoadingState } from './LoadingState'

interface TopicSettingsProps {
  topic: Topic
  apiKey: string | null
  onSaved: (topic: Topic) => void
}

export function TopicSettings({ topic, apiKey, onSaved }: TopicSettingsProps) {
  const [sources, setSources] = useState<Source[] | null>(null)
  const [sourcesLoading, setSourcesLoading] = useState(true)
  const [sourcesError, setSourcesError] = useState<string | null>(null)

  const [sourceName, setSourceName] = useState('')
  const [domain, setDomain] = useState('')
  const [feedUrl, setFeedUrl] = useState('')
  const [addingSource, setAddingSource] = useState(false)

  const [keywords, setKeywords] = useState<string[]>(topic.keywords)
  const [suggesting, setSuggesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [assistNotice, setAssistNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setKeywords(topic.keywords)
  }, [topic.id, topic.keywords])

  useEffect(() => {
    let cancelled = false
    setSourcesLoading(true)
    setSourcesError(null)
    void fetchTopicSources(topic.id)
      .then((next) => {
        if (!cancelled) {
          setSources(next)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setSourcesError(err instanceof Error ? err.message : String(err))
          setSources(null)
        }
      })
      .finally(() => {
        if (!cancelled) {
          setSourcesLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [topic.id])

  async function handleAddSource(event: FormEvent) {
    event.preventDefault()
    if (apiKey === null) {
      return
    }
    const trimmedDomain = domain.trim()
    if (trimmedDomain === '') {
      return
    }

    setAddingSource(true)
    setError(null)
    try {
      const trimmedFeed = feedUrl.trim()
      await registerSource(apiKey, {
        topic_id: topic.id,
        stable_id: trimmedDomain,
        name: sourceName.trim() || trimmedDomain,
        normalized_domain: trimmedDomain,
        feeds: trimmedFeed !== '' ? [{ feed_url: trimmedFeed }] : [],
      })
      setSourceName('')
      setDomain('')
      setFeedUrl('')
      setSourcesLoading(true)
      setSourcesError(null)
      try {
        setSources(await fetchTopicSources(topic.id))
      } catch (err) {
        setSourcesError(err instanceof Error ? err.message : String(err))
        setSources(null)
      } finally {
        setSourcesLoading(false)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setAddingSource(false)
    }
  }

  async function handleReSuggest() {
    setSuggesting(true)
    setAssistNotice(null)
    setError(null)
    try {
      const suggested = await suggestKeywords(
        topic.name,
        topic.description,
        topic.interest_detail ? [topic.interest_detail] : [],
      )
      setKeywords(suggested)
    } catch {
      setAssistNotice('Re-suggestion unavailable — edit keywords manually')
    } finally {
      setSuggesting(false)
    }
  }

  async function handleSaveKeywords() {
    if (apiKey === null || keywords.length === 0) {
      return
    }

    setSaving(true)
    setError(null)
    try {
      const updated = await updateTopic(apiKey, topic.id, {
        name: topic.name,
        description: topic.description,
        interest_detail: topic.interest_detail,
        keywords,
      })
      onSaved(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-8 p-4">
      <div>
        <h2 className="mb-1 text-lg font-semibold text-slate-900">Topic settings</h2>
        <p className="text-sm text-slate-500">{topic.name}</p>
      </div>

      {error !== null && <ErrorState message={error} />}

      <section className="space-y-4">
        <h3 className="text-sm font-semibold text-slate-900">Sources</h3>
        <p className="text-sm text-slate-600">
          Sources and feeds this topic follows. Add more at any time.
        </p>

        {sourcesLoading && <LoadingState label="Loading sources..." />}
        {!sourcesLoading && sourcesError !== null && <ErrorState message={sourcesError} />}
        {!sourcesLoading && sourcesError === null && sources !== null && sources.length === 0 && (
          <p className="text-sm text-slate-500">No sources yet.</p>
        )}
        {!sourcesLoading && sourcesError === null && sources !== null && sources.length > 0 && (
          <ul className="divide-y divide-slate-100 rounded-md border border-slate-200">
            {sources.map((source) => (
              <li key={source.id} className="px-3 py-3">
                <div className="text-sm font-medium text-slate-900">{source.name}</div>
                <div className="text-xs text-slate-500">{source.normalized_domain}</div>
                {source.feeds.length > 0 && (
                  <ul className="mt-1 space-y-0.5">
                    {source.feeds.map((feed) => (
                      <li key={feed.id} className="truncate text-xs text-slate-400">
                        {feed.feed_url}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}

        {apiKey === null ? (
          <p className="text-sm text-slate-500">Set an API key to edit sources.</p>
        ) : (
          <form onSubmit={(event) => void handleAddSource(event)} className="space-y-3">
            <div>
              <label
                htmlFor="settings-source-name"
                className="mb-1 block text-sm font-medium text-slate-700"
              >
                Source name
              </label>
              <input
                id="settings-source-name"
                type="text"
                value={sourceName}
                onChange={(event) => setSourceName(event.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label
                htmlFor="settings-source-domain"
                className="mb-1 block text-sm font-medium text-slate-700"
              >
                Normalized domain
              </label>
              <input
                id="settings-source-domain"
                type="text"
                required
                placeholder="example.com"
                value={domain}
                onChange={(event) => setDomain(event.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label
                htmlFor="settings-source-feed"
                className="mb-1 block text-sm font-medium text-slate-700"
              >
                Feed URL (optional)
              </label>
              <input
                id="settings-source-feed"
                type="text"
                value={feedUrl}
                onChange={(event) => setFeedUrl(event.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
            <button
              type="submit"
              disabled={addingSource || domain.trim() === ''}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {addingSource ? 'Adding...' : 'Add source'}
            </button>
          </form>
        )}
      </section>

      <section className="space-y-4">
        <h3 className="text-sm font-semibold text-slate-900">Keywords</h3>
        <p className="text-sm text-slate-600">
          Keywords are matched against incoming content. Re-suggest uses the
          retained interest detail from onboarding.
        </p>

        {assistNotice !== null && (
          <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            {assistNotice}
          </p>
        )}

        <KeywordChips keywords={keywords} onChange={setKeywords} />

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void handleReSuggest()}
            disabled={suggesting}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-50"
          >
            {suggesting ? 'Re-suggesting...' : 'Re-suggest keywords'}
          </button>

          {apiKey === null ? (
            <p className="self-center text-sm text-slate-500">
              Set an API key to save keywords.
            </p>
          ) : (
            <button
              type="button"
              onClick={() => void handleSaveKeywords()}
              disabled={saving || keywords.length === 0}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {saving ? 'Saving...' : 'Save keywords'}
            </button>
          )}
        </div>
      </section>
    </div>
  )
}
