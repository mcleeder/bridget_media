<script lang="ts">
  import { onMount } from 'svelte'
  import type { NetworkStatus, WifiNetwork } from './types'
  import { joinNetwork, scanNetworks } from './api'
  import NetworkList from './NetworkList.svelte'

  interface Props {
    status: NetworkStatus | null
  }

  const { status }: Props = $props()

  let networks = $state<WifiNetwork[]>([])
  let isScanning = $state(false)
  let scanError = $state<string | null>(null)

  let selectedSsid = $state<string | null>(null)
  let password = $state('')
  let isHiddenEntry = $state(false)
  let hiddenSsid = $state('')

  let isSubmitting = $state(false)
  let submitted = $state(false)
  let joinError = $state<string | null>(null)

  const targetSsid = $derived(isHiddenEntry ? hiddenSsid.trim() : (selectedSsid ?? ''))
  const canSubmit = $derived(targetSsid.length > 0 && !isSubmitting)

  async function rescan(): Promise<void> {
    isScanning = true
    scanError = null
    try {
      networks = await scanNetworks()
    } catch (err) {
      scanError = err instanceof Error ? err.message : 'Scan failed'
    } finally {
      isScanning = false
    }
  }

  onMount(() => {
    void rescan()
  })

  function select(network: WifiNetwork): void {
    isHiddenEntry = false
    selectedSsid = network.ssid
    password = ''
    joinError = null
  }

  async function submit(event: SubmitEvent): Promise<void> {
    event.preventDefault()
    if (!canSubmit) return
    isSubmitting = true
    joinError = null
    try {
      await joinNetwork(targetSsid, password, isHiddenEntry)
      submitted = true
    } catch (err) {
      // Joining tears down the hotspot this page is served over, so the
      // request dying is the *expected* outcome of a successful join. Only a
      // refusal the server managed to send back (a 4xx it answered before
      // switching) is worth showing as an error.
      if (err instanceof TypeError) {
        submitted = true
      } else {
        joinError = err instanceof Error ? err.message : 'Join failed'
      }
    } finally {
      isSubmitting = false
    }
  }
</script>

<section class="wifi">
  {#if submitted}
    <div class="submitted">
      <h2>Connecting to {targetSsid}</h2>
      <p>
        This setup network is shutting down, so this page will stop responding — that is
        normal. <strong>Watch the screen on the box</strong>: it shows the network it joined
        and the address to open next.
      </p>
      <p class="muted">
        If the screen still says it is offline after a minute, the password was probably
        wrong. The setup network comes back on its own — reconnect and try again.
      </p>
    </div>
  {:else}
    {#if status?.is_hotspot_active}
      <p class="notice">
        You are connected to the box's own setup network. Pick your home Wi-Fi below.
      </p>
    {/if}

    {#if scanError}
      <p class="error">{scanError}</p>
    {/if}

    <NetworkList
      {networks}
      {isScanning}
      selectedSsid={isHiddenEntry ? null : selectedSsid}
      onSelect={select}
      onRescan={() => void rescan()}
    />

    <form onsubmit={(event) => void submit(event)}>
      <label class="hidden-toggle">
        <input
          type="checkbox"
          bind:checked={isHiddenEntry}
          onchange={() => {
            selectedSsid = null
            joinError = null
          }}
        />
        My network is hidden (type its name)
      </label>

      {#if isHiddenEntry}
        <label class="field">
          <span>Network name</span>
          <input type="text" bind:value={hiddenSsid} autocomplete="off" spellcheck="false" />
        </label>
      {/if}

      <label class="field">
        <span>Password</span>
        <input type="password" bind:value={password} autocomplete="off" />
      </label>

      {#if joinError}
        <p class="error">{joinError}</p>
      {/if}

      <button class="join" type="submit" disabled={!canSubmit}>
        {#if isSubmitting}
          Sending…
        {:else if targetSsid}
          Join {targetSsid}
        {:else}
          Pick a network
        {/if}
      </button>
    </form>
  {/if}
</section>

<style>
  .notice {
    color: var(--text-muted);
    font-size: 0.9rem;
    margin-bottom: 1rem;
  }

  form {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 0.75rem;
    padding: 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    font-size: 0.9rem;
  }

  .field input {
    font: inherit;
    padding: 0.6rem 0.7rem;
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    background: var(--bg);
    color: var(--text);
  }

  .hidden-toggle {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.9rem;
    color: var(--text-muted);
  }

  .join {
    background: var(--accent);
    color: var(--accent-text);
    border: none;
    border-radius: 0.5rem;
    padding: 0.7rem 1rem;
    font-size: 0.95rem;
  }

  .join:disabled {
    opacity: 0.55;
    cursor: default;
  }

  .submitted h2 {
    margin-bottom: 0.75rem;
  }

  .submitted p {
    font-size: 0.95rem;
    line-height: 1.45;
    margin-bottom: 0.75rem;
  }

  .muted {
    color: var(--text-muted);
    font-size: 0.9rem;
  }
</style>
