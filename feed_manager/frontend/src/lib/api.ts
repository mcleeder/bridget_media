import type { Feed, NetworkStatus, PodcastSearchResult, WifiNetwork } from './types'

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

export async function fetchNetworkStatus(): Promise<NetworkStatus> {
  const response = await fetch('/api/network/status')
  return handleResponse<NetworkStatus>(response)
}

export async function scanNetworks(): Promise<WifiNetwork[]> {
  const response = await fetch('/api/network/scan')
  return handleResponse<WifiNetwork[]>(response)
}

// Answers 202 and joins in the background: switching networks tears down the
// hotspot this request arrived over, so a dropped connection here is the
// success case, not a failure. Callers must treat a network error after a
// submitted join as "probably worked — go look at the screen".
export async function joinNetwork(
  ssid: string,
  password: string,
  isHidden = false,
): Promise<void> {
  const response = await fetch('/api/network/join', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ssid, password, is_hidden: isHidden }),
  })
  await handleResponse<{ status: string }>(response)
}
