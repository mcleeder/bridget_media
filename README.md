# Pi Media

A podcast player for a Raspberry Pi 3B+ with a Waveshare 2.9" e-ink touchscreen. Streams audio (no local storage) via MPD to a Bluetooth speaker. Feeds are managed from a phone/laptop through a small companion web app, not on the tiny screen itself.

Full architecture, schema, coding standards, and phase history live in [CLAUDE.md](CLAUDE.md). This doc is the fast path for running, debugging, and deploying.

## Two entry points

| Process | Runs | Purpose |
|---|---|---|
| `main.py` | on the Pi (or `--simulate` locally) | e-ink UI + MPD playback |
| `feed_manager/app.py` | on the Pi | Flask + Svelte web UI to search/add/remove feeds |

Both are independent OS processes talking to the same `pi_media.db` (SQLite, WAL mode). Neither imports the other.

## Layers (bottom to top, strict — never import upward)

```
config  →  db  →  feeds / player / bluetooth  →  display  →  main / feed_manager
```

- **`db/`** — schema + repositories (`FeedRepository`, `EpisodeRepository`, `QueueRepository`). One `sqlite3` connection per thread/process, always — sharing one across threads corrupts it (hit this once, see CLAUDE.md "Key Notes").
- **`feeds/`** — `feedparser` fetch → DB. `feeds/fetcher.py` reads feeds from the DB (not `config.py` — that's a one-time seed only).
- **`player/`** — wraps `python-mpd2`. Resolves redirect chains and auto-reconnects on MPD's 60s idle-drop; see CLAUDE.md if playback silently dies after sitting on a list.
- **`bluetooth/`** — shells out to `bluetoothctl`.
- **`display/`** — the UI. Pure `transition()` state machine (`display/state_machine.py`) + `ScreenManager` (`display/manager.py`) that applies side effects and redraws. Screens only render and turn touches into events — they never navigate or call player/bluetooth directly (they go through Protocols in `display/playback.py` / `display/bluetooth_control.py`). This is what makes `--simulate` work with no MPD/hardware.
- **`feed_manager/`** — Flask API (`routes.py`) + built Svelte frontend, served as static files.

**If something's broken, start here:** UI/navigation bug → `display/`. Wrong/missing episodes → `feeds/` or the DB. Playback won't start/skip → `player/` (check `journalctl -u pi-media` first — failed player commands degrade to a log line, not a visible error). Feed manager not syncing to the screen → the 60s poll in `main.py`.

## Local development

```bash
conda activate pi_media
python main.py --simulate        # tkinter window, mouse = touch
```

MPD/Bluetooth aren't simulated — those calls fail gracefully on Windows. Test UI/navigation locally, test audio/BT on the Pi. To verify a change without manually clicking through the simulator, use the `verify` skill (scripted touches → PNG frames).

Feed manager frontend (one-time):
```bash
cd feed_manager/frontend && npm install
```

## Deploy scripts

All run from the repo root in **Git Bash** on Windows. Connection details (`PI_NETWORK_NAME`, `PI_USERNAME`, password) come from `.env` (git-ignored, not committed).

### Fresh Pi (after a reflash)

```bash
ssh-keygen -R tinypie3.local                     # only if reflashed — clears the stale host key
bash deploy/setup_ssh_key.sh                     # one-time: sets up passwordless SSH (prompts for .env password)
bash deploy/deploy.sh                             # syncs code to ~/pi_media on the Pi
ssh mike_pi@tinypie3.local 'bash ~/pi_media/deploy/setup_pi.sh'   # installs packages, enables SPI/I2C, sets up both services
```

`setup_pi.sh` is idempotent — safe to re-run any time (e.g. after adding a new apt/pip dependency). It needs passwordless `sudo` on the Pi; if the imager-created user doesn't have it:
```bash
ssh mike_pi@tinypie3.local "echo 'mike_pi ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/010_mike_pi-nopasswd"
```

Then pair the speaker (one-time per device):
```bash
bash deploy/pair_speaker.sh --scan               # lists nearby MACs/names
bash deploy/pair_speaker.sh AA:BB:CC:DD:EE:FF     # pairs, trusts, connects, patches mpd.conf
```
Reboot the Pi after.

### Routine iteration

```bash
bash deploy/deploy.sh
```
This builds the Svelte frontend locally, tar-over-ssh syncs everything (excluding caches, `.env`, the DB) to `~/pi_media`, and restarts both `pi-media` and `pi-media-feeds` services. **It does not delete files removed locally** — if you renamed/deleted a file, clean it up on the Pi manually.

### Logs / debugging on the Pi

```bash
ssh mike_pi@tinypie3.local 'journalctl -u pi-media -f'          # player/display app
ssh mike_pi@tinypie3.local 'journalctl -u pi-media-feeds -f'    # feed manager web app
```

### Script reference

| Script | When |
|---|---|
| `setup_ssh_key.sh` | Once per fresh Pi — enables passwordless SSH |
| `setup_pi.sh` | Once per fresh Pi, and again any time system deps/services change (idempotent) |
| `deploy.sh` | Every code push to the Pi |
| `pair_speaker.sh` | Once per new Bluetooth speaker |
| `pi-media.service` / `pi-media-feeds.service` | systemd unit templates, installed by `setup_pi.sh` — don't run directly |
| `mpd.conf` | MPD config template, installed by `setup_pi.sh` |
