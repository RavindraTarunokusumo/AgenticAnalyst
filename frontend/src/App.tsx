import { useEffect, useRef, useState } from 'react'
import type {
  BriefDetail as BriefDetailData,
  BriefListItem,
  Cadence,
  IngestionAttempt,
  Topic,
} from './api'
import { fetchBriefDetail, fetchBriefList, fetchIngestionAttempts, fetchTopics } from './api'
import { AddContentPanel } from './components/AddContentPanel'
import { ApiKeySettings } from './components/ApiKeySettings'
import { BriefDetail } from './components/BriefDetail'
import { BriefList } from './components/BriefList'
import { CadenceTabs } from './components/CadenceTabs'
import { ErrorState } from './components/ErrorState'
import { LoadingState } from './components/LoadingState'
import { RecentActivityList } from './components/RecentActivityList'
import { TopicOnboarding } from './components/TopicOnboarding'
import { TopicSettings } from './components/TopicSettings'

function App() {
  const [cadence, setCadence] = useState<Cadence>('daily')
  const [briefs, setBriefs] = useState<BriefListItem[] | null>(null)
  const [briefsLoading, setBriefsLoading] = useState(true)
  const [briefsError, setBriefsError] = useState<string | null>(null)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedBrief, setSelectedBrief] = useState<BriefDetailData | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const latestDetailRequestId = useRef<string | null>(null)

  const [topics, setTopics] = useState<Topic[] | null>(null)
  const [topicsLoading, setTopicsLoading] = useState(true)
  const [topicsError, setTopicsError] = useState<string | null>(null)
  const [selectedTopicId, setSelectedTopicId] = useState<string | null>(null)
  const [view, setView] = useState<'briefs' | 'settings'>('briefs')
  const [creatingNew, setCreatingNew] = useState(false)
  const [apiKey, setApiKey] = useState<string | null>(() => localStorage.getItem('ae_api_key'))

  const [attempts, setAttempts] = useState<IngestionAttempt[] | null>(null)
  const [attemptsLoading, setAttemptsLoading] = useState(true)
  const [attemptsError, setAttemptsError] = useState<string | null>(null)

  function refetchAttempts() {
    setAttemptsLoading(true)
    setAttemptsError(null)
    fetchIngestionAttempts()
      .then(setAttempts)
      .catch((err: unknown) => {
        setAttemptsError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        setAttemptsLoading(false)
      })
  }

  // Gates the normal view behind at least one topic - runs once on mount,
  // not on cadence/selection changes.
  useEffect(() => {
    let cancelled = false
    fetchTopics()
      .then((items) => {
        if (!cancelled) {
          setTopics(items)
          if (items.length > 0) {
            setSelectedTopicId((current) => current ?? items[0].id)
          }
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setTopicsError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setTopicsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    refetchAttempts()
  }, [])

  function handleTopicCreated(topic: Topic, key: string) {
    setTopics((current) => (current === null || current.length === 0 ? [topic] : [...current, topic]))
    setSelectedTopicId(topic.id)
    setApiKey(key)
    setView('briefs')
    setCreatingNew(false)
  }

  function handleTopicSaved(updated: Topic) {
    setTopics((current) =>
      current === null
        ? current
        : current.map((topic) => (topic.id === updated.id ? updated : topic)),
    )
  }

  function handleApiKeySave(key: string) {
    localStorage.setItem('ae_api_key', key)
    setApiKey(key)
  }

  function handleTopicSelect(topicId: string) {
    latestDetailRequestId.current = null
    setSelectedTopicId(topicId)
    setSelectedId(null)
    setSelectedBrief(null)
    setDetailError(null)
    setView('briefs')
  }

  // Re-fetch the list whenever the active cadence tab or selected topic
  // changes; the currently selected brief and its detail panel are left
  // alone until an explicit cadence/topic switch or a new pick.
  useEffect(() => {
    if (selectedTopicId === null) {
      setBriefs([])
      setBriefsLoading(false)
      setBriefsError(null)
      return
    }
    let cancelled = false
    setBriefsLoading(true)
    setBriefsError(null)
    fetchBriefList(cadence, selectedTopicId)
      .then((items) => {
        if (!cancelled) setBriefs(items)
      })
      .catch((err: unknown) => {
        if (!cancelled) setBriefsError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setBriefsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [cadence, selectedTopicId])

  function handleCadenceChange(next: Cadence) {
    latestDetailRequestId.current = null
    setCadence(next)
    setSelectedId(null)
    setSelectedBrief(null)
    setDetailError(null)
  }

  // Guards against a slower fetch for an earlier click overwriting a faster
  // one for a later click (or repopulating state after a cadence switch
  // already reset it) - only the most recently requested id's response is
  // applied, mirroring the cancellation pattern in the cadence effect above.
  function handleSelectBrief(id: string) {
    latestDetailRequestId.current = id
    setSelectedId(id)
    setDetailLoading(true)
    setDetailError(null)
    fetchBriefDetail(id)
      .then((brief) => {
        if (latestDetailRequestId.current === id) setSelectedBrief(brief)
      })
      .catch((err: unknown) => {
        if (latestDetailRequestId.current === id) {
          setSelectedBrief(null)
          setDetailError(err instanceof Error ? err.message : String(err))
        }
      })
      .finally(() => {
        if (latestDetailRequestId.current === id) setDetailLoading(false)
      })
  }

  const selectedTopic =
    topics !== null && selectedTopicId !== null
      ? (topics.find((topic) => topic.id === selectedTopicId) ?? null)
      : null

  const header = (
    <header className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
      <h1 className="text-xl font-semibold">AnalystEngine Briefs</h1>
      <ApiKeySettings apiKey={apiKey} onSave={handleApiKeySave} />
    </header>
  )

  if (topicsLoading) {
    return (
      <div className="min-h-svh bg-white text-slate-900">
        {header}
        <LoadingState label="Loading topics..." />
      </div>
    )
  }

  if (topicsError !== null) {
    return (
      <div className="min-h-svh bg-white text-slate-900">
        {header}
        <ErrorState message={topicsError} />
      </div>
    )
  }

  if (creatingNew || (topics !== null && topics.length === 0)) {
    return (
      <div className="min-h-svh bg-white text-slate-900">
        {header}
        <TopicOnboarding
          apiKey={apiKey}
          onApiKeyChange={handleApiKeySave}
          onCreated={handleTopicCreated}
        />
      </div>
    )
  }

  return (
    <div className="min-h-svh bg-white text-slate-900">
      {header}

      <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 px-6 py-3">
        <label htmlFor="topic-select" className="text-sm font-medium text-slate-700">
          Topic
        </label>
        <select
          id="topic-select"
          value={selectedTopicId ?? ''}
          onChange={(event) => handleTopicSelect(event.target.value)}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
        >
          {(topics ?? []).map((topic) => (
            <option key={topic.id} value={topic.id}>
              {topic.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => setCreatingNew(true)}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700"
        >
          New topic
        </button>
        <button
          type="button"
          onClick={() => setView((current) => (current === 'briefs' ? 'settings' : 'briefs'))}
          className={
            view === 'settings'
              ? 'rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white'
              : 'rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700'
          }
        >
          Settings
        </button>
      </div>

      {view === 'settings' && selectedTopic !== null ? (
        <main className="mx-auto max-w-6xl p-6">
          <section className="rounded-md border border-slate-200">
            <TopicSettings topic={selectedTopic} apiKey={apiKey} onSaved={handleTopicSaved} />
          </section>
        </main>
      ) : (
        <>
          <main className="mx-auto grid max-w-6xl grid-cols-1 gap-6 p-6 md:grid-cols-[320px_1fr]">
            <section className="rounded-md border border-slate-200">
              <div className="px-2 pt-2">
                <CadenceTabs active={cadence} onChange={handleCadenceChange} />
              </div>
              <BriefList
                items={briefs}
                loading={briefsLoading}
                error={briefsError}
                selectedId={selectedId}
                onSelect={handleSelectBrief}
              />
            </section>

            <section className="rounded-md border border-slate-200 p-4">
              <BriefDetail brief={selectedBrief} loading={detailLoading} error={detailError} />
            </section>
          </main>

          <main className="mx-auto grid max-w-6xl grid-cols-1 gap-6 px-6 pb-6 md:grid-cols-2">
            <section className="rounded-md border border-slate-200 p-4">
              <h2 className="mb-3 text-sm font-semibold text-slate-900">Add content</h2>
              {apiKey !== null && selectedTopicId !== null ? (
                <AddContentPanel
                  apiKey={apiKey}
                  topicId={selectedTopicId}
                  onSubmitted={refetchAttempts}
                />
              ) : (
                <p className="text-sm text-slate-500">Set an API key to add content.</p>
              )}
            </section>

            <section className="rounded-md border border-slate-200">
              <h2 className="px-3 pt-3 text-sm font-semibold text-slate-900">Recent activity</h2>
              <RecentActivityList
                attempts={attempts}
                loading={attemptsLoading}
                error={attemptsError}
              />
            </section>
          </main>
        </>
      )}
    </div>
  )
}

export default App
