<script lang="ts">
  import type { Feed } from './types'

  interface Props {
    feeds: Feed[]
    onRemove: (feedId: number) => void
  }

  const { feeds, onRemove }: Props = $props()
</script>

<section class="feed-list">
  <h2>Your Podcasts</h2>
  {#if feeds.length === 0}
    <p class="empty">No feeds yet — search below to add one.</p>
  {:else}
    <ul>
      {#each feeds as feed (feed.id)}
        <li>
          <span class="name">{feed.name}</span>
          <button
            class="remove"
            onclick={() => onRemove(feed.id)}
            aria-label={`Remove ${feed.name}`}
          >
            &times;
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .feed-list {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 0.75rem;
    padding: 1.25rem;
    margin-bottom: 1.5rem;
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.5rem 0.75rem;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
  }

  .name {
    font-size: 0.95rem;
  }

  .remove {
    background: transparent;
    border: none;
    color: var(--text-muted);
    font-size: 1.25rem;
    line-height: 1;
    padding: 0.25rem 0.5rem;
    border-radius: 0.375rem;
  }

  .remove:hover {
    color: var(--danger);
    background: var(--border);
  }
</style>
