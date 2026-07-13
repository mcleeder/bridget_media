import type { Feed, PodcastSearchResult } from './types'

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body: { error?: string } = await response.json().catch(() => ({}))
    throw new Error(body.error ?? `Request failed with status ${response.status}`)
  }
  return response.json() as Promise<T>
}

export async function fetchFeeds(): Promise<Feed[]> {
  const response = await fetch('/api/feeds')
  return handleResponse<Feed[]>(response)
}

export async function addFeed(name: string, url: string): Promise<Feed> {
  const response = await fetch('/api/feeds', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, url }),
  })
  return handleResponse<Feed>(response)
}

export async function deleteFeed(feedId: number): Promise<void> {
  const response = await fetch(`/api/feeds/${feedId}`, { method: 'DELETE' })
  if (!response.ok) {
    throw new Error(`Failed to delete feed ${feedId}`)
  }
}

export async function searchPodcasts(term: string, offset = 0): Promise<PodcastSearchResult[]> {
  const params = new URLSearchParams({ q: term, offset: String(offset) })
  const response = await fetch(`/api/search?${params.toString()}`)
  return handleResponse<PodcastSearchResult[]>(response)
}
