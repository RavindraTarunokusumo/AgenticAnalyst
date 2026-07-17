import { useState } from 'react'
import type { FormEvent } from 'react'
import type { Topic } from '../api'
import { clarifyTopic, createTopic, registerSource, suggestKeywords } from '../api'
import { ErrorState } from './ErrorState'
import { KeywordChips } from './KeywordChips'
import { LoadingState } from './LoadingState'

interface TopicOnboardingProps {
  apiKey: string | null
  onApiKeyChange: (key: string) => void
  onCreated: (topic: Topic, apiKey: string) => void
}

type Step = 1 | 2 | 3 | 4

export function TopicOnboarding({
  apiKey,
  onApiKeyChange,
  onCreated,
}: TopicOnboardingProps) {
  const [step, setStep] = useState<Step>(1)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  const [questions, setQuestions] = useState<string[]>([])
  const [answers, setAnswers] = useState<string[]>([])
  const [clarifyAvailable, setClarifyAvailable] = useState(true)

  const [keywords, setKeywords] = useState<string[]>([])

  const [sourceName, setSourceName] = useState('')
  const [domain, setDomain] = useState('')
  const [feedUrl, setFeedUrl] = useState('')
  const [localApiKey, setLocalApiKey] = useState('')

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [assistNotice, setAssistNotice] = useState<string | null>(null)

  function goBack() {
    setError(null)
    if (step === 2) {
      setStep(1)
    } else if (step === 3) {
      setStep(clarifyAvailable && questions.length > 0 ? 2 : 1)
    } else if (step === 4) {
      setStep(3)
    }
  }

  async function handleInterestNext(event: FormEvent) {
    event.preventDefault()
    setLoading(true)
    setError(null)
    setAssistNotice(null)
    try {
      const nextQuestions = await clarifyTopic(name.trim(), description.trim())
      setQuestions(nextQuestions)
      setAnswers(nextQuestions.map(() => ''))
      setClarifyAvailable(true)
      setStep(2)
    } catch {
      setClarifyAvailable(false)
      setQuestions([])
      setAnswers([])
      setKeywords([])
      setAssistNotice('Suggestions unavailable — you can add keywords yourself')
      setStep(3)
    } finally {
      setLoading(false)
    }
  }

  async function handleSuggestKeywords(event: FormEvent) {
    event.preventDefault()
    setLoading(true)
    setError(null)
    setAssistNotice(null)
    try {
      const suggested = await suggestKeywords(
        name.trim(),
        description.trim(),
        answers,
      )
      setKeywords(suggested)
      setStep(3)
    } catch {
      setKeywords([])
      setAssistNotice('Suggestions unavailable — you can add keywords yourself')
      setStep(3)
    } finally {
      setLoading(false)
    }
  }

  function handleKeywordsNext(event: FormEvent) {
    event.preventDefault()
    if (keywords.length === 0) {
      return
    }
    setError(null)
    setStep(4)
  }

  function buildInterestDetail(): string | null {
    if (!clarifyAvailable || questions.length === 0) {
      return null
    }
    return questions
      .map((question, index) => `Q: ${question}\nA: ${answers[index] ?? ''}`)
      .join('\n')
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    if (keywords.length === 0) {
      return
    }

    const key = apiKey ?? localApiKey.trim()
    if (key === '') {
      setError('API key is required.')
      return
    }

    setLoading(true)
    setError(null)
    try {
      const interest_detail = buildInterestDetail()
      const topic = await createTopic(key, {
        name: name.trim(),
        description: description.trim(),
        interest_detail,
        keywords,
      })

      const trimmedDomain = domain.trim()
      if (trimmedDomain !== '') {
        const trimmedFeed = feedUrl.trim()
        await registerSource(key, {
          topic_id: topic.id,
          stable_id: trimmedDomain,
          name: sourceName.trim() || trimmedDomain,
          normalized_domain: trimmedDomain,
          feeds: trimmedFeed !== '' ? [{ feed_url: trimmedFeed }] : [],
        })
      }

      localStorage.setItem('ae_api_key', key)
      onApiKeyChange(key)
      onCreated(topic, key)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-md p-6">
      <h2 className="mb-1 text-lg font-semibold text-slate-900">Create a topic</h2>
      <p className="mb-4 text-sm text-slate-500">
        Topics are what AnalystEngine follows. Set up interest, keywords, and an optional first source.
      </p>

      <p className="mb-4 text-xs font-medium uppercase tracking-wide text-slate-400">
        Step {step} of 4
      </p>

      {assistNotice !== null && (
        <p className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {assistNotice}
        </p>
      )}

      {loading && step !== 4 && <LoadingState label="Working..." />}

      {step === 1 && !loading && (
        <form onSubmit={(event) => void handleInterestNext(event)} className="space-y-4">
          <div>
            <label htmlFor="topic-name" className="mb-1 block text-sm font-medium text-slate-700">
              Topic name
            </label>
            <input
              id="topic-name"
              type="text"
              required
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label
              htmlFor="topic-description"
              className="mb-1 block text-sm font-medium text-slate-700"
            >
              What do you want to follow?
            </label>
            <textarea
              id="topic-description"
              required
              rows={4}
              placeholder="e.g. the US-Iran war and shipping disruption; or Postgres releases, only breaking changes"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>

          <button
            type="submit"
            className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Next
          </button>
        </form>
      )}

      {step === 2 && !loading && (
        <form onSubmit={(event) => void handleSuggestKeywords(event)} className="space-y-4">
          <p className="text-sm text-slate-600">
            A few questions to sharpen keyword suggestions. Answer what you can.
          </p>

          {questions.map((question, index) => (
            <div key={question}>
              <label
                htmlFor={`clarify-q-${index}`}
                className="mb-1 block text-sm font-medium text-slate-700"
              >
                {question}
              </label>
              <input
                id={`clarify-q-${index}`}
                type="text"
                value={answers[index] ?? ''}
                onChange={(event) => {
                  const next = [...answers]
                  next[index] = event.target.value
                  setAnswers(next)
                }}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
          ))}

          <div className="flex gap-2">
            <button
              type="button"
              onClick={goBack}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700"
            >
              Back
            </button>
            <button
              type="submit"
              className="flex-1 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              Suggest keywords
            </button>
          </div>
        </form>
      )}

      {step === 3 && !loading && (
        <form onSubmit={handleKeywordsNext} className="space-y-4">
          <p className="text-sm text-slate-600">
            These keywords are matched against incoming content. Edit freely — add, remove, or rewrite.
          </p>

          <KeywordChips keywords={keywords} onChange={setKeywords} />

          <div className="flex gap-2">
            <button
              type="button"
              onClick={goBack}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700"
            >
              Back
            </button>
            <button
              type="submit"
              disabled={keywords.length === 0}
              className="flex-1 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </form>
      )}

      {step === 4 && (
        <form onSubmit={(event) => void handleCreate(event)} className="space-y-4">
          <p className="text-sm text-slate-600">
            Optionally attach a first source. A topic with no sources yet is valid.
          </p>

          <div>
            <label
              htmlFor="topic-source-name"
              className="mb-1 block text-sm font-medium text-slate-700"
            >
              Source name
            </label>
            <input
              id="topic-source-name"
              type="text"
              value={sourceName}
              onChange={(event) => setSourceName(event.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label
              htmlFor="topic-source-domain"
              className="mb-1 block text-sm font-medium text-slate-700"
            >
              Normalized domain
            </label>
            <input
              id="topic-source-domain"
              type="text"
              placeholder="example.com"
              value={domain}
              onChange={(event) => setDomain(event.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label
              htmlFor="topic-source-feed"
              className="mb-1 block text-sm font-medium text-slate-700"
            >
              Feed URL (optional)
            </label>
            <input
              id="topic-source-feed"
              type="text"
              value={feedUrl}
              onChange={(event) => setFeedUrl(event.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </div>

          {apiKey === null && (
            <div>
              <label
                htmlFor="topic-api-key"
                className="mb-1 block text-sm font-medium text-slate-700"
              >
                API key
              </label>
              <input
                id="topic-api-key"
                type="password"
                required
                value={localApiKey}
                onChange={(event) => setLocalApiKey(event.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </div>
          )}

          <p className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
            No brief runs now — the first brief arrives on the next scheduled cadence.
          </p>

          {error !== null && <ErrorState message={error} />}

          <div className="flex gap-2">
            <button
              type="button"
              onClick={goBack}
              disabled={loading}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-50"
            >
              Back
            </button>
            <button
              type="submit"
              disabled={loading || keywords.length === 0}
              className="flex-1 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {loading ? 'Creating...' : 'Create topic'}
            </button>
          </div>
        </form>
      )}

      {error !== null && step !== 4 && <ErrorState message={error} />}
    </div>
  )
}
