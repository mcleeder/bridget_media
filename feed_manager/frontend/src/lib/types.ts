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
