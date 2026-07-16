// Typed fetch wrappers for the routes this viewer consumes (briefs, sources,
// ingestion). Field names/types mirror the Pydantic response models exactly
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

export interface FeedHealth {
  id: string
  feed_url: string
  enabled: boolean
  poll_interval_minutes: number
  last_polled_at: string | null
  last_success_at: string | null
  last_error_summary: string | null
}

export interface Source {
  id: string
  stable_id: string
  name: string
  normalized_domain: string
  feeds: FeedHealth[]
}

export interface RegisterFeedRequest {
  feed_url: string
  enabled?: boolean
  poll_interval_minutes?: number
}

export interface RegisterSourceRequest {
  stable_id: string
  name: string
  normalized_domain: string
  feeds: RegisterFeedRequest[]
}

export interface IngestionResult {
  candidate_url: string
  status: string
  article_id: string | null
  error_code: string | null
  error_summary: string | null
}

export interface IngestionAttempt {
  id: string
  source_id: string
  source_feed_id: string | null
  requested_url: string
  canonical_url: string | null
  status: string
  http_status: number | null
  extractor: string | null
  article_id: string | null
  error_code: string | null
  error_summary: string | null
  started_at: string
  completed_at: string | null
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

export async function fetchSources(): Promise<Source[]> {
  const response = await fetch('/sources')
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response))
  }
  return (await response.json()) as Source[]
}

export async function registerSource(
  apiKey: string,
  req: RegisterSourceRequest,
): Promise<Source> {
  const response = await fetch('/sources', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
    body: JSON.stringify(req),
  })
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response))
  }
  return (await response.json()) as Source
}

export async function ingestUrls(
  apiKey: string,
  sourceId: string,
  urls: string[],
): Promise<IngestionResult[]> {
  const response = await fetch('/ingestion/urls', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': apiKey },
    body: JSON.stringify({ source_id: sourceId, urls }),
  })
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response))
  }
  return (await response.json()) as IngestionResult[]
}

export async function ingestFile(
  apiKey: string,
  sourceId: string,
  file: File,
): Promise<IngestionResult> {
  const formData = new FormData()
  formData.append('source_id', sourceId)
  formData.append('file', file)
  const response = await fetch('/ingestion/files', {
    method: 'POST',
    headers: { 'X-API-Key': apiKey },
    body: formData,
  })
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response))
  }
  return (await response.json()) as IngestionResult
}

export async function fetchIngestionAttempts(limit?: number): Promise<IngestionAttempt[]> {
  const query = limit !== undefined ? `?limit=${encodeURIComponent(String(limit))}` : ''
  const response = await fetch(`/ingestion/attempts${query}`)
  if (!response.ok) {
    throw new Error(await parseErrorDetail(response))
  }
  return (await response.json()) as IngestionAttempt[]
}
