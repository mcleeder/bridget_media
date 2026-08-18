<script lang="ts">
  import { onMount } from 'svelte'
  import type { Feed, NetworkStatus, PodcastSearchResult } from './lib/types'
  import { addFeed, deleteFeed, fetchFeeds, fetchNetworkStatus } from './lib/api'
  import FeedList from './lib/FeedList.svelte'
  import SearchPanel from './lib/SearchPanel.svelte'
  import WifiPanel from './lib/WifiPanel.svelte'

  type View = 'podcasts' | 'wifi'

  let feeds = $state<Feed[]>([])
  let loadError = $state<string | null>(null)
  let networkStatus = $state<NetworkStatus | null>(null)
  let view = $state<View>('podcasts')

  async function loadFeeds(): Promise<void> {
    try {
      feeds = await fetchFeeds()
      loadError = null
    } catch (err) {
      loadError = err instanceof Error ? err.message : 'Failed to load feeds'
    }
  }

  async function loadNetworkStatus(): Promise<void> {
    try {
      networkStatus = await fetchNetworkStatus()
      // In setup mode the box has nothing else useful to offer, so open on
      // Wi-Fi without the owner having to notice there are tabs at all.
      if (networkStatus.is_hotspot_active) {
        view = 'wifi'
      }
    } catch {
      // No network layer (or no nmcli) is not a reason to hide the podcasts.
      networkStatus = null
    }
  }

  onMount(() => {
    void loadFeeds()
    void loadNetworkStatus()
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
  <h1>Bridget Media</h1>

  <nav class="tabs">
    <button class:active={view === 'podcasts'} onclick={() => (view = 'podcasts')}>
      Podcasts
    </button>
    <button class:active={view === 'wifi'} onclick={() => (view = 'wifi')}>
      Wi-Fi
      {#if networkStatus && !networkStatus.is_online}
        <span class="dot" aria-label="not online"></span>
      {/if}
    </button>
  </nav>

  {#if view === 'podcasts'}
    {#if loadError}
      <p class="error">{loadError}</p>
    {/if}
    <FeedList {feeds} onRemove={(feedId) => void handleRemove(feedId)} />
    <SearchPanel {feeds} onAdd={handleAdd} />
  {:else}
    <WifiPanel status={networkStatus} />
  {/if}
</main>

<style>
  .tabs {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1.5rem;
  }

  .tabs button {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    color: var(--text-muted);
    padding: 0.45rem 0.9rem;
    font-size: 0.95rem;
  }

  .tabs button.active {
    background: var(--surface);
    border-color: var(--accent);
    color: var(--text);
  }

  .dot {
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: var(--danger);
  }
</style>
