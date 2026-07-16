import { useEffect, useRef, useState } from 'react'
import type {
  BriefDetail as BriefDetailData,
  BriefListItem,
  Cadence,
  IngestionAttempt,
  Source,
} from './api'
import { fetchBriefDetail, fetchBriefList, fetchIngestionAttempts, fetchSources } from './api'
import { AddContentPanel } from './components/AddContentPanel'
import { ApiKeySettings } from './components/ApiKeySettings'
import { BriefDetail } from './components/BriefDetail'
import { BriefList } from './components/BriefList'
import { CadenceTabs } from './components/CadenceTabs'
import { ErrorState } from './components/ErrorState'
import { LoadingState } from './components/LoadingState'
import { Onboarding } from './components/Onboarding'
import { RecentActivityList } from './components/RecentActivityList'

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

  const [sources, setSources] = useState<Source[] | null>(null)
  const [sourcesLoading, setSourcesLoading] = useState(true)
  const [sourcesError, setSourcesError] = useState<string | null>(null)
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

  // Gates the normal 3-panel view behind at least one registered source
  // (spec §3.1) - runs once on mount, not on cadence/selection changes.
  useEffect(() => {
    let cancelled = false
    fetchSources()
      .then((items) => {
        if (!cancelled) setSources(items)
      })
      .catch((err: unknown) => {
        if (!cancelled) setSourcesError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setSourcesLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    refetchAttempts()
  }, [])

  function handleOnboarded(source: Source, registeredApiKey: string) {
    setSources([source])
    setApiKey(registeredApiKey)
  }

  function handleApiKeySave(key: string) {
    localStorage.setItem('ae_api_key', key)
    setApiKey(key)
  }

  // Re-fetch the list whenever the active cadence tab changes; the currently
  // selected brief and its detail panel are left alone (spec §6 step 4 - no
  // re-fetch on "back", only on an explicit cadence switch or a new pick).
  useEffect(() => {
    let cancelled = false
    setBriefsLoading(true)
    setBriefsError(null)
    fetchBriefList(cadence)
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
  }, [cadence])

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

  const header = (
    <header className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
      <h1 className="text-xl font-semibold">AnalystEngine Briefs</h1>
      <ApiKeySettings apiKey={apiKey} onSave={handleApiKeySave} />
    </header>
  )

  if (sourcesLoading) {
    return (
      <div className="min-h-svh bg-white text-slate-900">
        {header}
        <LoadingState label="Loading sources..." />
      </div>
    )
  }

  if (sourcesError !== null) {
    return (
      <div className="min-h-svh bg-white text-slate-900">
        {header}
        <ErrorState message={sourcesError} />
      </div>
    )
  }

  if (sources !== null && sources.length === 0) {
    return (
      <div className="min-h-svh bg-white text-slate-900">
        {header}
        <Onboarding onRegistered={handleOnboarded} />
      </div>
    )
  }

  return (
    <div className="min-h-svh bg-white text-slate-900">
      {header}

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
          {apiKey !== null && sources !== null && sources.length > 0 ? (
            <AddContentPanel apiKey={apiKey} source={sources[0]} onSubmitted={refetchAttempts} />
          ) : (
            <p className="text-sm text-slate-500">Set an API key to add content.</p>
          )}
        </section>

        <section className="rounded-md border border-slate-200">
          <h2 className="px-3 pt-3 text-sm font-semibold text-slate-900">Recent activity</h2>
          <RecentActivityList attempts={attempts} loading={attemptsLoading} error={attemptsError} />
        </section>
      </main>
    </div>
  )
}

export default App
