export interface Feed {
  id: number
  name: string
  url: string
  last_fetched: string | null
}

export interface PodcastSearchResult {
  name: string
  artist_name: string
  feed_url: string
  artwork_url: string | null
}

export interface NetworkStatus {
  is_online: boolean
  ssid: string | null
  ip_address: string | null
  is_hotspot_active: boolean
}

export interface WifiNetwork {
  ssid: string
  signal: number
  is_secured: boolean
  is_known: boolean
}
