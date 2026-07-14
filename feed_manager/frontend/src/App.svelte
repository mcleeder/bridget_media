<script lang="ts">
  import { onMount } from 'svelte'
  import type { Feed, PodcastSearchResult } from './lib/types'
  import { addFeed, deleteFeed, fetchFeeds } from './lib/api'
  import FeedList from './lib/FeedList.svelte'
  import SearchPanel from './lib/SearchPanel.svelte'

  let feeds = $state<Feed[]>([])
  let loadError = $state<string | null>(null)

  async function loadFeeds(): Promise<void> {
    try {
      feeds = await fetchFeeds()
      loadError = null
    } catch (err) {
      loadError = err instanceof Error ? err.message : 'Failed to load feeds'
    }
  }

  onMount(() => {
    void loadFeeds()
  })

  async function handleAdd(result: PodcastSearchResult): Promise<void> {
    await addFeed(result.name, result.feed_url)
    await loadFeeds()
  }

  async function handleRemove(feedId: number): Promise<void> {
    await deleteFeed(feedId)
    await loadFeeds()
  }
</script>

<main>
  <h1>Bridget Media — Podcasts</h1>
  {#if loadError}
    <p class="error">{loadError}</p>
  {/if}
  <FeedList {feeds} onRemove={(feedId) => void handleRemove(feedId)} />
  <SearchPanel {feeds} onAdd={handleAdd} />
</main>
