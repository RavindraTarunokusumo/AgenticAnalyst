// Typed fetch wrappers for the two existing read routes this viewer consumes.
// Field names/types mirror BriefListItemResponse/BriefDetailResponse exactly
// (src/analyst_engine/api/app.py) - update here if those response models change.

export type Cadence = 'daily' | 'weekly' | 'monthly'

export interface BriefListItem {
  id: string
  cadence: string
  covered_start: string
  covered_end: string
  created_at: string
}

export interface ResolvedCitation {
  article_id: string
  excerpt: string | null
  article_title: string
  article_url: string
  source_name: string
}

export interface ResolvedBatchSummary {
  id: string
  model: string
  prompt_version: string
  summary: string
  source_notes: string | null
  entities: string[]
  topics: string[]
  citations: ResolvedCitation[]
}

export interface BriefDetail {
  id: string
  cadence: string
  covered_start: string
  covered_end: string
  content: string
  narrative_state_version_id: string | null
  created_by_run_id: string
  created_at: string
  cited_summaries: ResolvedBatchSummary[]
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (
      body !== null &&
      typeof body === 'object' &&
      'detail' in body &&
      typeof (body as { detail: unknown }).detail === 'string'
    ) {
      return (body as { detail: string }).detail
    }
  } catch {
    // response body wasn't JSON - fall through to the status-based message
  }
  return `request failed with status ${response.status}`
}

// Throws on any non-2xx response (including 404) so callers drive their own
// error-state UI; this module never swallows a failed request.
export async function fetchBriefList(cadence: Cadence): Promise<BriefListItem[]> {
  const response = await fetch(`/briefs?cadence=${encodeURIComponent(cadence)}`)
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response))
  }
  return (await response.json()) as BriefListItem[]
}

export async function fetchBriefDetail(id: string): Promise<BriefDetail> {
  const response = await fetch(`/briefs/${encodeURIComponent(id)}`)
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response))
  }
  return (await response.json()) as BriefDetail
}
