<script lang="ts">
  import type { Feed, PodcastSearchResult } from './types'
  import { searchPodcasts } from './api'
  import SearchResultCard from './SearchResultCard.svelte'

  interface Props {
    feeds: Feed[]
    onAdd: (result: PodcastSearchResult) => Promise<void>
  }

  const { feeds, onAdd }: Props = $props()

  const RESULTS_PER_PAGE = 20

  let term = $state('')
  let results = $state<PodcastSearchResult[]>([])
  let offset = $state(0)
  let loading = $state(false)
  let searched = $state(false)
  let error = $state<string | null>(null)
  let addingUrl = $state<string | null>(null)

  const addedUrls = $derived(new Set(feeds.map((feed) => feed.url)))

  async function runSearch(nextOffset: number): Promise<void> {
    if (!term.trim()) return
    loading = true
    error = null
    try {
      results = await searchPodcasts(term, nextOffset)
      offset = nextOffset
      searched = true
    } catch (err) {
      error = err instanceof Error ? err.message : 'Search failed'
    } finally {
      loading = false
    }
  }

  function handleSubmit(event: SubmitEvent): void {
    event.preventDefault()
    void runSearch(0)
  }

  async function handleAdd(result: PodcastSearchResult): Promise<void> {
    addingUrl = result.feed_url
    error = null
    try {
      await onAdd(result)
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to add podcast'
    } finally {
      addingUrl = null
    }
  }
</script>

<section class="search-panel">
  <h2>Add a Podcast</h2>
  <form onsubmit={handleSubmit}>
    <input type="search" placeholder="Search podcasts…" bind:value={term} />
    <button type="submit" disabled={loading}>Search</button>
  </form>

  {#if error}
    <p class="error">{error}</p>
  {/if}

  {#if results.length > 0}
    <ul class="results">
      {#each results as result (result.feed_url)}
        <SearchResultCard
          {result}
          alreadyAdded={addedUrls.has(result.feed_url)}
          adding={addingUrl === result.feed_url}
          onAdd={handleAdd}
        />
      {/each}
    </ul>
    <div class="pagination">
      <button
        disabled={offset === 0 || loading}
        onclick={() => runSearch(Math.max(0, offset - RESULTS_PER_PAGE))}
      >
        Previous
      </button>
      <button
        disabled={results.length < RESULTS_PER_PAGE || loading}
        onclick={() => runSearch(offset + RESULTS_PER_PAGE)}
      >
        Next
      </button>
    </div>
  {:else if searched && !loading}
    <p class="empty">No results.</p>
  {/if}
</section>

<style>
  .search-panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 0.75rem;
    padding: 1.25rem;
  }

  form {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
  }

  input[type='search'] {
    flex: 1;
    font: inherit;
    padding: 0.5rem 0.75rem;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    background: var(--bg);
    color: var(--text);
  }

  form button {
    background: var(--accent);
    color: var(--accent-text);
    border: none;
    border-radius: 0.5rem;
    padding: 0.5rem 1rem;
  }

  form button:disabled {
    background: var(--border);
    color: var(--text-muted);
  }

  .results {
    list-style: none;
    margin: 0 0 1rem;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .pagination {
    display: flex;
    justify-content: space-between;
  }

  .pagination button {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    padding: 0.4rem 0.9rem;
    color: var(--text);
  }

  .pagination button:disabled {
    color: var(--text-muted);
    cursor: default;
  }
</style>
