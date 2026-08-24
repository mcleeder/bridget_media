# Pi Media — Raspberry Pi Podcast Player

## Project Overview

A podcast player running on a Raspberry Pi with a Waveshare 2.9" e-ink touch display. Streams audio via MPD to a Bluetooth speaker. No local audio storage — pure streaming. Feeds are managed via a small companion web app (`feed_manager/`) rather than the e-ink screen itself, which is too small/keyboard-less for search-and-add.

## Hardware

- **Raspberry Pi 3 Model B+** — Raspberry Pi OS (Debian 13 "trixie", arm64), hostname `bridget` since Phase 9 (was `tinypie3`); `.env` holds it plus the credentials
- **Display**: Waveshare 2.9" Touch E-Paper HAT — 296×128px, black/white, SPI
- **Touch**: 5-point capacitive, I2C (ICNT86 controller — confirmed on hardware; TP_lib's `ICNT_Scan` maps coords into 296×128 landscape space)
- **Audio**: MPD daemon → Bluetooth speaker via `mpc`

**Wiring — individual jumpers, not the ribbon ❌ NOT WORKING (2026-08-10)** — the HAT is being moved off the 40-pin ribbon onto individual jumper wires to save space in the case. On jumpers, **both panel and touch are dead**; the working touch-driven session logged earlier the same day was on the ribbon. It needs **12 signal wires plus power**, not just SPI and I2C: VCC (**3.3V** — pin 1/17, *not* 5V), GND, DIN/CLK/CS/DC/RST/BUSY for the panel, and TP_SDA/TP_SCL/TP_INT/TP_RST for touch. One ground is electrically sufficient — all header GND pins are the same net; the risk with a single jumper is a marginal crimp, whose intermittent contact reads as a logic fault rather than a wiring one. Confirm the pin map against TP_lib's `epdconfig.py` rather than a table written from memory.

**Diagnosis (2026-08-10): the panel's logic is alive; its refresh cannot complete. Points at marginal power, not signal wiring.** With the 8 panel wires fitted (VCC pin 1, GND pin 9, RST 11, BUSY 18, DIN 19, DC 22, CLK 23, CS 24 — all matching `epdconfig.py`), evidence in order of weight:

- **BUSY is driven, not floating.** `pinctrl set 24 ip pu` and `ip pd` both read `lo`, refusing to follow either internal pull, while an unattached control pin (GPIO23) follows both. So the panel is powered enough to hold BUSY.
- **The panel executes commands.** Sampling GPIO24 during a refresh caught BUSY high 27 times, versus 400/400 `lo` with no refresh running.
- **But the refresh never finishes.** `Clear(white)` returned in 0.26s (a real 2.9" full refresh is ~2s), then `display_Base` **hung past 119s** and left **BUSY stuck high** — the controller asserted busy and never released it. Nothing ever appears on the glass.
- **The Pi logged under-voltage**: `vcgencmd get_throttled` = `0x50000` (bit 16 under-voltage *has occurred*, bit 18 throttling has occurred; current-state bits clear).

Read together: logic-level work (µA) succeeds, but the panel's charge pump — which needs tens of mA to generate the ±20V that actually moves e-ink particles — cannot come up, so the waveform stalls forever. **Suspect power delivery: the PSU, and the single VCC/GND jumper pair (only one ground, pin 9).** Next physical tests: a known-good 5V 2.5A+ supply, a second GND jumper, re-crimped/shorter VCC and GND wires, and metering 3.3V at the HAT's own pads *during* a refresh looking for sag.

**Red PWR LED disabled (2026-08-22).** The box lives on a shelf, so the red power LED is off via `/boot/firmware/config.txt` (backup at `config.txt.bak-preled`):

```
dtparam=pwr_led_trigger=none
dtparam=pwr_led_activelow=on
```

**Both lines are required, and `activelow=on` is the opposite of the value in Raspberry Pi's own docs** — their recipe says `activelow=off`, which is a Pi 4 recipe and leaves this 3B+ **lit**. On this board the expander line is `PWR_LED_R` (Pi 4 names it `PWR_LED_OFF`, an inverted signal — do not carry Pi 4 reasoning across), and **a HIGH pin is dark**. `trigger=none` makes the kernel initialise brightness to `0`, so the polarity has to be the one where `0` drives the pin HIGH — that is `activelow=on`. Verified after reboot: DT flags cell `0x1` (ACTIVE_LOW), `brightness=0`, and `/sys/kernel/debug/gpio` showing `gpio-2 (PWR_LED_R |PWR) out hi ACTIVE LOW`.

**The green `ACT` LED is off too** (`dtparam=act_led_trigger=none`, added 2026-08-22). It needs **no** `act_led_activelow` line, and that asymmetry with PWR is the point: `ACT` is `STATUS_LED_G` on SoC GPIO 29 with stock DT flags `0x0` (active-high), so `brightness=0` already drives the pin LOW = dark. Verified as `gpio-29 (STATUS_LED_G |ACT) out lo`. Expect the green LED to **still flash during the first seconds of boot** — that is the bootloader using it for diagnostics before the kernel LED driver exists, and `dtparam` cannot reach that stage.

**Neither LED can be dimmed — only switched.** `max_brightness` is `1` on both: single GPIO lines, no PWM. The workarounds were checked and rejected, so they don't need rechecking: GPIO 29 has no PWM alt-function on the BCM2837 (PWM is on 12/13/18/19), and faking PWM with the `timer` trigger is bounded by `CONFIG_HZ=250` (4ms granularity), so any duty cycle low enough to read as "dim" lands at 20–25Hz and reads as flicker instead. Physical diffusion (tape) is the only real dimming. **The box now has no LED sign of life at all** — the e-ink panel is the liveness indicator, and since e-ink holds its last frame with no power, a frozen screen and a healthy screen look identical: use `systemctl status pi-media` to tell them apart.

**The cost: on the 3B+ the PWR LED *is* the under-voltage indicator**, and CLAUDE.md still has power delivery as the prime suspect for the panel trouble above. Use `vcgencmd get_throttled` — it reports the same bits, but only when asked. Observed on consecutive boots: `0x50000` (under-voltage *and* throttling occurred) on one, `0x0` on the very next, so **the fault is intermittent** — a single clean reading is not evidence the supply is fine.

Note this hang is precisely what the Phase "Display bring-up hardening" timeout was written for, and it fired correctly: `pi-media` reported `DisplayError` and settled into `failed` after 5 restarts instead of hanging silently.

The multi-hour debugging session this caused is worth remembering, because **none of the first half was the wiring**: the Pi had silently forgotten its Wi-Fi credentials and had to have them re-entered on the HDMI desktop. Misleading signals along the way — `nslookup tinypie3` answered `192.168.1.253` from the router's *stale DHCP lease table* while nothing was at that address (ARP resolved nothing; the "Destination host unreachable" ping reply came from the *local* machine, not the Pi), and the display appearing to "boot better" when re-plugged was coincidence. Check liveness with ARP/ping, never with a DNS answer alone. This is also the strongest argument yet for the Phase 9–10 AP fallback: recovery here required a monitor, a keyboard and physical access, none of which a friend with the box on a shelf would have.

## Tech Stack

| Concern | Choice |
|---|---|
| Language | Python 3 |
| Database | SQLite (stdlib `sqlite3`) |
| RSS parsing | `feedparser` |
| MPD client | `python-mpd2` |
| Display driver | Waveshare EPD library (from their GitHub/wiki) |
| Image rendering | `Pillow` (PIL) |
| Scheduling | `APScheduler` (background feed refresh) |
| Local dev simulator | `tkinter` (stdlib) |
| Feed manager backend | `Flask` + `requests` (iTunes Search API) |
| Feed manager frontend | Svelte + TypeScript, built with Vite |

## Architecture

### Layers

```
config.py          ← default seed feeds, app settings
db/                ← SQLite schema and queries
feeds/             ← RSS fetch + parse → store episodes; iTunes search; default-feed seeding
player/            ← python-mpd2 wrapper, playback state
network/           ← nmcli wrapper: status, scan, join, hotspot (peer of bluetooth/)
display/           ← e-ink driver, touch input, screen rendering
main.py            ← app entry point, event loop
feed_manager/      ← second entry point: Flask + Svelte web UI for managing feeds
```

### Data Flow

1. `feeds/fetcher.py` fetches feeds read from the DB (`FeedRepository.get_all()`) on startup + every N hours, writes episodes to DB
2. `player/controller.py` wraps MPD: stream URL, play/pause/stop/seek
3. `display/` renders a PIL image → pushes to e-ink; touch events → UI events → state machine
4. `main.py` wires it all together and runs the poll loop: touch → `ScreenManager.handle_touch` → display update; also polls the `feeds` table every ~60s so feeds added/removed via `feed_manager/` (a separate process) show up on screen
5. `feed_manager/app.py` is a second, independent entry point — a small Flask API + a built Svelte UI — that lets you search the iTunes podcast directory and add/remove feeds from a phone/laptop on the LAN, writing to the same `pi_media.db`

### UI State Machine

Navigation is an explicit state machine, not a screen stack.

- **`display/state_machine.py`** — `AppState` enum (`HOME`, `PODCAST_LIST`, `EPISODE_LIST`, `NOW_PLAYING`, `QUEUE`, `BLUETOOTH`, `BLUETOOTH_DISCOVER`, `RADIO_LIST`, `RADIO_PLAYING`, `WIFI`) and a pure `transition(state, event, now_playing_origin) → AppState`. No side effects live here. NOW_PLAYING is reachable from more than one screen (episode list, queue), so Back from it returns to `now_playing_origin` — `ScreenManager` tracks it and passes it in, keeping `transition()` pure.
- **`display/events.py`** — frozen event dataclasses: `HomeMenuSelected(item: HomeMenuItem)`, `FeedSelected`, `EpisodeSelected`, `BackRequested`, `ListScrolled`, `PlayPauseToggled`, `SkipRequested`, `QueueToggled(episode)`, `QueueRemoveRequested(episode)`, `BluetoothDeviceSelected(device)`, `BluetoothScanRequested`, `BluetoothPairRequested(device)`, `BluetoothForgetRequested(device)`, `StationSelected(station)`.
- **`display/copy.py`** — every user-facing string, as `Final` constants. Two registers on purpose: navigation (headers, row labels) stays plain; status/empty/error notices carry the house voice. Status copy is budgeted to 3 wrapped lines (~135 chars) — longer copy is silently ellipsised.
- **Screens** (`display/screens/`) only render and translate touches into events (`handle_touch(x, y) → Event | None`). They never navigate, never touch the player, never construct other screens. `Screen` is a Protocol (`display/screens/base.py`).
- **`display/manager.py`** — `ScreenManager` drives the machine: applies each event's side effects (player commands, screen construction), calls `transition()`, and refreshes the display — **partial refresh everywhere, with a true full refresh every Nth state transition** (`_TRANSITIONS_BETWEEN_FULL_REFRESHES`) to clear e-ink ghosting without flashing on every navigation.

Transitions:

| From | Event | To |
|---|---|---|
| HOME | HomeMenuSelected(PODCASTS) | PODCAST_LIST |
| HOME | HomeMenuSelected(QUEUE) | QUEUE |
| HOME | HomeMenuSelected(BLUETOOTH) | BLUETOOTH |
| HOME | HomeMenuSelected(RADIO) | RADIO_LIST |
| HOME | HomeMenuSelected(WIFI) | WIFI (starts a background status read) |
| WIFI | BackRequested | HOME |
| RADIO_LIST | StationSelected | RADIO_PLAYING (starts the stream) |
| RADIO_LIST | BackRequested | HOME |
| RADIO_PLAYING | BackRequested (stops the stream) | RADIO_LIST |
| PODCAST_LIST | FeedSelected | EPISODE_LIST |
| PODCAST_LIST | BackRequested | HOME |
| EPISODE_LIST | EpisodeSelected | NOW_PLAYING (starts playback) |
| EPISODE_LIST | BackRequested | PODCAST_LIST |
| QUEUE | EpisodeSelected / BackRequested | NOW_PLAYING / HOME |
| BLUETOOTH | BackRequested | HOME |
| BLUETOOTH | BluetoothScanRequested | BLUETOOTH_DISCOVER (starts a background scan) |
| BLUETOOTH_DISCOVER | BackRequested (abandons the scan) | BLUETOOTH |
| BLUETOOTH_DISCOVER | BluetoothScanRequested | BLUETOOTH_DISCOVER (rescan) |
| BLUETOOTH_DISCOVER | BluetoothPairRequested | BLUETOOTH (pair + trust + connect) |
| NOW_PLAYING | BackRequested (stops playback) | `now_playing_origin` |

Radio has its own player state rather than reusing NOW_PLAYING. A live stream has no duration, position, or queue entry, so keeping it separate is what stops the episode machinery (resume-seek, mark-played, position persistence, queue auto-advance) from ever running against it — `_playing_episode` and `_playing_station` are never both set, and starting either releases the other. RADIO_PLAYING is reachable only from RADIO_LIST, so it needs no `now_playing_origin` equivalent.

`BluetoothPairRequested` returns to BLUETOOTH **unconditionally** — success is self-evident (the device shows there as Connected) and failure is a banner the manager sets, so no outcome flag has to be threaded through the pure function.

Anything else is a no-op that keeps the current state. Initial state is HOME. `QueueToggled` / `QueueRemoveRequested` / `BluetoothDeviceSelected` / `BluetoothForgetRequested` don't navigate — the manager updates the queue/bluetooth state, rebuilds the current list screen (scroll preserved), and partial-refreshes.

`display` never imports `player`, `bluetooth` or `network`: playback flows through the `AudioPlayer` / `PlaybackState` Protocols in `display/playback.py` (satisfied structurally by `PlayerController`), Bluetooth flows through the `BluetoothDevice` / `BluetoothService` Protocols in `display/bluetooth_control.py` (satisfied structurally by `BluetoothController`), and the network through `display/network_control.py` (satisfied by `NetworkController`) — read-only, so the panel can report the network but never reconfigure it. `ScreenManager` wraps player, bluetooth and network calls in a broad `except Exception` (with a why-comment) because their exception types live above the display layer — a failure degrades to a log line, never a UI crash. This is also what makes the simulator work on Windows with no MPD or `bluetoothctl`.

## Database Schema

```sql
CREATE TABLE feeds (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL UNIQUE,
    last_fetched DATETIME
);

CREATE TABLE episodes (
    id           INTEGER PRIMARY KEY,
    feed_id      INTEGER REFERENCES feeds(id),
    title        TEXT NOT NULL,
    audio_url    TEXT NOT NULL,
    published_at DATETIME,
    duration_sec INTEGER,
    played       BOOLEAN DEFAULT 0,
    play_position_sec INTEGER DEFAULT 0
);

CREATE TABLE queue (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL UNIQUE REFERENCES episodes(id),
    added_at   TEXT NOT NULL
);
```

The queue is FIFO (`ORDER BY id`, no position column). `UNIQUE(episode_id)` + `INSERT OR IGNORE` make double-queueing a no-op. Entries are removed when an episode **finishes** (auto-advance, `ScreenManager._advance_queue`), not when it starts — restarting mid-episode keeps the entry. Auto-advance only continues the queue when the finished episode was **itself queued** (see the Phase 5 amendment and the Key Note).

## Display / UI

### Key Constraints

- **296×128px** — very small; font sizes and touch targets must be deliberate
- **Full refresh** (~2s, visibly flashes a few times — inherent to the e-ink waveform) runs every 6th screen transition to clear ghosting; the first frame after boot is also full (partials need a base frame)
- **Partial refresh** (fast, flash-free) used for everything else: in-screen updates (playback progress, time) and the transitions in between
- E-ink uses Waveshare's SPI driver; touch uses I2C
- **Rotated 180° (2026-08-22)** — the HAT is mounted upside down on the shelf. `config.DISPLAY_ROTATE_180` is wired into `WaveshareDriver(rotate_180=…)` from `main.py`, and the driver flips **both** the outgoing frame (`_orient`) and the incoming touch coordinates (`_orient_touch`). Everything above the driver still works in one unrotated 296×128 space, and the **simulator is deliberately not rotated** so local development stays the right way up

### Screens

1. **Home** — root menu ("Bridget Media" header), five rows (Podcasts / Radio / Next / Wi-Fi / Bluetooth), icon left + chevron right, no back button. Uses the shared scroll sidebar since Phase 8.5: three rows fit the 128px panel, so the order deliberately puts the three listening destinations above the fold and the two setup screens — Wi-Fi then Bluetooth — below it. Its `ListScroller` is long-lived (the screen is never rebuilt), so the menu stays where it was left
2. **Podcast List** — scrollable list of feed names; tap a row to enter, tap header to go back to Home
3. **Episode List** — episodes for selected feed (title + date, ● = unplayed); tap header to go back, tap a row to play, tap the action-zone icon (+ / ✓) to toggle queue membership
4. **Now Playing** — feed name, wrapped episode title (2 lines max), publish date (same 9px size as the feed name, positioned from the *actual* wrapped line count so a one-line title leaves no gap; omitted when the feed has no date), progress bar with elapsed/total times, bottom control bar; Back returns to whichever screen started playback
5. **Next (queue)** — FIFO queue: episode title + feed name per row, remove icon in the action zone, tap a row to play (Back from Now Playing returns here); empty state (copy in `display/copy.py`, like every other user-facing string)
6. **Bluetooth** — paired-device rows (name + "Connected"/"Tap to connect", `ICON_BLUETOOTH_CONNECTED` inline on the connected one's status line); tap a row left of the action zone to connect/disconnect, tap the action-zone `ICON_LINK_OFF` to forget the device, tap the header-right **"+ search"** button (`ICON_ADD_BLUETOOTH`) to scan for new ones. Also renders the transient "Making introductions…"/"Getting cozy…" frames and the pairing-failure banner; unreachable state when there's no `bluetoothctl` (always true on Windows)
7. **Add device (Bluetooth discover)** — nearby *unpaired* devices found by a scan; whole row is the tap target (pair), header-right button rescans. Scanning / results / nobody-found / unreachable states
8. **Radio** — live stations from `config.STATIONS`; whole row tunes in, no action zone (nothing to queue). Header is the back button
9. **Radio playing** — station name centred, an `ICON_GRAPHIC_EQ` + "Live" line under it, and a two-button control bar: Back keeps Now Playing's position and width so the gesture is identical on both players, and play/pause takes the whole remainder (there is no seeking on a live stream, so the ±30s buttons have nothing to do). The player-unreachable notice replaces the "Live" line
10. **Wi-Fi** — read-only status, no list: network name with a state line under it (Connected / No internet / Setup hotspot), IP address, and `bridget.local`. Header is the back button and the body has no tap targets. Checking / offline / no-address / unreachable states; unreachable is always what Windows shows

### Layout & Touch Zones

Shared list geometry lives in `display/screens/list_layout.py`:

- **Header** — 23px black bar (title; on Episode List it's also the back button, with a back icon). An optional right-hand 48px action button (`draw_header(action_icon=…)` / `is_header_action_touch`) carries screen-level actions — currently Scan/Rescan on the Bluetooth screens — without spending one of only three visible rows
- **Status messages** — `list_layout.draw_status_message()` draws the centred icon-over-text block used by every transient/empty/error state, word-wrapped to 3 lines and vertically centred in the body. Now Playing is the exception: its error sits inline between the title and the controls, so it stays one short line
- **Rows** — 3 visible rows × 35px, finger-sized
- **Action zone** — 36px column just left of the sidebar (`ACTION_X = SIDEBAR_X - 36`), one icon button per row (episode list: queue + / ✓; queue: remove); row text clips at `ACTION_X - 12`
- **Scroll sidebar** — right-edge 36px column with up/down chevrons; chevrons only draw when scrolling that direction is possible; tap top half = up, bottom half = down; scrolls use partial refresh (no flicker)

Now Playing controls are bottom-anchored (y=95..128), four 74px-wide icon buttons: back, replay-30, play/pause (inverted black button, primary action), forward-30.

### Fonts & Icons

- **Text**: `assets/fonts/DejaVuSans.ttf`
- **Icons**: `assets/fonts/MaterialIcons-Regular.ttf` (Google Material Icons, Apache 2.0) — glyphs are `ICON_*` constants in `display/renderer.py`, codepoints verified against `MaterialIcons-Regular.codepoints` (kept alongside the font)
- Fonts load through `renderer.load_text_font(size)` / `load_icon_font(size)` (cached); `renderer.draw_icon_centered()` centers a glyph in a button rect — on *rendered ink*, not `textbbox` (see Key Notes)
- `draw_icon_centered` accepts more than one glyph: a two-glyph constant like `ICON_ADD_BLUETOOTH` (`ICON_ADD + ICON_BLUETOOTH_SEARCHING`) renders as a single run and is centred as a whole, which is how the "add device" button is built without any extra layout code
- Text wrapping goes through `renderer.wrap_lines()`; `draw_text_wrapped()` (left-aligned) and `draw_text_wrapped_centered()` (per-line centred, used by status messages) share it, so wrapping behaves identically everywhere. `wrap_lines` is also callable directly when a caller needs the line *count* to position what follows — Now Playing uses it for the publish date

## Local Development (Windows)

The Pi (1GB RAM) can't comfortably run VS Code Remote SSH, so UI development happens locally with a simulator.

### How it works

Run with `--simulate` flag (or `SIMULATE=1` env var):

```
python main.py --simulate
```

This swaps the Waveshare hardware driver for a **tkinter simulator** that:
- Opens a window showing the 296×128 display scaled up 3× (888×384px) for visibility
- Maps mouse clicks back to device coordinates for touch simulation
- Left-click = tap; no hardware dependencies needed

MPD/playback is **not simulated** — player calls will simply fail gracefully on Windows (connection refused). Develop and test all UI navigation and rendering locally; test audio on the Pi.

### Driver abstraction

Both drivers satisfy the same Protocol (`display/drivers/base.py`):

```python
class DisplayDriver(Protocol):
    def display(self, image: Image.Image) -> None: ...          # full refresh
    def display_partial(self, image: Image.Image) -> None: ...  # partial refresh
    def read_touch(self) -> list[tuple[int, int]]: ...          # touch coords (296×128 space)
    def clear(self) -> None: ...
    def close(self) -> None: ...
```

`display/drivers/waveshare.py` — wraps Waveshare EPD lib, real hardware
`display/drivers/simulator.py` — tkinter window, mouse input

## Project Structure

```
pi_media/
├── CLAUDE.md
├── .claude/skills/verify/     # project verify skill: how to run + drive the app for verification
├── .env                       # Pi SSH credentials (git-ignored)
├── requirements.txt           # runtime deps
├── requirements-dev.txt       # + mypy/ruff (local only)
├── pyproject.toml             # ruff + mypy config
├── main.py                    # entry point, DI wiring, poll loop
├── config.py                  # default seed FeedConfig list, Station list, settings
├── test_display.py            # Pi-only hardware smoke test
├── touch_zones.png            # tap-target reference for all 7 screens (generated)
├── tools/
│   └── make_touch_zones.py    # regenerates touch_zones.png from the layout constants
├── deploy/
│   ├── deploy.sh              # Windows → Pi code sync + service restart (both services)
│   ├── setup_ssh_key.sh       # one-time passwordless SSH setup
│   ├── setup_pi.sh            # on-Pi provisioning (run once per flash)
│   ├── pair_speaker.sh        # Windows → SSH: scan/pair/trust/connect + configure-speaker
│   ├── pi-media.service       # systemd unit template (player app)
│   ├── pi-media-feeds.service # systemd unit template (feed manager web app)
│   └── mpd.conf               # MPD config template (bluez-alsa + aux outputs, ffmpeg mp3 decoding)
├── db/
│   ├── __init__.py
│   ├── database.py            # connection, schema init, DatabaseError
│   ├── models.py              # Feed, Episode (frozen dataclasses)
│   └── queries.py             # FeedRepository (incl. delete), EpisodeRepository
├── feeds/
│   ├── __init__.py
│   ├── fetcher.py             # feedparser → DB, sourced from FeedRepository.get_all()
│   ├── seed.py                # seed_default_feeds() — one-time, only if feeds table is empty
│   └── itunes_search.py       # ItunesSearchClient — iTunes Search API proxy
├── player/
│   ├── __init__.py
│   └── controller.py          # python-mpd2 wrapper, PlaybackState
├── bluetooth/
│   ├── __init__.py
│   └── controller.py          # bluetoothctl subprocess wrapper, BluetoothDevice, BluetoothError
├── network/
│   ├── __init__.py
│   └── controller.py          # nmcli wrapper: NetworkStatus, WifiNetwork, NetworkError
├── display/
│   ├── __init__.py
│   ├── events.py              # typed Event dataclasses
│   ├── copy.py                # all user-facing strings (Final constants)
│   ├── state_machine.py       # AppState enum + pure transition()
│   ├── errors.py              # DisplayError (dependency-free, so drivers can raise it)
│   ├── playback.py            # AudioPlayer / PlaybackState Protocols
│   ├── bluetooth_control.py   # BluetoothDevice / BluetoothService Protocols
│   ├── network_control.py     # NetworkStatus / WifiNetwork / NetworkService Protocols (read-only)
│   ├── manager.py             # ScreenManager (drives the machine)
│   ├── renderer.py            # PIL helpers, fonts, ICON_* glyph constants
│   ├── drivers/
│   │   ├── __init__.py
│   │   ├── base.py            # DisplayDriver Protocol
│   │   ├── waveshare.py       # real e-ink + touch (Pi only)
│   │   └── simulator.py       # tkinter window (local dev)
│   └── screens/
│       ├── __init__.py
│       ├── base.py            # Screen Protocol
│       ├── list_layout.py     # shared list geometry, ListScroller, sidebar
│       ├── home.py            # root menu (Bluetooth / Podcasts / Next)
│       ├── podcast_list.py
│       ├── episode_list.py
│       ├── queue_list.py
│       ├── now_playing.py
│       ├── bluetooth_list.py
│       ├── bluetooth_discover.py
│       ├── radio_list.py        # live stations
│       ├── radio_playing.py     # live-stream player (no progress bar, no seek)
│       └── wifi_list.py         # read-only network status
├── assets/
│   └── fonts/                 # DejaVuSans.ttf, MaterialIcons-Regular.ttf (+ .codepoints)
└── feed_manager/               # second entry point: web UI for managing feeds
    ├── __init__.py
    ├── app.py                  # Flask factory + entrypoint; per-request Database via flask.g
    ├── routes.py                # Blueprint: /api/feeds (GET/POST/DELETE), /api/search
    └── frontend/                 # Svelte + TS + Vite app; built to frontend/dist/, served by Flask
        └── src/
            ├── App.svelte
            └── lib/               # api.ts, types.ts, FeedList/SearchPanel/SearchResultCard.svelte
```

## Environment Setup

| Environment | Method |
|---|---|
| Local (Windows) | conda env, Python 3.11 |
| Pi 3 Model B+ | System Python (Pi OS trixie, 3.13), no venv |

```bash
# Local setup
conda create -n pi_media python=3.11
conda activate pi_media
pip install -r requirements-dev.txt   # runtime deps + mypy/ruff

# Feed manager frontend (one-time; Node/npm never runs on the Pi)
cd feed_manager/frontend && npm install
```

On the Pi, dependencies are installed by `deploy/setup_pi.sh` (see Deployment). `requirements.txt` is runtime-only and stays the source of truth — keep the pip list in `setup_pi.sh` in sync with it. `deploy/deploy.sh` builds the frontend locally before every sync, so the Pi only ever receives the built `frontend/dist/` static output.

## Deployment

Connection details (hostname, user, password) live in `.env` — git-ignored, never commit it.

**Fresh Pi (after a reflash):**

```bash
bash deploy/setup_ssh_key.sh    # one-time: passwordless SSH (prompts for the .env password)
bash deploy/deploy.sh           # push code to ~/pi_media on the Pi
ssh <user>@<host>.local 'bash ~/pi_media/deploy/setup_pi.sh'
```

Reflash gotchas: clear the stale host key first (`ssh-keygen -R <host>.local`), and the *first* `setup_pi.sh` run needs broad sudo, which the imager-created user doesn't have by default (`echo '<user> ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/010_<user>-nopasswd`). Since Phase 9 that file can be **deleted afterwards** — step 7 installs a narrow allowlist that covers everything the running apps and `deploy.sh` need, and the blanket grant was removed on the real device on 2026-08-18. A later `setup_pi.sh` re-run will then prompt for a password, which is the intended trade.

`setup_pi.sh` is idempotent: apt packages (MPD, bluez-alsa, GPIO/SPI/I2C libs, avahi, NetworkManager), enables SPI + I2C, sets the mDNS hostname from `config.MDNS_HOSTNAME`, installs the passwordless-sudo **allowlist** (`/etc/sudoers.d/020_pi-media` — `rfkill unblock bluetooth`, `configure-speaker`, `nmcli`, and the three `systemctl restart` lines deploy.sh needs; written only if `visudo -c` accepts it), pip runtime deps (`--break-system-packages`, Pillow via apt), clones the Waveshare `Touch_e-Paper_HAT` repo and installs its `TP_lib` package (imported directly by `display/drivers/waveshare.py`; the panel class is `EPD_2IN9_V2`, touch is `icnt86.INCT86` — Waveshare's own typo), installs `/etc/mpd.conf` (Bluetooth output via bluez-alsa) and the `pi-media` systemd service. It ends by printing the two manual steps: pair the speaker with `bluetoothctl`, then `configure-speaker <MAC>` (installed helper that patches the MAC into mpd.conf), and reboot.

Speaker-pairing gotchas (hit on the real device): the BT controller ships **rfkill soft-blocked** — `sudo /usr/sbin/rfkill unblock bluetooth` before `bluetoothctl power on` will work; the device must be discovered by a `bluetoothctl scan` before `pair` accepts its MAC (an `hcitool scan` sighting isn't enough); and `configure-speaker` restarts MPD, which the app heals from via auto-reconnect. Current speaker: EarFun UBOOM L, paired + trusted 2026-07-11.

**Iterating:** `bash deploy/deploy.sh` — tar-over-ssh sync (excludes caches, `.env`, the DB) + service restart. Deleted files are not removed on the Pi. App logs: `journalctl -u pi-media -f`.

Shell scripts, `.service`, and `.conf` files are forced to LF via `.gitattributes` — they execute on the Pi, and CRLF breaks bash there.

## Coding Standards

### Python Version
Target **Python 3.11+**. Use modern syntax throughout — no compatibility shims.

### Type Annotations
- Every function has fully annotated parameters and return types. No exceptions.
- Every class attribute is annotated.
- Use `X | None` not `Optional[X]`. Use `list[X]`, `dict[K, V]` not `List`, `Dict`.
- Use `typing.Protocol` for structural interfaces (e.g. `BaseDriver`), not ABC.
- Use `typing.Final` for constants in `config.py`.
- Run `mypy --strict` as the type-checking bar. Code must pass clean.

### Data Models
- `Feed`, `Episode`, `PlaybackState` and any other value objects are `@dataclass(frozen=True)`.
- Frozen = immutable after construction. If you need to update state, return a new instance.
- Dataclasses live in their layer's module, not in a shared `models.py` — they belong to the layer that owns them.
- No raw `dict` passed between layers. Always a typed dataclass.
- Bring in `pydantic` only if runtime validation or serialization complexity demands it.

### Interfaces / Protocols
```python
# Good
class DisplayDriver(Protocol):
    def display(self, image: Image.Image) -> None: ...

# Avoid
class DisplayDriver(ABC):
    @abstractmethod
    def display(self, image: Image.Image) -> None: ...
```
Protocols are preferred — they allow structural typing without forcing inheritance.

### Dependency Injection
Nothing instantiates its own dependencies. Dependencies flow in via constructor.

```python
# Good
class ScreenManager:
    def __init__(self, driver: DisplayDriver, db: Database) -> None:
        self._driver = driver
        self._db = db

# Bad
class ScreenManager:
    def __init__(self) -> None:
        self._driver = WaveshareDriver()   # hard-coded, untestable
        self._db = Database()
```

`main.py` is the only place that constructs concrete implementations and wires the graph together.

### Layer Hierarchy (strict — no upward imports)

```
config          (constants only, no imports from project)
    ↓
db                        (knows config, knows nothing else)
    ↓
feeds / player / bluetooth / network (know db, know config — bluetooth and network need neither, they only shell out)
    ↓
display                  (knows feeds/player/bluetooth/network through injected interfaces, never imports them directly)
    ↓
main / feed_manager       (two independent entry points; feed_manager knows only db + feeds, not display/player/bluetooth — it gains network in Phase 10)
```

A layer must never import from the layer above it. If you feel the urge to do so, the logic belongs in a different layer.

### Error Handling
- Each layer defines its own exception types:
  ```python
  class FeedFetchError(Exception): ...
  class DatabaseError(Exception): ...
  class PlayerError(Exception): ...
  class BluetoothError(Exception): ...
  class NetworkError(Exception): ...
  class DisplayError(Exception): ...
  ```
- Raw library exceptions (`mpd.ConnectionError`, `sqlite3.OperationalError`, etc.) are caught at the layer boundary and re-raised as the layer's own type.
- Never silently swallow exceptions. Log and re-raise, or handle explicitly with a comment explaining why.
- `main.py` is responsible for top-level error handling and user-visible error states.

### Naming
- Classes: `PascalCase`. Functions/methods/variables: `snake_case`. Constants: `UPPER_SNAKE`.
- Names are complete words — no abbreviations (`episode` not `ep`, `database` not `db` as a type name).
- Methods named for what they do: `fetch_episodes()`, `render_now_playing()`, `connect()`.
- Booleans prefixed: `is_playing`, `has_been_played`.

### Module / Import Style
- Absolute imports only. Never relative (`from .foo import bar`).
- Import groups separated by blank lines: stdlib → third-party → project-local.
- No star imports (`from x import *`).

### General Rules
- No mutable module-level state. `config.py` is `Final` constants only.
- No magic numbers — named constants for anything non-obvious (buffer sizes, refresh intervals, display dimensions).
- Prefer pure functions. If a function doesn't need `self`, it probably shouldn't be a method.
- Short functions. If you need to scroll to read a function, it should be split.
- No comments that describe *what* the code does — the code does that. Comments explain *why* when the reason is non-obvious.

### Tooling
- **`ruff`** — linting and formatting. Configured in `pyproject.toml`.
- **`mypy --strict`** — type checking. Must pass clean before any code ships to the Pi.

```toml
# pyproject.toml
[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.11"
strict = true

# Untyped third-party libs (and the Pi-only waveshare_epd) are exempted via
# [[tool.mypy.overrides]] with ignore_missing_imports — everything else passes strict.
```

Run from the repo root (`test_display.py` needs the Pi-only waveshare lib, so exclude it locally):

```bash
python -m ruff check .
python -m mypy --strict . --exclude test_display.py
```

## Development Phases

### Phase 1 — Core ✅ COMPLETE (2026-07-10)
- [x] DB schema + queries
- [x] Feed fetcher (feedparser → SQLite)
- [x] MPD controller wrapper (play URL, pause, resume, seek)
- [x] Display driver base + tkinter simulator
- [x] Three screens: podcast list → episode list → now playing
- [x] Playback controls on now-playing screen (Material Icons buttons, ±30s skip)
- [x] UI navigation as an explicit state machine (see "UI State Machine" above)
- [x] Fonts: DejaVu for text, Material Icons for symbols
- [x] Scroll support on both list screens (sidebar chevrons, partial refresh)
- [x] `mypy --strict` + `ruff` pass clean; navigation and rendering verified end-to-end in the simulator

**Hardware bring-up (2026-07-11)** — first Pi deployment done: app boots on the device, e-ink driver initializes (after rewriting `waveshare.py` against TP_lib's real API — `EPD_2IN9_V2` + ICNT86 touch, not the guessed `EPD`/GT1151), and MPD connects on localhost. Audio out verified same day (see Phase 2). Touch works in practice (navigation/playback driven by taps on the panel); partial-refresh quality when scrolling hasn't been explicitly assessed.

### Phase 2 — Polish ✅ COMPLETE (2026-07-11)
- [x] Episode played/unplayed tracking — `ScreenManager._mark_played_if_past_threshold()` (called from `refresh_playback()`) marks an episode played once 90% heard (`_PLAYED_FRACTION_THRESHOLD`); on Back from Now Playing the episode screen is rebuilt from the repository (scroll position preserved via `EpisodeListScreen.scroll_offset`) so the ● marker updates
- [x] Resume from last position — position persisted every 30s from `refresh_playback()` (`_POSITION_PERSIST_INTERVAL_SEC`, throttled to limit SD writes) plus immediately on pause and on Back; `seek()` (now on the `AudioPlayer` Protocol) is issued right after `play()` when `play_position_sec > 0` and the episode isn't played; marking played resets the stored position to 0 so replays start fresh. Seek-right-after-play confirmed against live MPD on-device (2026-07-11). Caveat: ad-stitched feeds (WNYC) regenerate the stream per session, so a resumed position can land ±a few seconds off
- [x] Mid-session data refresh — the fetch job sets a `threading.Event` (wired in `main.py`); the main loop calls `ScreenManager.reload_feeds()` on the UI thread, which re-queries feeds, preserves scroll, and partial-refreshes only if the podcast list is showing. Covers both first-boot fill-in and the 4h background refresh
- [x] Faster startup — the startup fetch no longer blocks: the scheduler job runs with `next_run_time=now` in its own thread and the UI comes up from the DB immediately; the fetch-completed event above fills the list in afterwards
- [x] Error states on screen — when `get_state()` raises, `NowPlayingScreen` draws an "MPD unreachable" notice (error icon + text) in place of the progress bar/times; controls stay visible so Back still works

**Audio verification (2026-07-11)** — EarFun UBOOM L speaker paired/trusted and set as MPD output via `configure-speaker`; live playback, ±30s skips, pause/resume, and resume-from-position all confirmed on the device (after the player-layer fixes in Key Notes below). A failed player command degrades to a log line by design, which on-screen looks like a dead button — check `journalctl -u pi-media` before assuming a touch problem.

### Phase 3 — Home Menu + Navigation Rework ✅ COMPLETE (2026-07-12)
- [x] Root `HomeScreen` (`display/screens/home.py`): three rows — Bluetooth, Podcasts, Next — icons + chevrons, reusing list geometry
- [x] `AppState` gains `HOME` (new initial state), `QUEUE`, `BLUETOOTH`; `transition()` gains the `now_playing_origin` parameter (see UI State Machine)
- [x] `HomeMenuItem` / `HomeMenuSelected` events; podcast list header is now a back-to-home button
- [x] New icons: `ICON_BLUETOOTH`, `ICON_PODCASTS`, `ICON_QUEUE_MUSIC`, `ICON_CHEVRON_RIGHT`
- Tapping Bluetooth/Next on Home is a deliberate no-op until Phases 4/6 add their transition arms

### Phase 4 — Episode Queue ✅ COMPLETE (2026-07-12)
- [x] `queue` table appended to `_SCHEMA` (`CREATE TABLE IF NOT EXISTS` runs every boot — new tables need no migration): `id INTEGER PK AUTOINCREMENT, episode_id INTEGER NOT NULL UNIQUE REFERENCES episodes(id), added_at TEXT NOT NULL`
- [x] `QueueEntry(id, episode, feed_name, added_at)` frozen dataclass; `QueueRepository`: `add` (INSERT OR IGNORE), `remove`, `get_entries` (JOIN episodes+feeds, ORDER BY q.id — FIFO, no position column), `first_entry`, `queued_episode_ids`; plus `FeedRepository.get_by_id`
- [x] Episode list + button: `ACTION_X = SIDEBAR_X - 36` zone in `list_layout.py`; toggles queue membership via `QueueToggled(episode)` (`ICON_PLAYLIST_ADD e03b` ↔ `ICON_PLAYLIST_ADD_CHECK e065`); titles clip at `ACTION_X - 12`
- [x] `QueueListScreen` (`display/screens/queue_list.py`): title + feed-name rows, `ICON_REMOVE_CIRCLE_OUTLINE e15d` in action zone → `QueueRemoveRequested`, row tap → `EpisodeSelected`, header "Next" with back icon
- [x] Manager: `queue_repository` dep; extracted `_start_episode(episode)` (feed name via `get_by_id`, not `_selected_feed` — queue playback has no selected feed); Back-from-NOW_PLAYING rebuilds episode **or** queue screen per `_now_playing_origin`; `QueueToggled | QueueRemoveRequested` join the partial-refresh event tuple
- [x] Queue entries are removed on natural finish, not on start (restart mid-episode keeps the entry) — removal side landed with Phase 5's auto-advance
- [x] Verify-skill coords: action zone at (240, 40)/(240, 75)/(240, 110)
- Verified via scripted-touch harness (18 checks: toggle on/off, FIFO order, feed-name join, remove, play-from-queue with correct URL, origin-aware Back both ways) + simulator smoke run; ruff + `mypy --strict` clean

**Queue hardening (2026-07-13)** — fixed an intermittent hard crash when tapping + during an active feed fetch. Root cause: one shared `sqlite3.Connection` used by both the UI thread and the APScheduler fetch thread — concurrent statements corrupt the connection and raise `SystemError` (not a `sqlite3.Error`, so repository handlers never catch it). Fixes, all verified by a scripted concurrent-writer harness that reproduced the original crash:
- `main.py` opens a **second `Database`** for the fetcher; each connection stays single-threaded (see Key Notes)
- `Database` sets `journal_mode=WAL`, `busy_timeout=5000`, and `isolation_level="IMMEDIATE"` — IMMEDIATE takes the write lock at BEGIN so a colliding write waits out the timeout instead of failing instantly with `BUSY_SNAPSHOT` (without it, most UI writes during a fetch burst still failed "database is locked")
- Queue side effects in the manager go through `_queue_command` (mirrors `_player_command`): a residual `DatabaseError` degrades to a log line, not a UI crash
- `ScreenManager.handle_touch` debounces: taps within `_TOUCH_DEBOUNCE_SEC` (300ms) of the last are ignored. Capacitive jitter can emit one physical tap as two events (the driver's held-finger filter only matches exact coordinates), and a double-fire on a toggle silently undoes it

### Phase 5 — Auto-Advance ✅ COMPLETE (2026-07-13 — simulator-verified; confirm on Pi with real MPD)
- [x] `PlaybackState.is_stopped` (MPD `state == "stop"`) in `player/controller.py` + the `display/playback.py` Protocol
- [x] Natural-finish rule (`_is_natural_finish`): current poll `is_stopped` AND previous poll `is_playing` with `elapsed/duration ≥ _PLAYED_FRACTION_THRESHOLD` (manager keeps `_last_playback_state`; reset on stop/new episode). Immune to decode-failure stops (far from end) and user Back (clears `_playing_episode` first)
- [x] `refresh_playback()` restructure: `_poll_playback()` runs whenever `_playing_episode` is set (any screen), `_show` only on NOW_PLAYING — fixes mark-played/persist silently stopping off-screen; `_persist_position_throttled` guarded with `is_playing` so a stopped state (elapsed 0) can't zero a saved position
- [x] `_advance_queue()`: remove finished from queue, defensively mark played (shared `_mark_episode_played` helper), `first_entry()` → `_start_episode`; rebuilds QUEUE/EPISODE_LIST screen if showing (NOW_PLAYING is replaced by `_start_episode` and redrawn by the poll's trailing `_show`). Wrapped in `except DatabaseError` — a DB hiccup logs, doesn't kill the loop, and can't re-fire (`_playing_episode` cleared first)
- Verified via 26-check scripted-touch harness (queue playback → two consecutive natural finishes → queue drained; decode-failure immunity; stopped-poll position guard; user-Back immunity) + simulator smoke run; ruff + `mypy --strict` clean

**Amended 2026-08-23 — auto-advance is gated on queue membership.** As shipped, *any* natural finish started `first_entry()`, queue-started or not. Reported from real use and confirmed in the Pi's journal: an episode picked straight from the episode list finished, and a single forgotten queue entry — an already-played episode from an unrelated feed — began playing unasked. `_advance_queue` now reads membership first (`_is_queued`, which counts a DB read failure as *not* queued: skipping the advance is the safe wrong answer) and only continues the queue when the finished episode was in it. The finished entry is still dropped either way, and mark-played is untouched. Membership rather than a playback-origin flag on purpose — starting a queued episode by tapping it in the *episode list* is a normal thing to do, and must still chain. Verified by a 17-check scripted-touch harness, including a negative control that reverses the gate and reproduces the original report.

### Phase 6 — Bluetooth Screen + Pairing Script + Aux Output ✅ COMPLETE (2026-07-13 — Pi-verified)
- [x] `bluetooth/controller.py`: `BluetoothController`, `BluetoothError`, frozen `BluetoothDevice(mac, name, is_connected)`; `bluetoothctl` via `subprocess.run(..., timeout=…)` — `devices Paired` (fallback `paired-devices`), `info <MAC>` → "Connected: yes", `connect` (20s), `disconnect` (10s)
- [x] `display/bluetooth_control.py`: `BluetoothDevice` + `BluetoothService` Protocols (mirrors `playback.py`); the service method returns `Sequence[BluetoothDevice]` rather than `list[...]` — `list` is invariant, so a concrete `list[bluetooth.controller.BluetoothDevice]` wouldn't satisfy a `list[Protocol]`-typed return under `mypy --strict`. Manager gets a `_bluetooth_command` wrapper (broad `except Exception` → log line, mirrors `_player_command`)
- [x] `activate_device` = connect + `sudo -n /usr/local/bin/configure-speaker <MAC>` (MPD restart heals via `PlayerController._execute`'s existing reconnect); `ScreenManager._show_bluetooth_connecting` draws a "Connecting…" partial frame *before* the blocking call — the one spot that deviates from the normal one-redraw-after-side-effects flow, since the block is ~20s
- [x] `BluetoothScreen` (`display/screens/bluetooth_list.py`): device rows, `ICON_BLUETOOTH_CONNECTED` on the connected one; tap unconnected → switch (via `activate_device`), tap connected → disconnect; whole row is the tap target (no separate action-zone icon, unlike queue/episode lists); "Bluetooth unreachable" error state and an empty state pointing at `deploy/pair_speaker.sh`
- [x] `deploy/pair_speaker.sh` (Git Bash → SSH, deploy.sh conventions): `sudo rfkill unblock bluetooth` → `power on` → `--timeout 15 scan on` (required before `pair` accepts the MAC) → `pair`/`trust`/`connect` → `configure-speaker`; `--scan` mode just lists MACs
- [x] Aux mirror: second `audio_output` in `deploy/mpd.conf` — `type "alsa"`, `device "plughw:CARD=Headphones"` (card-by-name is reboot-stable), `mixer_type "software"`; `setup_pi.sh` gets an idempotent append (grep-guard + `tee -a` + mpd restart) because the no-clobber MAC guard stops template updates reaching a configured Pi; decoder blocks untouched
- [x] `setup_pi.sh`: `bluetooth` added to the existing `usermod -aG spi,i2c,gpio "$RUN_USER"` line — needed because `bluetoothctl connect` runs as the app user, unlike `configure-speaker` which runs via passwordless sudo
- [x] On Windows the Bluetooth screen shows the "Bluetooth unreachable" error status (no `bluetoothctl`) — expected, verified via the scripted-touch harness's `raise_on_list` case

**Pi verification (2026-07-13)** — `deploy/deploy.sh` + a re-run of `setup_pi.sh` (idempotent) confirmed: `mike_pi` gained the `bluetooth` group, the aux `audio_output` block landed in `/etc/mpd.conf`, and `pi-media`/`mpd` both stayed healthy through the re-provision. `BluetoothController` exercised directly over SSH against the real `bluetoothctl` and the already-paired EarFun UBOOM L: `list_paired_devices()` correctly reported it connected, `disconnect_device()` flipped it to disconnected, and `activate_device()` (connect + `configure-speaker`, which restarts MPD) reconnected it — `PlayerController` healed from the MPD restart with no errors in `journalctl`. Interactive pairing via `pair_speaker.sh` wasn't exercised since the speaker was already paired+trusted; that path remains to be run the next time a new device is paired.

### Phase 7 — Feed Manager Web App ✅ COMPLETE (2026-07-13 — simulator-verified; confirm on Pi)
- [x] **Architectural fix**: `FeedFetcher.fetch_all()` used to iterate `config.FEEDS` directly and re-`upsert` it every cycle, so the `feeds` DB table was just a mirror of the hardcoded list and nothing ever removed a row. Now `fetch_all()` loops `FeedRepository.get_all()` (DB is the source of truth); `feeds/seed.py`'s `seed_default_feeds()` inserts `config.FEEDS` only once, on first boot (early-returns if the table is non-empty) — compatible with the documented "wipe `pi_media.db*` freely" dev workflow, since a wipe re-seeds automatically. Deleting a feed via the web app is now permanent.
- [x] `feeds/fetcher.py`: private `_fetch_one(FeedConfig)` became public `fetch_one(name, url) -> Feed`, called by both `fetch_all()` and the web app's add-feed endpoint (immediate episode population instead of waiting up to `FEED_REFRESH_INTERVAL_HOURS`)
- [x] `db/queries.py`: `FeedRepository.delete(feed_id)` — cascades to `queue` then `episodes` in one transaction, since `episodes`/`queue` have no `ON DELETE CASCADE` and `PRAGMA foreign_keys = ON` is set
- [x] `feeds/itunes_search.py`: `ItunesSearchClient` — no-auth proxy to `itunes.apple.com/search`, `ItunesSearchError`, frozen `PodcastSearchResult` (name, artist_name, feed_url, artwork_url)
- [x] `feed_manager/` — a second, independent entry point (not a new layer; composes `db`/`feeds` exactly like `main.py`, no `display`/`player`/`bluetooth`). `app.py`: `create_app()` factory, serves the built Svelte `frontend/dist/` as static files (`static_url_path=""`, no SPA router needed — single page), opens one `Database(config.DB_PATH)` per request via `flask.g` (`before_request`/`teardown_request`) so no connection crosses Flask's request-handling threads. `routes.py`: Blueprint with `GET/POST /api/feeds`, `DELETE /api/feeds/<id>`, `GET /api/search`. Runs single-threaded (`threaded=False`) — a deliberate simplicity call for a single-user, LAN-only tool rather than adding a WSGI server dependency
- [x] **Cross-process DB safety**: Flask is a separate *process* from `pi-media`, not a thread — architecturally identical to the existing UI-thread/fetcher-thread split, just at the process level (if anything safer, since no Python object crosses a thread boundary). WAL + `busy_timeout=5000` + `isolation_level="IMMEDIATE"` (the same fix from the Phase 4 queue-crash incident) already handle two independent connections writing to the same file
- [x] `main.py`: calls `seed_default_feeds(feed_repo)` once at startup; the poll loop gets a `_FEED_POLL_INTERVAL_SEC` (60s) check comparing the feed-id set against a cached copy, calling the existing `ScreenManager.reload_feeds()` on a change — this is how feeds added via the web app (a separate process with no shared in-memory state) reach the e-ink screen without a restart
- [x] Frontend: Vite + Svelte 5 + TypeScript, no client-side router (single page: search panel + current-feeds list), no ESLint/Prettier setup yet. `vite.config.ts` proxies `/api` to the Flask backend in dev (`VITE_API_TARGET`, default `http://localhost:8000`); production serves everything from Flask, so **no Node/npm dependency on the Pi** — the frontend is built once locally (`npm install` one-time, then `npm run build`, or automatically via `deploy/deploy.sh`) and only `frontend/dist/` is deployed
- [x] `deploy/pi-media-feeds.service` mirrors `pi-media.service` (`@USER@`/`@APP_DIR@` substitution, `ExecStart=/usr/bin/python3 -m feed_manager.app`, no MPD dependency); `setup_pi.sh` installs `Flask`/`requests` and enables the new service (step 7); `deploy.sh` builds the frontend before syncing and restarts both services (each guarded independently, since either may not be installed yet on a first deploy)
- Verified end-to-end in the simulator: ran `main.py --simulate` and `feed_manager/app.py` concurrently against the same dev DB, added a feed through the real Flask API (iTunes search proxy confirmed against the live API separately), and confirmed `main.py`'s new poll loop picked up the change and called `reload_feeds()` (`3 feeds` → `4 feeds` in the log) within the 60s window with zero shared in-memory state between the two processes; delete/cascade returned `204`. `ruff` + `mypy --strict` clean; `npm run check` (svelte-check + tsc) and `npm run build` clean.

**Feed-URL hardening (2026-08-08)** — `POST /api/feeds` passed its URL straight to `feedparser.parse()`, which accepts a filesystem path or `file://` URL as readily as an `http` one, making the unauthenticated web app a local-file-read and internal-port-scan primitive. `feeds/fetcher.py` gained `_validate_feed_url` (scheme must be `http`/`https`) called from `fetch_one` *before* the upsert, so a rejected URL leaves no feed row; `InvalidFeedUrlError` subclasses `FeedFetchError` so `fetch_all`'s handler still catches it while `routes.py` can answer `400` instead of `502`. Verified with an 11-check script (`file://`, bare POSIX and Windows paths, `ftp`/`gopher`, empty and whitespace URLs all rejected with no rows created; `http`/`https`/mixed-case accepted through to the fetch). The rest of the review that prompted this is in "Security posture" under Phases 9–10.


### Phase 8 — On-Device Bluetooth Pairing ✅ COMPLETE (2026-08-02 — simulator-verified; deployed and **partially** Pi-verified)

Phase 6 could only connect to devices already paired from a laptop via `deploy/pair_speaker.sh`. Pairing a new speaker now happens entirely on the panel.

- [x] `bluetooth/controller.py`: `scan_for_devices()` (rfkill unblock → `power on` → `--timeout 15 scan on` → `devices` minus paired MACs), `pair_device()` (`pair` + `trust`), `forget_device()` (`remove`). Module-level `_parse_device_lines` is shared with `list_paired_devices`; `_is_placeholder_name` drops rows bluetoothctl named `AA-BB-CC-…` after its own MAC — without it a scan is mostly unreadable BLE beacons
- [x] **Only "Just Works" pairing.** `bluetoothctl` runs non-interactively, so a device demanding a PIN or numeric confirmation fails rather than hanging; the on-screen banner points at `pair_speaker.sh`, which stays the fallback. Rendering a keypad on 296×128 was never on the table
- [x] `AppState.BLUETOOTH_DISCOVER` + `BluetoothScanRequested` / `BluetoothPairRequested` / `BluetoothForgetRequested`; `BluetoothDiscoverScreen`
- [x] **The scan is the one bluetooth call on a background thread** (`ScreenManager._start_scan` → daemon `threading.Thread` → `queue.Queue` → `poll_background_work()`, called each tick from `main.py`). Safe because the worker only shells out to `bluetoothctl`: it touches no sqlite connection (so the Phase 4 one-connection-per-thread rule isn't in play) and never draws — results cross back as plain frozen dataclasses and all rendering stays on the UI thread. Daemon, not `ThreadPoolExecutor`, so Ctrl-C never waits out a 15s scan. A `_scan_generation` counter drops the result of a scan the user backed out of
- [x] **Pair/connect/disconnect/forget stay blocking**, with a status frame drawn first (the Phase 6 pattern). They're modal by nature — a tap must not land on another device mid-pair. `_show_screen()` was split out of `_show()` for exactly this: pairing draws the BLUETOOTH screen while `_state` still says BLUETOOTH_DISCOVER
- [x] `_bluetooth_command` now returns `bool` so the pair path can branch to the failure banner
- [x] Header-right action button (`draw_header(action_icon=…)`, `is_header_action_touch`) and the shared `draw_status_message` both live in `list_layout.py`; `renderer.wrap_lines` was extracted so `draw_text_wrapped` and the new `draw_text_wrapped_centered` share one wrap implementation
- [x] Paired rows gained an `ICON_LINK_OFF` forget button in the action zone; the connected marker moved to the status line to make room. No confirm dialog — recovery is now one scan away
- [x] **Latent bug fixed:** taps buffered during a multi-second blocking bluetooth call used to replay against whatever screen came up next. `_drain_touches()` discards them after every modal block, including the pre-existing connect path
- [x] Copy centralized into `display/copy.py` and rewritten in a Gossip Girl register (status/error notices only; navigation labels stay plain). Fixed stale copy while there: the empty podcast list said "add feeds in config.py", which Phase 7 made wrong
- Verified via a 27-check scripted-touch harness (scan → results excluding paired devices, Back mid-scan discarding a late result, rescan-while-scanning ignored, pair success/failure, forget, empty + unreachable states, touch drain) plus rendered-frame review of all eight states and a simulator run; `ruff` + `mypy --strict` clean

**Follow-up fixes from first use on the device (2026-08-02, same day)** — all in the second Phase 8 commit:
- The header search button didn't read as "add a device". It now shows `ICON_ADD_BLUETOOTH` ("+" then the search glyph) and the header action zone widened 36px → 48px to hold the pair legibly — which also enlarges the tap target for the one control a new user has to find.
- **Every icon in the app was drawing 1–4px high** (see Key Notes) — reported as "the back arrow looks misaligned", but the back arrow was just the most visible instance. Fixed at the root in `draw_icon_centered`, plus the header bar's off-by-one. This moved icons on every screen; Home, Now Playing and the list screens were re-rendered and reviewed afterwards.
- Now Playing gained the episode publish date under the title.
- `touch_zones.png` replaced with a generator (see Key Notes) — the committed image had been stale since Phase 1.

**Pi verification (2026-08-02, partial)** — deployed; `pi-media`, `pi-media-feeds` and `mpd` all healthy through the restart and MPD reconnected cleanly. `BluetoothController` exercised over SSH against the real `bluetoothctl`: `list_paired_devices()` returned all three paired devices, and `scan_for_devices()` completed and found 4 nearby unpaired devices with real names — so the rfkill-unblock → `power on` → timed scan → subtract-paired path and the placeholder-name filter both work on hardware. `sudo -n rfkill` relies on the passwordless sudo the deploy tooling already requires, and raised no error.

**Still outstanding (state-changing, needs a person at the device):** `pair_device` / `forget_device` against a real device, and the on-screen touch flow — scan from the panel, then forget + re-pair a speaker entirely from the screen (exercises pair → trust → connect → `configure-speaker` → MPD restart → `PlayerController` reconnect).

Note the Pi now has **three** paired devices (EarFun UBOOM L, ACCENTUM TW, LinkBuds Fit), not the single speaker earlier phases assumed. Three exactly fills the 3 visible rows, so the sidebar still doesn't appear — pairing a fourth is what will first exercise scrolling here.

### Phase 8.5 — Live Radio (FIP) ✅ COMPLETE (2026-08-08 — simulator-verified; confirm audio on Pi)

Numbered 8.5 because it landed after Phase 8 but is unrelated to the Phases 9–10 shipping arc below, which keep their numbers.

FIP is a French public radio station streaming continuous music. It is *not* a podcast in any way the code cared about — the only shared field is a URL — so the work was almost entirely about **not** reusing the episode model:

- [x] `config.Station(name, stream_url)` + `config.STATIONS`: eight FIP webradios (main, Rock, Jazz, Groove, Monde, Nouveautés, Reggae, Électro) as `Final` constants. **No database table.** A station in `feeds` would be feedparser'd every refresh cycle (`fetch_all()` loops `FeedRepository.get_all()` since Phase 7), so stations deliberately never touch the DB. Editing the list is how stations change; injected into `ScreenManager` from `main.py`, per the DI rule
- [x] Icecast **MP3** endpoints, not the HLS `.m3u8` variants — mp3 is decoded by ffmpeg, which `deploy/mpd.conf` already forces as the only mp3 decoder (the Phase 2 seek fix). Verified all eight return `200 audio/mpeg`
- [x] `AppState.RADIO_LIST` / `RADIO_PLAYING`, `HomeMenuItem.RADIO`, `StationSelected(station)`, `RadioListScreen`, `RadioPlayingScreen`
- [x] `ScreenManager._playing_station` alongside `_playing_episode`, **never both set**. `_start_station` calls the extracted `_release_playing_episode()` (persist position, clear tracking) first, and `_start_episode` clears `_playing_station`. Without that, tuning in mid-episode would leave the episode being polled and its saved position overwritten from the radio stream's elapsed time
- [x] `refresh_playback()` redraws RADIO_PLAYING but runs no polling for it — nothing to persist, mark or advance — so the play/pause icon still follows a dropped stream
- [x] Home gained the scroll sidebar (see Screens above) and its rows were reordered
- Verified via a 23-check scripted-touch harness (home scroll + reorder, station list scroll, correct stream URL played, no seek ever issued on a live stream, pause/resume, player-unreachable state, Back stops the stream, and podcast→radio switching releasing the episode with its position persisted) plus rendered-frame review of all states, a simulator smoke run, and a regenerated `touch_zones.png`; `ruff` + `mypy --strict` clean

**Not done — track titles.** Radio France's Icecast servers send **no ICY metadata**: a request with `Icy-MetaData: 1` comes back with `icy-name` set to the filename and *no* `icy-metaint`, so there is no `StreamTitle` for MPD to expose and nothing to read from `currentsong()`. `https://www.radiofrance.fr/fip/api/live` is gone (404). The only working source found is the undocumented legacy `https://api.radiofrance.fr/livemeta/pull/<stationId>` (FIP is 7), which returns JSON song titles with no API key. Left out deliberately: it would add a polled external HTTP dependency on a device meant to run unattended. `RadioPlayingScreen._draw_status_line` is where a title would go if it is ever added.

**Audio verified on hardware (2026-08-10)** — FIP tuned in from the panel; `mpc status` shows `fipworld-midfi.mp3 [playing]` and the music was audible on the EarFun UBOOM L. Live Icecast → ffmpeg → bluez-alsa → Bluetooth speaker works end to end. Note MPD keeps streaming independently of `pi-media`, so audio continued after the app crashed — a running stream is not evidence the app is healthy.

### Display bring-up hardening ✅ COMPLETE (2026-08-10 — Pi-verified)

Found while debugging the individual-wire rewiring above (see Hardware). Not the cause of that fault — a userspace service cannot stop the Pi booting or joining Wi-Fi — but the reason it produced no evidence either way.

- [x] `WaveshareDriver.__init__` had no timeout and no error handling, giving two undiagnosable states: a **silent hang** (Waveshare's `init()` polls BUSY forever, so the process stayed alive, systemd reported it healthy and the log just stopped) or an **exception out of `main()`** and a restart loop every `RestartSec`. Bring-up now runs on a daemon thread joined with a 15s timeout and raises `DisplayError` naming the suspect wires
- [x] A missing `TP_lib` becomes `DisplayError` pointing at `setup_pi.sh`, per the catch-raw-library-exceptions-at-the-boundary rule
- [x] Driver construction moved **above** `scheduler.start()` and guarded → clean exit, and no fetch storm on restart (see Key Notes)
- [x] `pi-media.service` gained `StartLimitIntervalSec=300` / `StartLimitBurst=5`, so a hardware fault settles into `failed` rather than looping
- [x] `DisplayError` moved to `display/errors.py` so drivers can raise it without importing the manager; `display/__init__.py` re-exports it
- Verified with a 7-check fake-`TP_lib` harness (hang → timeout at the expected elapsed time, `init()` raising → cause preserved, missing import) plus a simulator smoke run; `ruff` + `mypy --strict` clean

**Pi verification (2026-08-10)** — deployed; `pi-media`, `pi-media-feeds` and `mpd` all healthy, MPD reconnected, all four feeds fetched, no errors. Startup log now shows a ~1.3s gap between "Starting Pi Media" and the scheduler lines — that gap *is* the driver being built first, which is how to confirm the reorder is live. The restart cap needed a manual unit install (see Key Notes) and reads back as `StartLimitIntervalUSec=5min` / `StartLimitBurst=5`.

---

## Shipping to Other People (Phases 9–10, plus a parked 12)

Everything up to Phase 8 assumes an engineer with SSH access sitting on the same LAN. Phases 9–10 close the gap to *handing a finished box to a non-technical friend*. The blocker is Wi-Fi: it is currently baked into the Pi image, so the device only works on the network it was imaged for.

**The chosen approach is AP fallback.** When the Pi can't reach a known network it starts its own hotspot; the owner joins it from a phone and is served the *same* Svelte app that manages feeds, on a Wi-Fi view. The e-ink panel is what makes this better than a headless IoT box: it can state the hotspot name, show a join QR, and confirm success — so the flow never depends on captive-portal auto-detection working.

Three decisions that shape all three phases:

- **`network/` is a peer of `bluetooth/`**, not a new layer. It shells out to `nmcli` exactly as `bluetooth/controller.py` shells out to `bluetoothctl`, knows nothing above it, and is therefore importable by *both* entry points — `main.py` (to render status) and `feed_manager/` (to provision). Unlike sqlite, concurrent access is safe: `nmcli` is a thin D-Bus client and NetworkManager serializes requests. `display/` still never imports it — a `NetworkService` Protocol in `display/network_control.py` mirrors `display/bluetooth_control.py`.
- **The watchdog owns the hotspot; the app only displays.** A tiny systemd-timed `python -m network.watchdog` decides when to raise and drop the AP. If it lived in `main.py`'s poll loop, a crashed player app would also mean no way to fix the Wi-Fi — the exact failure that strands a friend. Keeping the decision out of the UI process also keeps `display/` read-only with respect to the network.
- **One web app, two entry surfaces.** The captive portal is not a separate page; it is `feed_manager/`'s existing Svelte bundle opening on its Wi-Fi view. Same build, same deploy, same CSS variables in `app.css`, same `api.ts` error handling. That is what "uniform experience" means here — a friend sees one Bridget Media web app whether they are joining a network or adding a podcast.

### Security posture (applies to Phases 9–10 and the parked 12)

Everything through Phase 8 was priced against one threat model: **a LAN the owner controls, with an engineer on it**. The worst case was a housemate deleting a feed. Phase 10 changes that model in three ways at once — the same unauthenticated app starts accepting **the owner's Wi-Fi password**, moves to **port 80**, and runs in **a house nobody can SSH into**. The trade-offs that were reasonable before have to be re-priced, not inherited.

This is a personal-scale IoT device, not a product, so the bar is *the basics done deliberately* rather than defence in depth. Concretely:

- **Never put a secret in an exception message.** `bluetooth/controller.py`'s `_run()` raises `BluetoothError(f"bluetoothctl {' '.join(args)} failed")`, and Phase 9 says to mirror that shape for `nmcli` — which would put the Wi-Fi password into the journal *and* into the HTTP response, since `routes.py` answers `{"error": str(exc)}`. Wrong-password is the most likely failure in the whole join flow, so this fires on the common path. `network/controller.py`'s `_run()` takes a redaction list, or the secret goes via a connection profile / stdin rather than argv (argv is also world-readable in `ps`). See the Key Note.
- **Provisioning is reachable only from the hotspot.** The Wi-Fi endpoints reject requests unless `is_hotspot_active` — which the API already reports for the frontend's default-tab logic, so it's one guard clause. This is the structural control that replaces adding logins: a guest on the home LAN can meddle with podcasts but cannot touch network config.
- **Serve the web app with `waitress`, not `app.run()`.** Werkzeug's dev server is explicitly not for production, and Phase 9 hands it port 80 plus `CAP_NET_BIND_SERVICE`. Pure Python, no compile step on the Pi. It also retires the Phase 7 `threaded=False` call, where one slow feed fetch blocks the whole app.
- **Narrow the passwordless sudo grant.** The deploy tooling currently requires `NOPASSWD: ALL`, so compromising the app user is root. Phase 9 adds `nmcli` (which genuinely needs root) — that is the moment to replace it with an allowlist: `rfkill`, `configure-speaker`, `nmcli`, `systemctl restart mpd`.
- **Harden both systemd units.** `NoNewPrivileges=yes`, `PrivateTmp=yes`, `ProtectHome=yes` are free. `ProtectSystem=strict` + `ReadWritePaths=@APP_DIR@` is easy on `pi-media-feeds`; on `pi-media` it needs care because of SPI/I2C/GPIO device access.
- **Accepted, consciously:** the portal takes credentials over plain HTTP. There is no cert for `10.42.0.1` and TLS would only produce warnings that train people to click through. It is encrypted at layer 2 by the hotspot's own WPA2, so the exposure is to someone who already has the AP password. Acceptable *because* the AP is WPA2 and short-lived — which is what makes the AP lifetime cap in Phase 10 a security control, not a nicety.

Not a concern, checked rather than assumed: `db/queries.py` is fully parameterized (no SQL injection), and `.env` is gitignored and has never appeared in git history.

### Phase 9 — Network Layer + Wi-Fi Status Screen ✅ COMPLETE (2026-08-18 — Pi-verified)

Foundation only: read network state, show it, make the box findable. No provisioning yet.

- [x] `network/controller.py` — `NetworkController`, `NetworkError`, frozen `NetworkStatus(is_online, ssid, ip_address, is_hotspot_active)` and `WifiNetwork(ssid, signal, is_secured, is_known)`. All via `subprocess.run(["nmcli", "-t", "-f", …], timeout=…)` with `-t` (terse) for parsing. Methods: `get_status()`, `scan_networks()`, `join_network(ssid, password, is_hidden)`, `forget_network(ssid)`, `start_hotspot(ssid, password)`, `stop_hotspot()`; `HOTSPOT_CONNECTION_NAME` is a `Final` so Phase 10 raises and drops the same profile. Mirrors `bluetooth/controller.py`'s shape: module-level `Final` timeouts, one private `_run()`, module-level pure parse helpers. `is_online` is `CONNECTIVITY == "full"` only — "limited"/"portal" is an associated link with no route, which the screen reports differently
- [x] Escape hatches handled from day one, and all confirmed against a real 24-network scan: **hidden SSIDs** (empty SSID, dropped — manual entry is Phase 10's job), **WPA3** (present in the wild here; nmcli's own failure is surfaced), **duplicate SSIDs** across bands (collapsed to the strongest sighting, so one router isn't two rows), and SSIDs containing `:` (`_split_terse` unescapes `\:` and `\\` rather than naively splitting)
- [x] `display/network_control.py` — `NetworkStatus` / `WifiNetwork` / `NetworkService` Protocols, returning `Sequence[WifiNetwork]`. Deliberately **read-only**: the panel reports the network and can never reconfigure it, which is also why no `_network_command` wrapper exists yet — nothing in `display` issues a network *command*. It lands in Phase 10 with the manual hotspot trigger
- [x] `AppState.WIFI` + a Home row, ordered Podcasts / Radio / Next / **Wi-Fi** / Bluetooth — the two setup screens fall below the fold, Wi-Fi first because when both are wrong the network is what to fix first
- [x] `WifiScreen` (`display/screens/wifi_list.py`) — three rows: network name with a state line under it (the Bluetooth row idiom), IP address, and `bridget.local`. States: checking / connected / **associated-but-no-internet** / hotspot-active / offline / no-address / unreachable. On Windows there is no `nmcli`, so the simulator shows unreachable — same as Bluetooth
- [x] Status reads go off-thread via the Phase 8 rule (nmcli only, no sqlite, no drawing) through a second `queue.Queue` drained by the same `poll_background_work()`; `_status_generation` discards the result of a check the user backed out of
- [x] **mDNS**: `setup_pi.sh` sets the hostname from `config.MDNS_HOSTNAME`, so the screen, the Host allowlist and avahi cannot disagree, and prints a loud warning when it changes (the deploy tooling still points at the old name)
- [x] **Feed manager moved to port 80** under `waitress`, with `AmbientCapabilities=CAP_NET_BIND_SERVICE` instead of root. `config.FEED_MANAGER_PORT` stays the source of truth; `--port 8000` is the local-dev escape hatch the Vite proxy expects
- [x] Security: `_run()` redaction, the sudoers allowlist, and systemd hardening on both units — see "Security posture" and the Key Notes
- [x] `Host` header allowlist: named hosts plus any private/loopback/link-local **IP literal** (the LAN address changes with the router, so addresses are allowed by range, names are not). A rebinding-style `Host: evil.example.com` gets 403 — verified against the deployed Pi
- [x] All user-facing strings in `display/copy.py`, checked by rendering
- Verified by a 46-check harness (terse parsing incl. escaped colons, dedupe, hidden/known/secured flags, redaction, all seven screen states, Home reordering, abandoned-check discard, host allowlist) plus rendered-frame review; `ruff` + `mypy --strict` clean

**Pi verification (2026-08-18)** — deployed to the renamed `bridget.local`; all three services healthy, `pi-media` at `NRestarts=0` with no errors. Confirmed on hardware: `get_status()` returns the real SSID/IP, `scan_networks()` finds 24 networks correctly deduped and sorted, the unit hardening reads back from `systemctl show`, the app binds **port 80 as a non-root user**, the Host allowlist answers 403 to a rebinding Host, and the sudo allowlist passes `nmcli`/`rfkill`/`systemctl restart` while refusing everything else. `deploy.sh` still works with the blanket `NOPASSWD: ALL` grant **removed**. The Wi-Fi screen itself was driven from the panel by touch (`HOME -> WIFI`, `WIFI -> HOME` in the journal, no errors).

**Regression found 2026-08-18 (fixed same day).** The hardening above broke on-device speaker switching — see the `ProtectSystem=full` Key Note. `pi-media.service` now carries `ReadWritePaths=/etc/mpd.conf` and `configure-speaker` rewrites in place. Audio verified back on the EarFun.

**Not done — deliberately.** `NoNewPrivileges=yes` is set on **neither** unit, against the Security-posture bullet above: `sudo` is setuid, so it would break `rfkill`/`configure-speaker` on `pi-media` today and `sudo -n nmcli` from `pi-media-feeds` in Phase 10 — and it fails as a baffling "sudo must be setuid root", not a network error. Both units carry the rest of the hardening. `join_network` / `forget_network` / hotspot control are written and typed but have **never been run** — nothing calls them until Phase 10, and joining a network is what disconnects the box that is being worked on.

### Phase 10 — AP Fallback + Captive Portal ✅ COMPLETE (2026-08-18 — Pi-verified)

The shipping-critical phase: a friend can get the box onto their Wi-Fi with no engineer present.

**Hotspot lifecycle**

- [x] `network/watchdog.py` — `python -m network.watchdog`, run one-shot by `bridget-netwatch.timer` (`OnBootSec=90s`, `OnUnitActiveSec=60s`). `OnBootSec` is deliberately generous: NetworkManager needs time to try the saved networks after a cold boot, and counting those seconds as "offline" would raise a hotspot on a box that was about to connect fine. State survives between invocations in `network_watchdog_state.json`; a corrupt file is discarded rather than allowed to wedge the watchdog forever
- [x] `run_once(controller, state, now)` takes the clock **as an argument**, not by reading it — that is what makes the lifetime cap testable at all. `_elapsed_since` treats both a negative and an enormous elapsed as expired, because the Pi 3B+ has no RTC and NTP landing mid-window makes the clock jump: dropping an AP early is recoverable from the panel, leaving one up forever is not
- [x] `OFFLINE_CHECKS_BEFORE_HOTSPOT = 3` — a count, not a single sample, so a router rebooting doesn't raise a hotspot (~3 minutes offline before the AP goes up)
- [x] `network/hotspot.py` — SSID (`Bridget-Setup-<4 chars>`) and password generated **once per device with `secrets`**, never a repo constant, and written `0600` via `os.open(O_EXCL)` so the password is never briefly world-readable. Alphabet excludes ambiguous characters: it gets read off a 296×128 panel and typed into a phone by someone who did not choose it
- [x] **`load_credentials` never generates; `ensure_credentials` does.** The watchdog runs as root, and a credentials file *created* by root is unreadable by the app user that has to draw the QR — which would leave a hotspot up that the panel cannot describe. So root's path (`start_saved_hotspot`) only ever loads, and a missing file fails loudly
- [x] **Hard lifetime cap of 20 minutes** (`HOTSPOT_MAX_LIFETIME_SEC`) — a security control, not a nicety: the portal takes a Wi-Fi password over plain HTTP, so an AP nobody is watching must not stay up indefinitely. Expiry drops the AP *and* rejoins a saved network; the panel can raise it again on demand
- [x] **Manual trigger from the panel** — `AppState.WIFI_SETUP` + `HotspotRequested` (WIFI → WIFI_SETUP, Back returns). The one place `display/` issues a network *command* rather than reading state, so Phase 9's read-only `NetworkService` Protocol widened by exactly one method
- [x] A hotspot the watchdog did not start is **adopted** (`hotspot_started_at = now`) so the lifetime cap applies to a manually-raised AP exactly as to an automatic one

**Captive portal**

- [x] `deploy/dnsmasq-shared-portal.conf` → `/etc/NetworkManager/dnsmasq-shared.d/`, which NetworkManager reads **only for shared (hotspot) connections**, so the `address=/#/10.42.0.1` wildcard never applies while the box is a normal client on someone's home network
- [x] Probe routes in `feed_manager/app.py` — iOS/macOS `/hotspot-detect.html`, Android `/generate_204`, Windows `/ncsi.txt` — answered so the phone's connectivity check fails in the specific way that pops the "Sign in to network" sheet
- [x] **Join QR on the panel** (`display/screens/wifi_setup.py`) — a `WIFI:T:WPA;S:<ssid>;P:<password>;;` payload rendered with `segno` at whole-pixel module scale, mandatory 4-module quiet zone kept. Auto-detection stays best-effort by design: the panel states the SSID, the password and `http://10.42.0.1` in text, so the flow completes even when the sheet never appears

**API + Svelte**

- [x] `GET /api/network/status`, `GET /api/network/scan`, `POST /api/network/join`, `POST /api/network/forget`, following the existing `{"error": …}` convention `api.ts` already understands
- [x] **`POST /api/network/join` returns `202` before it joins.** Switching to the target network tears down the AP, so the phone loses the connection mid-request — the frontend treats a dropped connection as the *success* path and says to watch the screen, which is where the real outcome appears
- [x] `_require_hotspot()` guard: the network endpoints refuse unless the request arrives on the hotspot subnet. This is the structural control that replaces adding logins — a guest on the home LAN can meddle with podcasts but cannot touch network config
- [x] `MAX_JOIN_ATTEMPTS = 10` then `429`, so the owner gets retries for a mistyped password and nobody gets hundreds
- [x] `WifiPanel.svelte` + `NetworkList.svelte` beside the podcast view in `App.svelte` — no router (the app deliberately has none), a `$state` view switch, reusing `app.css`'s existing custom properties. The backend picks the opening view: `is_hotspot_active` defaults the app to the Wi-Fi tab, so in setup mode a friend sees Wi-Fi first without knowing there are tabs. Same bundle either way

**Three bugs found only by running it on hardware (2026-08-18)** — all three are one-radio or NetworkManager-behaviour problems that no amount of local testing would have surfaced:

1. **The AP came back up seconds after being dropped, and the lifetime cap could therefore never expire.** `reconnect_saved_network()` ran `nmcli device connect wlan0`, which picks a profile by autoconnect priority and kept re-selecting the `bridget-hotspot` profile it had just torn down. The journal shows the loop plainly: "Hotspot lifetime reached — dropping it and rejoining", then *"Adopting a hotspot this watchdog did not start"* one tick later, repeatedly — and because adoption resets `hotspot_started_at` to now, the 20-minute cap restarted every time. An AP meant to live 20 minutes would have broadcast forever. Fixed twice over: `start_hotspot` now sets `connection.autoconnect no` on the profile, and `reconnect_saved_network` names the target profile explicitly (`connection up id <name>`, skipping `HOTSPOT_CONNECTION_NAME`) instead of letting NetworkManager choose
2. **Joining from the portal failed with "No network with SSID … found".** The Pi has one radio: it cannot host an AP and associate with a router at the same time, so with the AP up there is no scan list for nmcli to match against. `join_network_from_hotspot()` drops the AP first, then joins. If the join then fails the box is briefly offline with no AP, which sounds alarming and is the recovery path working — the watchdog raises the AP again a few minutes later, so a mistyped password costs a wait rather than a stranded device
3. **`/api/network/scan` could never return anything**, for the same one-radio reason — the endpoint is only reachable while the AP is up. The scan is now taken in the last moment the radio is free (`_cache_scan_then_start`), written to `network_scan_cache.json`, and served from there; a failed scan degrades to an empty list plus manual SSID entry rather than abandoning the hotspot

- Verified by a 7-check watchdog-decision harness (offline counting, raise-at-threshold, kept-inside-lifetime, expired → drop **and** rejoin, backward clock jump, manual-AP adoption) plus the live hardware cycle below; `ruff` + `mypy --strict` clean

**Pi verification (2026-08-18)** — the fixes above were found by a live session that ended with the box flapping, so the regression was re-run deliberately on hardware with `HOTSPOT_MAX_LIFETIME_SEC` temporarily shortened to 120s (a detached script, since raising the AP kills the SSH session that started it, with a forced-recovery guard in case the watchdog failed). Result: AP up at 18:35:29 as `Bridget-Setup-n4b9` on `10.42.0.1`, adopted by the watchdog one tick later, expired on schedule, and **the watchdog itself brought the box back** — the guard never fired. The journal shows the fixed path exactly: `nmcli connection down id bridget-hotspot`, then `nmcli connection up id 'MyAltice 0722b1'` (the named profile, not `device connect`), then "Reconnected to saved network". Total outage 170s. Decisively, **nothing re-adopted an AP afterwards** — in the broken run "Adopting a hotspot this watchdog did not start" reappeared one tick after every drop; here the watchdog has been silent ever since, which is what "online, nothing to do" looks like. `connection.autoconnect no` persists on the hotspot profile and the shortened lifetime was restored to 20 minutes.

**Still outstanding — needs a phone.** The portal itself has never been driven by a human: the join QR's legibility on the real panel at 2px/module, whether the "Sign in to network" sheet actually pops on iOS/Android, and the deliberate mid-request disconnect on `POST /api/network/join` (the phone loses the AP as the box switches networks, so a dropped connection is the success path). The scan cache and `join_network_from_hotspot` are what those depend on and both are now exercised, but end-to-end provisioning by a non-engineer is unproven. Also unrun: `tools/make_touch_zones.py` for the new WIFI_SETUP screen.

### Phase 11 — Sleep Timer 📋 PLANNED

Fall asleep to a podcast or to FIP without the box playing all night. Reachable in one tap from whichever player is already on screen, because that is the moment anyone actually wants it.

**The timer itself**

- [ ] `display/sleep_timer.py` — a frozen `SleepTimer(deadline: float)` plus pure `remaining_seconds(timer, now)` / `is_expired(timer, now)`, both taking `now` **as an argument**. Same reason as Phase 10's `run_once(controller, state, now)`: reading the clock inside the function is what made that lifetime cap untestable, and this is the same shape of problem
- [ ] **`time.monotonic()`, never wall clock.** The Pi 3B+ has no RTC, so after an offline boot the clock restores a stale value and then jumps forward when NTP lands (see Key Notes) — a wall-clock deadline would fire hours early or never fire at all, and both failures happen while the owner is asleep and cannot see them. The Phase 10 watchdog *had* to use wall clock because it exits between invocations; the sleep timer lives inside one long-running process, so the monotonic clock is available and is strictly correct here. This is a deliberate divergence between two pieces of timing code, worth the comment
- [ ] **Session state, never persisted.** Unlike `network_watchdog_state.json`, a sleep timer that survived a restart would silently stop playback at a deadline nobody set. It dies with the process, on purpose
- [ ] **An absolute deadline, not "N minutes of playback".** Pausing does not pause the timer — the user is falling asleep against wall time, not against playback time. Written down so it is not "fixed" later

**Firing it, without tripping the machinery that already exists**

- [ ] The expiry check goes at the top of `ScreenManager.refresh_playback()`, **unconditionally** — not inside the `if self._playing_episode is not None` poll and not inside the player-screen redraw. Someone can set a timer and navigate to Home before dozing off, and radio runs with no polling at all today, so anything narrower silently never fires for half the cases. This is the same failure Phase 5 fixed when mark-played stopped happening off-screen
- [ ] **Expiry must not look like a natural finish.** If the timer lands while an episode happens to be past `_PLAYED_FRACTION_THRESHOLD`, `_is_natural_finish` sees a stop right after playing near the end, `_advance_queue` pops the queue and starts the *next* episode — the timer would wake the owner with more audio, which is precisely inverted. Expiry therefore routes through the existing `_release_playing_episode()`, whose docstring already states the rule ("Clearing `_playing_episode` before the player is stopped is what keeps a user-initiated stop from looking like a natural finish"), and only then stops the player. Structurally immune, exactly as user-Back already is — no new flag, no special case in `_is_natural_finish`
- [ ] Podcast expiry **persists the play position** (`_release_playing_episode` already does): dozing off 12 minutes in and resuming there tomorrow is the entire point. It does *not* mark the episode played
- [ ] Radio expiry clears `_playing_station` and stops. Nothing to persist, nothing to mark, nothing to advance — the Phase 8.5 separation pays for itself again
- [ ] On expiry the screen is **not** navigated away from; playback simply stops and the moon reverts to its unset state. E-ink holds the last frame with no power, so a stopped Now Playing is a perfectly good thing to wake up to

**UI**

- [ ] A tap zone in the **top-right of both Now Playing and Radio Playing**, showing `ICON_BEDTIME` (`ef44`, verified against `MaterialIcons-Regular.codepoints`) alone when unset, and the icon plus remaining whole minutes ("28m") when set. It is both the control and the readout, which is what keeps it to one glyph of screen budget
- [ ] Now Playing's top strip currently holds the feed name, so the feed name clips at the new zone — the same idiom as list rows clipping at `ACTION_X - 12`. Radio Playing's top strip is free (station name starts at y=28)
- [ ] **Tap-target size is the risk to verify on glass, not in the simulator.** The zone is ~48px wide (matching the Phase 8 header-action widening, which was made 36→48px for exactly this reason) but only ~22px tall against the 35px finger-sized list rows. If it proves fiddly on the real panel, the fallback is a full-width strip above the control bar rather than shrinking anything else
- [ ] `AppState.SLEEP_TIMER`; events `SleepTimerRequested` and `SleepDurationSelected(minutes: int | None)` where `None` is Off
- [ ] `SleepTimerScreen` reusing `list_layout` — 15 / 30 / 45 / 60 minutes and Off is five rows against three visible, so it scrolls with the standard sidebar exactly like Home. The active duration is marked in the action zone; header is the back button
- [ ] **Back from SLEEP_TIMER must return to the player that opened it**, so a second origin is needed beside `now_playing_origin`. Rather than growing `transition()` a fourth positional argument, introduce a frozen `NavigationContext(now_playing_origin, sleep_timer_origin)` and pass that — the function stays pure and three-argument, and the next origin costs nothing. Note this does not contradict the "don't widen the pure function" Key Note: that one is about *outcomes* (success/failure), which still belong in side effects; an origin is navigation input, and `now_playing_origin` is the standing precedent
- [ ] The countdown readout needs no special redraw cadence: `refresh_playback()` already redraws both player screens every tick, so the minutes value comes along free. Compute it from the monotonic deadline, do not tick a counter
- [ ] All new strings in `display/copy.py`, checked by rendering against the 3-line/~135-char status budget

**Files**: new `display/sleep_timer.py`, `display/screens/sleep_timer.py`; touched `display/state_machine.py`, `display/events.py`, `display/manager.py`, `display/copy.py`, `display/renderer.py` (`ICON_BEDTIME`), `display/screens/now_playing.py`, `display/screens/radio_playing.py`.

- [ ] Verification: a pure harness for `remaining_seconds` / `is_expired` with an injected clock (no hardware, no MPD); a scripted-touch harness per `.claude/skills/verify/SKILL.md` covering set-from-both-players, Off cancelling, the timer surviving navigation to Home, position persisted on podcast expiry, station released on radio expiry, and — the regression that matters — **expiry at ≥90% through an episode stopping rather than auto-advancing the queue**; rendered-frame review of both players set and unset plus the duration screen; re-run `tools/make_touch_zones.py` (new tap targets); `ruff` + `mypy --strict` clean

**Not in scope, deliberately.** "End of episode" as a duration (it means nothing for radio and tangles with queue auto-advance — worth its own pass if wanted), and any volume fade-out, which would require widening the `AudioPlayer` Protocol with volume control that `display/` deliberately has no access to today, on top of MPD volume over a Bluetooth sink being its own rabbit hole.


## Key Notes

- **A vendor's own config recipe can be board-specific and silently backwards.** Raspberry Pi's documented way to kill the PWR LED (`pwr_led_trigger=none` + `pwr_led_activelow=off`) leaves a 3B+ **lit**: the expander line here is `PWR_LED_R` where HIGH is dark, not the Pi 4's inverted `PWR_LED_OFF`, so `activelow` needs the opposite value. What made this expensive was that **`/sys/class/leds/PWR/brightness` read `0` the whole time the LED was visibly on** — the kernel's model and the glass disagreed, so sysfs confirmed a fix that had not happened. Two things broke the loop: a **blink test** (`echo timer > trigger`) to establish the kernel controls the LED at all, and `/sys/kernel/debug/gpio`, which prints the real pin level and its polarity. For anything whose output is a physical state, find a readback that reflects the hardware, not the driver's intent — and until you have one, a human eye is the ground truth.
- **Rotating the panel means rotating the touch grid with it.** The glass and the capacitive grid are one physical part, so flipping only the image leaves every tap landing on the row *diagonally opposite* the one pressed — which reads as a baffling touch-calibration fault, not as a rotation bug. `WaveshareDriver` therefore pairs `_orient` (frame) with `_orient_touch` (`x → WIDTH-1-x`, `y → HEIGHT-1-y`), and orientation lives in the **driver**, not the renderer: it is a fact about how the box is mounted, not about the UI, and keeping it there is what lets the screens, `list_layout.py`'s tap zones and `touch_zones.png` all stay in one unrotated coordinate space. The invariant to test is not either flip alone but that they agree — ink drawn at a logical point must physically appear where a tap reports that same logical point.
- **`nmcli device connect <iface>` picks the profile *NetworkManager* prefers, which includes the AP you just tore down.** Dropping the setup hotspot and then asking the device to reconnect looks like the obvious way to rejoin the house network; instead NetworkManager re-selected the `bridget-hotspot` profile by autoconnect priority, seconds after `connection down` brought it off. The failure is nastier than a plain "didn't reconnect", because the watchdog then *adopted* the AP it found up and reset the lifetime clock — so a cap that exists specifically to stop an unattended AP accepting Wi-Fi passwords over plain HTTP could never fire. Two independent fixes, because either alone is a single point of failure: the hotspot profile is created with `connection.autoconnect no`, and reconnection names its target profile explicitly (`connection up id <name>`, never `device connect`). Generally: when a tool "picks a sensible default" for you, check what it picks on the box, and prefer naming the thing you mean.
- **One Wi-Fi radio means hosting and scanning are mutually exclusive** — and the code that needs a scan list is, by construction, only reachable while the AP is up. Both the portal's network list and its join call failed on hardware for this one reason ("No network with SSID … found" is what nmcli says when the AP owns the radio and no scan list exists). Neither is fixable in place: the scan has to be captured in the last moment the radio is free and cached (`_cache_scan_then_start` → `network_scan_cache.json`), and joining has to drop the AP *before* it associates (`join_network_from_hotspot`). Any future feature that wants the air while the setup AP is up needs the same treatment — the answer is always "do it before taking the radio", never "do it concurrently".
- **An unprivileged `nmcli` scan is silently a lie.** `nmcli device wifi list --rescan yes` without root exits 0 and returns *whatever was already cached* — on this device two rows, both bands of the network it was already associated with, against **24** for the identical command under `sudo`. Nothing in the output says the rescan was ignored. Read as a working scan it is worst exactly where it matters: a box that has never been online in that house would offer an empty network list in the Phase 10 portal. `scan_networks()` is therefore privileged, unlike `get_status()`, which is honest unprivileged. The general lesson: for a tool that degrades instead of failing, compare privileged and unprivileged output on real hardware before trusting either.
- **`raise ... from None` does not remove the original exception from the object.** It only sets `__suppress_context__`, which stops the *traceback printer*; `__context__` still holds the exception, and `CalledProcessError`/`TimeoutExpired` carry the full argv — Wi-Fi password included — in their own repr. Anything that walks the chain (an error reporter, a re-raise, a debugger) still sees it. `NetworkController._run` therefore builds the `NetworkError` inside the `except` block and **raises it outside**, where there is no exception being handled to attach, setting `__cause__` by hand only for commands with no secret in argv.
- **A subprocess wrapper's error string is a disclosure channel.** `_run()` helpers here raise `f"<tool> {' '.join(args)} failed"`, which is ideal for `bluetoothctl` (MACs, harmless) and wrong the moment an argument is a secret — `nmcli device wifi connect <ssid> password <pw>` would put the Wi-Fi password in the journal *and* in the HTTP response, since `feed_manager/routes.py` answers `{"error": str(exc)}`. Any new `_run()` that can take a credential redacts it, or takes the secret via stdin / a config file instead of argv (argv is world-readable in `ps` too).
- **A URL from the web app is attacker-controlled.** `feedparser.parse()` opens a filesystem path or `file://` URL as readily as an `http` one, so `POST /api/feeds` was a local-file-read and internal-port-scan primitive for anyone who could reach the LAN. `feeds/fetcher.py._validate_feed_url` now rejects any scheme outside `{http, https}` *before* the upsert, so a rejected URL leaves no feed row behind. The same instinct applies to anything else the web app hands to a library that accepts paths.
- **"Continue the queue" and "start the queue" are different features, and shipping only the second is an ambush.** `_advance_queue` originally started `first_entry()` after *any* natural finish. Every individual step is defensible — the queue is FIFO, a finish is a finish — and the result is that one entry the owner queued weeks ago and forgot lies dormant until some unrelated episode ends, then plays itself. It is worse than a visible bug because nothing looks wrong at the time it is armed: the tap that queued it may well have been a mis-aimed row tap (the toggle zone is `x ∈ [224, 260)`, a 36px band between the title and the sidebar, and hitting it plays nothing and shows only a small ✓). The gate is membership — *was the thing that just finished in the queue?* — not a playback-origin flag, because starting a queued episode by tapping it in the episode list has to keep chaining. General shape: before auto-starting anything, check that the user's most recent action actually put them in the mode that auto-start belongs to.
- **Silence in the journal is not evidence nothing happened.** Diagnosing the above, the ambushing episode ran for ~21 hours and logged *nothing at all* — because it was already `played=1`, so `_mark_played_if_past_threshold`, `_persist_position_now` and the mark-played branch of `_advance_queue` all early-returned, and its own natural finish emptied the queue and therefore skipped the "Auto-advancing" line too. Every logged event in this app is a *change*; a steady state is invisible. Reconstruct from the DB (`queue`, `episodes.played`, `play_position_sec`) alongside the log, and treat a gap as unknown rather than idle.
- **A live stream is not a short podcast.** Radio shares exactly one field with an episode (a URL) and nothing else: no duration, no position, no queue entry, no publish date, no played state. Modelling it as a `Feed` + fake `Episode` would have been ~20 lines and wrong in four places at once — the feed fetcher would parse it every cycle, the resume-seek would seek into a live stream from an ever-growing saved position, the progress bar would sit permanently empty, and a dropout would be indistinguishable from a finish. The separate `Station` type and `RADIO_PLAYING` state are what make all of that structurally impossible rather than individually special-cased.
- **Threads in the display layer: only for work that touches nothing shared.** The Bluetooth scan is the sole background thread in the UI process (Phase 8) and it qualifies because it does nothing but shell out to `bluetoothctl` — no sqlite connection, no driver calls, results handed back as frozen dataclasses over a `queue.Queue`. Before threading anything else, apply that test; if the work needs the DB or the display, it belongs on the UI thread with a status frame instead. Modal operations (pair, connect) should stay blocking even though they're slower — you don't *want* input accepted mid-pair.
- **Long blocking calls need `_drain_touches()` afterwards.** Taps land in the driver's buffer while the UI thread is stuck in a 20–30s `bluetoothctl` call and then replay against whatever screen came up next. The 300ms debounce doesn't help — the taps are seconds apart. Any new multi-second blocking side effect must drain.
- **A pure `transition()` shouldn't learn about outcomes.** When pairing needed "go to BLUETOOTH on success, show an error on failure", the cheap fix would have been a second context parameter alongside `now_playing_origin`. Instead the event always transitions to BLUETOOTH and the manager sets a status banner. Prefer moving the outcome into a side effect over widening the pure function's signature.
- **Status-message copy is budgeted.** `list_layout.draw_status_message` wraps to 3 lines of ~45 chars (~135 total) and silently ellipsises the rest, so new copy in `display/copy.py` has to be written to that budget and checked by rendering it — not trimmed afterwards. Now Playing's error is the exception: it sits inline between the title and the controls and must stay one short line, or it collides with the control bar.
- **`touch_zones.png` is generated, not drawn** — `python tools/make_touch_zones.py` renders the real screens and overlays zones computed from `list_layout.py`'s constants. The first version was a hand-made one-off and silently went stale across four phases; re-run the script whenever a tap target moves rather than editing the image.
- **Icons are centred on rendered ink, not `textbbox`.** `renderer._icon_ink_box` measures a glyph by actually rasterising it, because the 1-bit canvas thresholds away the antialiased edges `textbbox` counts. Centring on `textbbox` drew *every* icon in the app 1–4px high (sidebar chevrons were worst at 4px) until it was fixed in Phase 8. Header icon rects also need `_HEADER_BAR_BOTTOM`, not `HEADER_HEIGHT` — the bar is filled inclusive of its last row, so it's 24px tall while the constant says 23.
- **Material Icons codepoints must be verified, not guessed** — `grep '^name ' assets/fonts/MaterialIcons-Regular.codepoints`. The bluetooth family is contiguous and easy to get subtly wrong (`e1a7` bluetooth, `e1a8` connected, `e1a9` *disabled*, `e1aa` searching).
- **One sqlite3 connection per thread, always.** The UI thread and the fetcher thread each get their own `Database` instance (wired in `main.py`); sharing a connection across threads corrupts it and crashes the process with `SystemError`. WAL + busy timeout + IMMEDIATE transactions (set in `db/database.py`) make the two connections coexist. If a new thread ever needs the DB, give it its own `Database`. `feed_manager/` (a separate process) follows the same rule per-request via `flask.g` — see Phase 7.
- MPD is installed/configured by `deploy/setup_pi.sh` (plus the manual speaker pairing step). Use `python-mpd2` to connect on `localhost:6600`. If MPD is unreachable at startup, `main.py` logs and continues — the UI still comes up.
- MPD drops idle client connections after 60s (`connection_timeout` default) and restarts when `configure-speaker` runs — `PlayerController._execute()` therefore reconnects once and retries on connection loss. Without it, browsing lists for over a minute killed all playback commands (the player-unreachable notice on Now Playing) until an app restart.
- Podcast audio URLs sit behind ad/tracking redirect chains that can exceed MPD's hard limit of 5 (Radiolab's is 6+), and MPD fails *asynchronously* — `play` is accepted, the decode error lands a second later and MPD ends up **stopped**. `PlayerController` therefore (a) resolves redirects app-side before queueing (`_resolve_stream_url`: plain GET, body unread, player-style User-Agent — some trackers 403 Python's default, and a `Range` header must NOT be sent because WNYC's CDN bakes it into the signed URL as `x-access-range`, killing seeks), and (b) `resume()` issues `play` when MPD is stopped, since `pause(0)` is a silent no-op there.
- ±30s skip needs ffmpeg as the mp3 decoder: MPD's default (`mad`) can't seek ad-stitched streams ("Decoder failed to seek" on WNYC/Radiolab), so `deploy/mpd.conf` disables `mad` and `mpg123`. If skips break again after an MPD reinstall, check those decoder blocks survived in `/etc/mpd.conf`.
- **`ProtectSystem=full` makes /etc read-only for a service's *children*, sudo included — and a config-patching helper fails with a code nobody reads.** Phase 9 hardened `pi-media.service` on the reasoning that "/etc read-only costs it nothing — it only writes the database"; it also writes `/etc/mpd.conf`, via `configure-speaker`, which is how the app repoints MPD when you switch speakers. Under the namespace `sed -i` got an I/O error and exited **4**, so mpd.conf kept the *previous* device's MAC: the speaker connected audibly and then played nothing, and the only trace was `Failed to open ALSA device "bluealsa:DEV=…": No such device` in MPD's journal. Two-part fix, both needed: `ReadWritePaths=/etc/mpd.conf` on the unit, and `configure-speaker` rewriting **through the existing inode** (`cat scratch > file`) rather than `sed -i`, whose temp-file-and-rename needs a writable *directory* and would replace the very inode the bind mount points at. General rule: when hardening a unit, enumerate what its *sudo helpers* write, not just what the process writes — and reproduce the failure inside the namespace (`systemd-run --property=…`), since it exits 0 from a plain SSH shell.
- **`deploy.sh` does not reinstall systemd units.** It syncs code and restarts services, so an edit to `deploy/pi-media.service` lands in `~/pi_media/deploy/` on the Pi and is *never read* — `/etc/systemd/system/` keeps the old copy and the change silently does nothing. The restart cap looked deployed and wasn't; `systemctl show pi-media -p StartLimitBurst` still reported systemd's defaults. After any unit change, either re-run `setup_pi.sh` or repeat its install line by hand: `sed 's|@USER@|…|; s|@APP_DIR@|…|' deploy/<unit> | sudo tee /etc/systemd/system/<unit>` then `daemon-reload`. Always read the value back from `systemctl show`, not from the repo file.
- **The Pi 3B+ has no RTC, so log timestamps lie after an offline boot.** `timedatectl` reports `RTC time: n/a`; booting without a network means no NTP, so the clock restores a stale value and every early log line carries it. When Wi-Fi comes back the clock jumps forward *mid-log*, so a single continuous process appears to log across eight days. Trust `uptime -s` and `systemctl show -p NRestarts -p MainPID` for what actually happened, never the journal's own timestamps — a wildly old timestamp on a running service is a clock artifact, not evidence of a stale process.
- **A hardware bring-up that can hang is worse than one that crashes.** Waveshare's `init()` polls the panel's BUSY line with no timeout of its own, so a missing or floating BUSY wire hangs it *forever*: the process stays alive, `systemctl` reports the unit healthy, and the log simply stops mid-startup with no error to find. `WaveshareDriver.__init__` therefore runs the whole bring-up on a daemon thread joined with `_BRING_UP_TIMEOUT_SEC` (15s — a healthy panel finishes in well under a second). The thread can't be killed, but as a daemon it dies with the process. Any future blocking hardware handshake needs the same treatment; "it hung with no log" costs far more debugging time than a stack trace.
- **Order of construction in `main.py` is a failure-mode decision, not style.** The driver is built *before* `scheduler.start()` because without a display there is no app, so failing there should cost nothing. When it ran after, a wiring fault became a restart loop that re-fetched every feed every `RestartSec` — a network/CPU/SD-write storm on a box that couldn't draw a single frame. `pi-media.service` also caps restarts (`StartLimitBurst=5`), so a hardware fault settles into `failed` — which `systemctl status` states plainly — instead of looping indefinitely.
- **`DisplayError` lives in `display/errors.py`, not `manager.py`.** It moved so `display/drivers/` can raise it without importing the manager (a driver has no business knowing about `ScreenManager`). `display/__init__.py` re-exports it, so `from display import DisplayError` is unchanged.
- Waveshare provides Python demo code on their wiki — use it as the display/touch driver base, don't rewrite from scratch.
- Speaker pairing has two paths now: on-screen (Phase 8, "Just Works" devices only) and `deploy/pair_speaker.sh` (needed for anything demanding a PIN or numeric confirmation). The on-screen path calls `sudo -n /usr/sbin/rfkill unblock bluetooth` best-effort before `power on`, since the Pi's controller ships soft-blocked — it relies on the same passwordless sudo the deploy tooling already requires.
- `config.STATIONS` is *not* a seed like `FEEDS` — there is no stations table, so editing that list is the only way stations change, and a DB wipe doesn't affect them. Keep them out of `feeds`: every row there is fetched by feedparser every refresh cycle.
- `config.FEEDS` (currently Radiolab, Dear Hank and John, The Universe (Crash Course Pods)) is only a one-time seed for a fresh DB now — add/remove feeds via `feed_manager/` (see Phase 7), not by editing `config.py`. With the 3 defaults, scrolling isn't exercisable on the podcast list without adding a 4th.
- No audio files stored locally — playback always streams from `episode.audio_url`.
- Partial refresh is used for all in-screen updates (scroll, play/pause toggle, skip, periodic progress redraw) *and* for most screen transitions; a real full refresh (the multi-flash one) only runs every `_TRANSITIONS_BETWEEN_FULL_REFRESHES`th transition to wipe accumulated ghosting. If ghosting looks bad on the panel, lower that constant in `display/manager.py`.
- All UI development happens locally with `--simulate`. MPD integration is tested on the Pi only. On Windows every player command raises inside `ScreenManager._player_command` and becomes a log line — that's the expected simulator behavior, not a bug.
- To verify UI changes without clicking through the simulator: drive `ScreenManager` with scripted touches against a fake driver that saves each frame as a PNG (a capturing driver + fake player satisfying the Protocols is ~60 lines). `.claude/skills/verify/SKILL.md` has the full recipe, including real touch coordinates for every tap target and how to fast-forward the position-persist throttle.
