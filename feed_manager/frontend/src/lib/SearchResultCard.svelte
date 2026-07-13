<script lang="ts">
  import type { PodcastSearchResult } from './types'

  interface Props {
    result: PodcastSearchResult
    alreadyAdded: boolean
    adding: boolean
    onAdd: (result: PodcastSearchResult) => void
  }

  const { result, alreadyAdded, adding, onAdd }: Props = $props()
</script>

<li class="result">
  {#if result.artwork_url}
    <img src={result.artwork_url} alt="" width="48" height="48" />
  {:else}
    <div class="artwork-placeholder"></div>
  {/if}
  <div class="info">
    <div class="name">{result.name}</div>
    <div class="artist">{result.artist_name}</div>
  </div>
  <button disabled={alreadyAdded || adding} onclick={() => onAdd(result)}>
    {alreadyAdded ? 'Added' : adding ? 'Adding…' : 'Add'}
  </button>
</li>

<style>
  .result {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
  }

  img,
  .artwork-placeholder {
    width: 48px;
    height: 48px;
    border-radius: 0.375rem;
    flex-shrink: 0;
    background: var(--border);
  }

  .info {
    flex: 1;
    min-width: 0;
  }

  .name {
    font-size: 0.95rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .artist {
    font-size: 0.8rem;
    color: var(--text-muted);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  button {
    flex-shrink: 0;
    background: var(--accent);
    color: var(--accent-text);
    border: none;
    border-radius: 0.375rem;
    padding: 0.4rem 0.75rem;
    font-size: 0.85rem;
  }

  button:disabled {
    background: var(--border);
    color: var(--text-muted);
    cursor: default;
  }
</style>
