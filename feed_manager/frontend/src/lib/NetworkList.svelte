<script lang="ts">
  import type { WifiNetwork } from './types'

  interface Props {
    networks: WifiNetwork[]
    isScanning: boolean
    selectedSsid: string | null
    onSelect: (network: WifiNetwork) => void
    onRescan: () => void
  }

  const { networks, isScanning, selectedSsid, onSelect, onRescan }: Props = $props()

  function bars(signal: number): string {
    if (signal >= 75) return '●●●'
    if (signal >= 50) return '●●○'
    return '●○○'
  }
</script>

<section class="network-list">
  <header>
    <h2>Networks nearby</h2>
    <button class="rescan" onclick={onRescan} disabled={isScanning}>
      {isScanning ? 'Scanning…' : 'Rescan'}
    </button>
  </header>

  {#if isScanning && networks.length === 0}
    <p class="empty">Looking for networks…</p>
  {:else if networks.length === 0}
    <p class="empty">No networks found. Move the box closer to your router and rescan.</p>
  {:else}
    <ul>
      {#each networks as network (network.ssid)}
        <li>
          <button
            class="network"
            class:selected={network.ssid === selectedSsid}
            onclick={() => onSelect(network)}
          >
            <span class="name">
              {network.ssid}
              {#if network.is_known}<span class="tag">saved</span>{/if}
            </span>
            <span class="meta">
              {#if network.is_secured}<span class="lock" aria-label="secured">&#128274;</span>{/if}
              <span class="signal" aria-label={`Signal ${network.signal} percent`}>
                {bars(network.signal)}
              </span>
            </span>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .network-list {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 0.75rem;
    padding: 1.25rem;
    margin-bottom: 1.5rem;
  }

  header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
  }

  .rescan {
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    color: var(--text-muted);
    padding: 0.3rem 0.7rem;
    font-size: 0.85rem;
  }

  .rescan:disabled {
    opacity: 0.6;
    cursor: default;
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .network {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.6rem 0.75rem;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    background: transparent;
    color: var(--text);
    text-align: left;
  }

  .network.selected {
    border-color: var(--accent);
    box-shadow: 0 0 0 1px var(--accent);
  }

  .name {
    font-size: 0.95rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .tag {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-muted);
    border: 1px solid var(--border);
    border-radius: 0.25rem;
    padding: 0.05rem 0.3rem;
  }

  .meta {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--text-muted);
    font-size: 0.85rem;
  }
</style>
