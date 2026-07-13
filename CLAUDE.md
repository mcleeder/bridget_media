# Pi Media — Raspberry Pi Podcast Player

## Project Overview

A podcast player running on a Raspberry Pi with a Waveshare 2.9" e-ink touch display. Streams audio via MPD to a Bluetooth speaker. No local audio storage — pure streaming. RSS feeds are hardcoded for now; a feed management system comes later.

## Hardware

- **Raspberry Pi 3 Model B+** — Raspberry Pi OS (Debian 13 "trixie", arm64), hostname in `.env`
- **Display**: Waveshare 2.9" Touch E-Paper HAT — 296×128px, black/white, SPI
- **Touch**: 5-point capacitive, I2C (ICNT86 controller — confirmed on hardware; TP_lib's `ICNT_Scan` maps coords into 296×128 landscape space)
- **Audio**: MPD daemon → Bluetooth speaker via `mpc`

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

## Architecture

### Layers

```
config.py          ← hardcoded RSS feeds, app settings
db/                ← SQLite schema and queries
feeds/             ← RSS fetch + parse → store episodes
player/            ← python-mpd2 wrapper, playback state
display/           ← e-ink driver, touch input, screen rendering
main.py            ← app entry point, event loop
```

### Data Flow

1. `feeds/fetcher.py` polls RSS feeds on startup + every N hours, writes episodes to DB
2. `player/controller.py` wraps MPD: stream URL, play/pause/stop/seek
3. `display/` renders a PIL image → pushes to e-ink; touch events → UI events → state machine
4. `main.py` wires it all together and runs the poll loop: touch → `ScreenManager.handle_touch` → display update

### UI State Machine

Navigation is an explicit state machine, not a screen stack.

- **`display/state_machine.py`** — `AppState` enum (`HOME`, `PODCAST_LIST`, `EPISODE_LIST`, `NOW_PLAYING`, `QUEUE`, `BLUETOOTH`) and a pure `transition(state, event, now_playing_origin) → AppState`. No side effects live here. NOW_PLAYING is reachable from more than one screen (episode list, queue), so Back from it returns to `now_playing_origin` — `ScreenManager` tracks it and passes it in, keeping `transition()` pure.
- **`display/events.py`** — frozen event dataclasses: `HomeMenuSelected(item: HomeMenuItem)`, `FeedSelected`, `EpisodeSelected`, `BackRequested`, `ListScrolled`, `PlayPauseToggled`, `SkipRequested`, `QueueToggled(episode)`, `QueueRemoveRequested(episode)`.
- **Screens** (`display/screens/`) only render and translate touches into events (`handle_touch(x, y) → Event | None`). They never navigate, never touch the player, never construct other screens. `Screen` is a Protocol (`display/screens/base.py`).
- **`display/manager.py`** — `ScreenManager` drives the machine: applies each event's side effects (player commands, screen construction), calls `transition()`, and refreshes the display — **partial refresh everywhere, with a true full refresh every Nth state transition** (`_TRANSITIONS_BETWEEN_FULL_REFRESHES`) to clear e-ink ghosting without flashing on every navigation.

Transitions:

| From | Event | To |
|---|---|---|
| HOME | HomeMenuSelected(PODCASTS) | PODCAST_LIST |
| HOME | HomeMenuSelected(QUEUE) | QUEUE |
| HOME | HomeMenuSelected(BLUETOOTH) | BLUETOOTH |
| PODCAST_LIST | FeedSelected | EPISODE_LIST |
| PODCAST_LIST | BackRequested | HOME |
| EPISODE_LIST | EpisodeSelected | NOW_PLAYING (starts playback) |
| EPISODE_LIST | BackRequested | PODCAST_LIST |
| QUEUE | EpisodeSelected / BackRequested | NOW_PLAYING / HOME |
| BLUETOOTH | BackRequested | HOME |
| NOW_PLAYING | BackRequested (stops playback) | `now_playing_origin` |

Anything else is a no-op that keeps the current state. Initial state is HOME. `QueueToggled` / `QueueRemoveRequested` / `BluetoothDeviceSelected` don't navigate — the manager updates the queue/bluetooth state, rebuilds the current list screen (scroll preserved), and partial-refreshes.

`display` never imports `player` or `bluetooth`: playback flows through the `AudioPlayer` / `PlaybackState` Protocols in `display/playback.py` (satisfied structurally by `PlayerController`), and Bluetooth flows through the `BluetoothDevice` / `BluetoothService` Protocols in `display/bluetooth_control.py` (satisfied structurally by `BluetoothController`). `ScreenManager` wraps both player and bluetooth calls in a broad `except Exception` (with a why-comment) because their exception types live above the display layer — a failure degrades to a log line, never a UI crash. This is also what makes the simulator work on Windows with no MPD or `bluetoothctl`.

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

The queue is FIFO (`ORDER BY id`, no position column). `UNIQUE(episode_id)` + `INSERT OR IGNORE` make double-queueing a no-op. Entries are removed when an episode **finishes** (auto-advance, `ScreenManager._advance_queue`), not when it starts — restarting mid-episode keeps the entry.

## Display / UI

### Key Constraints

- **296×128px** — very small; font sizes and touch targets must be deliberate
- **Full refresh** (~2s, visibly flashes a few times — inherent to the e-ink waveform) runs every 6th screen transition to clear ghosting; the first frame after boot is also full (partials need a base frame)
- **Partial refresh** (fast, flash-free) used for everything else: in-screen updates (playback progress, time) and the transitions in between
- E-ink uses Waveshare's SPI driver; touch uses I2C

### Screens

1. **Home** — root menu ("Bridget Media" header), three fixed rows (Bluetooth / Podcasts / Next), icon left + chevron right, no scrolling, no back button; header + 3×35px rows exactly fill 128px
2. **Podcast List** — scrollable list of feed names; tap a row to enter, tap header to go back to Home
3. **Episode List** — episodes for selected feed (title + date, ● = unplayed); tap header to go back, tap a row to play, tap the action-zone icon (+ / ✓) to toggle queue membership
4. **Now Playing** — feed name, wrapped episode title (2 lines max), progress bar with elapsed/total times, bottom control bar; Back returns to whichever screen started playback
5. **Next (queue)** — FIFO queue: episode title + feed name per row, remove icon in the action zone, tap a row to play (Back from Now Playing returns here); "Queue is empty" state
6. **Bluetooth** — paired-device rows (name + "Connected"/"Tap to connect"), `ICON_BLUETOOTH_CONNECTED` on the connected one; tap an unconnected row to switch to it, tap the connected row to disconnect; "Bluetooth unreachable" error state (no `bluetoothctl` — always true on Windows) and an empty state pointing at `deploy/pair_speaker.sh`

### Layout & Touch Zones

Shared list geometry lives in `display/screens/list_layout.py`:

- **Header** — 23px black bar (title; on Episode List it's also the back button, with a back icon)
- **Rows** — 3 visible rows × 35px, finger-sized
- **Action zone** — 36px column just left of the sidebar (`ACTION_X = SIDEBAR_X - 36`), one icon button per row (episode list: queue + / ✓; queue: remove); row text clips at `ACTION_X - 12`
- **Scroll sidebar** — right-edge 36px column with up/down chevrons; chevrons only draw when scrolling that direction is possible; tap top half = up, bottom half = down; scrolls use partial refresh (no flicker)

Now Playing controls are bottom-anchored (y=95..128), four 74px-wide icon buttons: back, replay-30, play/pause (inverted black button, primary action), forward-30.

### Fonts & Icons

- **Text**: `assets/fonts/DejaVuSans.ttf`
- **Icons**: `assets/fonts/MaterialIcons-Regular.ttf` (Google Material Icons, Apache 2.0) — glyphs are `ICON_*` constants in `display/renderer.py`, codepoints verified against `MaterialIcons-Regular.codepoints` (kept alongside the font)
- Fonts load through `renderer.load_text_font(size)` / `load_icon_font(size)` (cached); `renderer.draw_icon_centered()` centers a glyph in a button rect

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
├── config.py                  # hardcoded FeedConfig list, settings
├── test_display.py            # Pi-only hardware smoke test
├── deploy/
│   ├── deploy.sh              # Windows → Pi code sync + service restart
│   ├── setup_ssh_key.sh       # one-time passwordless SSH setup
│   ├── setup_pi.sh            # on-Pi provisioning (run once per flash)
│   ├── pair_speaker.sh        # Windows → SSH: scan/pair/trust/connect + configure-speaker
│   ├── pi-media.service       # systemd unit template
│   └── mpd.conf               # MPD config template (bluez-alsa + aux outputs, ffmpeg mp3 decoding)
├── db/
│   ├── __init__.py
│   ├── database.py            # connection, schema init, DatabaseError
│   ├── models.py              # Feed, Episode (frozen dataclasses)
│   └── queries.py             # FeedRepository, EpisodeRepository
├── feeds/
│   ├── __init__.py
│   └── fetcher.py             # feedparser → DB
├── player/
│   ├── __init__.py
│   └── controller.py          # python-mpd2 wrapper, PlaybackState
├── bluetooth/
│   ├── __init__.py
│   └── controller.py          # bluetoothctl subprocess wrapper, BluetoothDevice, BluetoothError
├── display/
│   ├── __init__.py
│   ├── events.py              # typed Event dataclasses
│   ├── state_machine.py       # AppState enum + pure transition()
│   ├── playback.py            # AudioPlayer / PlaybackState Protocols
│   ├── bluetooth_control.py   # BluetoothDevice / BluetoothService Protocols
│   ├── manager.py             # ScreenManager (drives the machine), DisplayError
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
│       └── bluetooth_list.py
└── assets/
    └── fonts/                 # DejaVuSans.ttf, MaterialIcons-Regular.ttf (+ .codepoints)
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
```

On the Pi, dependencies are installed by `deploy/setup_pi.sh` (see Deployment). `requirements.txt` is runtime-only and stays the source of truth — keep the pip list in `setup_pi.sh` in sync with it.

## Deployment

Connection details (hostname, user, password) live in `.env` — git-ignored, never commit it.

**Fresh Pi (after a reflash):**

```bash
bash deploy/setup_ssh_key.sh    # one-time: passwordless SSH (prompts for the .env password)
bash deploy/deploy.sh           # push code to ~/pi_media on the Pi
ssh <user>@<host>.local 'bash ~/pi_media/deploy/setup_pi.sh'
```

Reflash gotchas: clear the stale host key first (`ssh-keygen -R <host>.local`), and the deploy tooling needs **passwordless sudo** on the Pi — the imager-created user doesn't have it by default (`echo '<user> ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/010_<user>-nopasswd`).

`setup_pi.sh` is idempotent: apt packages (MPD, bluez-alsa, GPIO/SPI/I2C libs), enables SPI + I2C, pip runtime deps (`--break-system-packages`, Pillow via apt), clones the Waveshare `Touch_e-Paper_HAT` repo and installs its `TP_lib` package (imported directly by `display/drivers/waveshare.py`; the panel class is `EPD_2IN9_V2`, touch is `icnt86.INCT86` — Waveshare's own typo), installs `/etc/mpd.conf` (Bluetooth output via bluez-alsa) and the `pi-media` systemd service. It ends by printing the two manual steps: pair the speaker with `bluetoothctl`, then `configure-speaker <MAC>` (installed helper that patches the MAC into mpd.conf), and reboot.

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
feeds / player / bluetooth (know db, know config — bluetooth needs neither, it only shells out)
    ↓
display                  (knows feeds/player/bluetooth through injected interfaces, never imports them directly)
    ↓
main                      (imports everything, wires the graph, runs the loop)
```

A layer must never import from the layer above it. If you feel the urge to do so, the logic belongs in a different layer.

### Error Handling
- Each layer defines its own exception types:
  ```python
  class FeedFetchError(Exception): ...
  class DatabaseError(Exception): ...
  class PlayerError(Exception): ...
  class BluetoothError(Exception): ...
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
- [x] `_advance_queue()`: remove finished from queue, defensively mark played (shared `_mark_episode_played` helper), `first_entry()` → `_start_episode`; rebuilds QUEUE/EPISODE_LIST screen if showing (NOW_PLAYING is replaced by `_start_episode` and redrawn by the poll's trailing `_show`). Any natural finish pops the queue head, queue-started or not. Wrapped in `except DatabaseError` — a DB hiccup logs, doesn't kill the loop, and can't re-fire (`_playing_episode` cleared first)
- Verified via 26-check scripted-touch harness (queue playback → two consecutive natural finishes → queue drained; decode-failure immunity; stopped-poll position guard; user-Back immunity) + simulator smoke run; ruff + `mypy --strict` clean

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


## Key Notes

- **One sqlite3 connection per thread, always.** The UI thread and the fetcher thread each get their own `Database` instance (wired in `main.py`); sharing a connection across threads corrupts it and crashes the process with `SystemError`. WAL + busy timeout + IMMEDIATE transactions (set in `db/database.py`) make the two connections coexist. If a new thread ever needs the DB, give it its own `Database`.
- MPD is installed/configured by `deploy/setup_pi.sh` (plus the manual speaker pairing step). Use `python-mpd2` to connect on `localhost:6600`. If MPD is unreachable at startup, `main.py` logs and continues — the UI still comes up.
- MPD drops idle client connections after 60s (`connection_timeout` default) and restarts when `configure-speaker` runs — `PlayerController._execute()` therefore reconnects once and retries on connection loss. Without it, browsing lists for over a minute killed all playback commands ("MPD unreachable") until an app restart.
- Podcast audio URLs sit behind ad/tracking redirect chains that can exceed MPD's hard limit of 5 (Radiolab's is 6+), and MPD fails *asynchronously* — `play` is accepted, the decode error lands a second later and MPD ends up **stopped**. `PlayerController` therefore (a) resolves redirects app-side before queueing (`_resolve_stream_url`: plain GET, body unread, player-style User-Agent — some trackers 403 Python's default, and a `Range` header must NOT be sent because WNYC's CDN bakes it into the signed URL as `x-access-range`, killing seeks), and (b) `resume()` issues `play` when MPD is stopped, since `pause(0)` is a silent no-op there.
- ±30s skip needs ffmpeg as the mp3 decoder: MPD's default (`mad`) can't seek ad-stitched streams ("Decoder failed to seek" on WNYC/Radiolab), so `deploy/mpd.conf` disables `mad` and `mpg123`. If skips break again after an MPD reinstall, check those decoder blocks survived in `/etc/mpd.conf`.
- Waveshare provides Python demo code on their wiki — use it as the display/touch driver base, don't rewrite from scratch.
- RSS feeds are hardcoded in `config.py` as `FeedConfig` frozen dataclasses (currently Radiolab, Dear Hank and John, The Universe (Crash Course Pods) — 3 feeds, one per visible row, so scrolling isn't exercisable on the podcast list without adding a 4th).
- No audio files stored locally — playback always streams from `episode.audio_url`.
- Partial refresh is used for all in-screen updates (scroll, play/pause toggle, skip, periodic progress redraw) *and* for most screen transitions; a real full refresh (the multi-flash one) only runs every `_TRANSITIONS_BETWEEN_FULL_REFRESHES`th transition to wipe accumulated ghosting. If ghosting looks bad on the panel, lower that constant in `display/manager.py`.
- All UI development happens locally with `--simulate`. MPD integration is tested on the Pi only. On Windows every player command raises inside `ScreenManager._player_command` and becomes a log line — that's the expected simulator behavior, not a bug.
- To verify UI changes without clicking through the simulator: drive `ScreenManager` with scripted touches against a fake driver that saves each frame as a PNG (a capturing driver + fake player satisfying the Protocols is ~60 lines). `.claude/skills/verify/SKILL.md` has the full recipe, including real touch coordinates for every tap target and how to fast-forward the position-persist throttle.
