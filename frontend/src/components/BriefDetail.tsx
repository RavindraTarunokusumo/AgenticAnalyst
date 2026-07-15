import type { BriefDetail as BriefDetailData } from '../api'
import { EmptyState } from './EmptyState'
import { ErrorState } from './ErrorState'
import { LoadingState } from './LoadingState'

// Article URLs are canonicalized to http(s) at ingestion time
// (ingestion/canonicalize.py rejects any other scheme before an Article is
// ever persisted), but this guard is cheap defense-in-depth against an
// href-based scheme injection (e.g. `javascript:`) should that invariant
// ever be bypassed by a future write path.
function isSafeHttpUrl(url: string): boolean {
  return /^https?:\/\//i.test(url)
}

interface BriefDetailProps {
  brief: BriefDetailData | null
  loading: boolean
  error: string | null
}

export function BriefDetail({ brief, loading, error }: BriefDetailProps) {
  if (loading) {
    return <LoadingState label="Loading brief..." />
  }
  if (error !== null) {
    return <ErrorState message={error} />
  }
  if (brief === null) {
    return <EmptyState message="Select a brief from the list to read it." />
  }

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-lg font-semibold capitalize text-slate-900">
          {brief.cadence} brief - {brief.covered_start} to {brief.covered_end}
        </h2>
        <p className="text-xs text-slate-400">
          Created {new Date(brief.created_at).toLocaleString()}
        </p>
      </header>

      {/* content is untrusted LLM-generated text - rendered only via React's
          default text interpolation (a safe text node), never innerHTML. */}
      <pre className="whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-slate-50 p-4 font-sans text-sm text-slate-800">
        {brief.content}
      </pre>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-900">Citations</h3>
        {brief.cited_summaries.length === 0 ? (
          <EmptyState message="No cited summaries for this brief." />
        ) : (
          <ul className="space-y-4">
            {brief.cited_summaries.map((summary) => (
              <li key={summary.id} className="rounded-md border border-slate-200 p-3">
                {(summary.entities.length > 0 || summary.topics.length > 0) && (
                  <div className="mb-2 flex flex-wrap gap-1">
                    {summary.entities.map((entity) => (
                      <span
                        key={`entity-${entity}`}
                        className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700"
                      >
                        {entity}
                      </span>
                    ))}
                    {summary.topics.map((topic) => (
                      <span
                        key={`topic-${topic}`}
                        className="rounded-full bg-purple-50 px-2 py-0.5 text-xs text-purple-700"
                      >
                        {topic}
                      </span>
                    ))}
                  </div>
                )}
                <ul className="space-y-1">
                  {summary.citations.map((citation) => (
                    <li key={citation.article_id} className="text-sm">
                      {isSafeHttpUrl(citation.article_url) ? (
                        <a
                          href={citation.article_url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="text-slate-900 underline hover:text-slate-600"
                        >
                          {citation.article_title !== '' ? citation.article_title : citation.article_url}
                        </a>
                      ) : (
                        <span className="text-slate-400">Source unavailable</span>
                      )}
                      {citation.source_name !== '' && (
                        <span className="ml-2 text-xs text-slate-400">{citation.source_name}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
