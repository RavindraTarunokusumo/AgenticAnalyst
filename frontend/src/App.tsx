import { useEffect, useRef, useState } from 'react'
import type { BriefDetail as BriefDetailData, BriefListItem, Cadence } from './api'
import { fetchBriefDetail, fetchBriefList } from './api'
import { BriefDetail } from './components/BriefDetail'
import { BriefList } from './components/BriefList'
import { CadenceTabs } from './components/CadenceTabs'

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

  return (
    <div className="min-h-svh bg-white text-slate-900">
      <header className="border-b border-slate-200 px-6 py-4">
        <h1 className="text-xl font-semibold">AnalystEngine Briefs</h1>
      </header>

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
    </div>
  )
}

export default App
