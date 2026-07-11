# Pi Media — Raspberry Pi Podcast Player

## Project Overview

A podcast player running on a Raspberry Pi with a Waveshare 2.9" e-ink touch display. Streams audio via MPD to a Bluetooth speaker. No local audio storage — pure streaming. RSS feeds are hardcoded for now; a feed management system comes later.

## Hardware

- **Raspberry Pi** (model TBD)
- **Display**: Waveshare 2.9" Touch E-Paper HAT — 296×128px, black/white, SPI
- **Touch**: 5-point capacitive, I2C (likely GT1151 controller)
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

- **`display/state_machine.py`** — `AppState` enum (`PODCAST_LIST`, `EPISODE_LIST`, `NOW_PLAYING`) and a pure `transition(state, event) → AppState`. No side effects live here.
- **`display/events.py`** — frozen event dataclasses: `FeedSelected`, `EpisodeSelected`, `BackRequested`, `ListScrolled`, `PlayPauseToggled`, `SkipRequested`.
- **Screens** (`display/screens/`) only render and translate touches into events (`handle_touch(x, y) → Event | None`). They never navigate, never touch the player, never construct other screens. `Screen` is a Protocol (`display/screens/base.py`).
- **`display/manager.py`** — `ScreenManager` drives the machine: applies each event's side effects (player commands, screen construction), calls `transition()`, and refreshes the display — **full refresh on state changes, partial refresh for in-screen updates** (scroll, play/pause, skip, progress).

Transitions:

| From | Event | To |
|---|---|---|
| PODCAST_LIST | FeedSelected | EPISODE_LIST |
| EPISODE_LIST | EpisodeSelected | NOW_PLAYING (starts playback) |
| EPISODE_LIST | BackRequested | PODCAST_LIST |
| NOW_PLAYING | BackRequested (stops playback) | EPISODE_LIST |

Anything else is a no-op that keeps the current state.

`display` never imports `player`: playback flows through the `AudioPlayer` / `PlaybackState` Protocols in `display/playback.py`, which `PlayerController` satisfies structurally. `ScreenManager` wraps player calls in a broad `except Exception` (with a why-comment) because the player's exception types live above the display layer — a playback failure degrades to a log line, never a UI crash. This is also what makes the simulator work on Windows with no MPD.

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
```

## Display / UI

### Key Constraints

- **296×128px** — very small; font sizes and touch targets must be deliberate
- **Full refresh** (~2s) used for screen transitions
- **Partial refresh** (faster) used for in-screen updates (playback progress, time)
- E-ink uses Waveshare's SPI driver; touch uses I2C

### Screens

1. **Podcast List** — scrollable list of feed names; tap a row to enter
2. **Episode List** — episodes for selected feed (title + date, ● = unplayed); tap header to go back, tap a row to play
3. **Now Playing** — feed name, wrapped episode title (2 lines max), progress bar with elapsed/total times, bottom control bar

### Layout & Touch Zones

Shared list geometry lives in `display/screens/list_layout.py`:

- **Header** — 23px black bar (title; on Episode List it's also the back button, with a back icon)
- **Rows** — 3 visible rows × 35px, finger-sized
- **Scroll sidebar** — right-edge 36px column with up/down chevrons; chevrons only draw when scrolling that direction is possible; tap top half = up, bottom half = down; scrolls use partial refresh (no flicker)

Now Playing controls are bottom-anchored (y=95..128), four 74px-wide icon buttons: back, replay-30, play/pause (inverted black button, primary action), forward-30.

### Fonts & Icons

- **Text**: `assets/fonts/DejaVuSans.ttf`
- **Icons**: `assets/fonts/MaterialIcons-Regular.ttf` (Google Material Icons, Apache 2.0) — glyphs are `ICON_*` constants in `display/renderer.py`, codepoints verified against `MaterialIcons-Regular.codepoints` (kept alongside the font)
- Fonts load through `renderer.load_text_font(size)` / `load_icon_font(size)` (cached); `renderer.draw_icon_centered()` centers a glyph in a button rect

## Local Development (Windows)

The Pi Zero W can't run VS Code Remote SSH, so UI development happens locally with a simulator.

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
├── requirements.txt
├── pyproject.toml             # ruff + mypy config
├── main.py                    # entry point, DI wiring, poll loop
├── config.py                  # hardcoded FeedConfig list, settings
├── test_display.py            # Pi-only hardware smoke test
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
├── display/
│   ├── __init__.py
│   ├── events.py              # typed Event dataclasses
│   ├── state_machine.py       # AppState enum + pure transition()
│   ├── playback.py            # AudioPlayer / PlaybackState Protocols
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
│       ├── podcast_list.py
│       ├── episode_list.py
│       └── now_playing.py
└── assets/
    └── fonts/                 # DejaVuSans.ttf, MaterialIcons-Regular.ttf (+ .codepoints)
```

## Environment Setup

| Environment | Method |
|---|---|
| Local (Windows) | conda env, Python 3.11 |
| Pi Zero W | System Python (Pi OS Bookworm, 3.11), no venv |

```bash
# Local setup
conda create -n pi_media python=3.11
conda activate pi_media
pip install -r requirements.txt
```

On the Pi, install dependencies directly:
```bash
pip install -r requirements.txt
```

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
db              (knows config, knows nothing else)
    ↓
feeds / player  (know db, know config)
    ↓
display         (knows feeds/player through injected interfaces, never imports them directly)
    ↓
main            (imports everything, wires the graph, runs the loop)
```

A layer must never import from the layer above it. If you feel the urge to do so, the logic belongs in a different layer.

### Error Handling
- Each layer defines its own exception types:
  ```python
  class FeedFetchError(Exception): ...
  class DatabaseError(Exception): ...
  class PlayerError(Exception): ...
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

**Not yet verified on hardware** — everything above ran only against the tkinter simulator. First Pi deployment should confirm: Waveshare partial refresh actually looks right for scrolling, GT1151 touch coordinates map to the same 296×128 space the simulator uses, and MPD streaming works via `NowPlaying`.

### Phase 2 — Polish (next up)
- [ ] Episode played/unplayed tracking — `EpisodeRepository.mark_played()` and the ● unplayed marker already exist; hook marking into `ScreenManager._apply_side_effects` (on `EpisodeSelected`, or better: when playback passes some threshold), and refresh the cached episode screen so the marker updates
- [ ] Resume from last position — `play_position_sec` column and `EpisodeRepository.update_play_position()` already exist; persist position periodically from `refresh_playback()` and `seek()` after `play()` when reopening an episode
- [ ] Mid-session data refresh — the APScheduler background fetch already runs every 4h, but `PodcastListScreen` and cached `EpisodeListScreen` snapshots don't pick up newly fetched episodes until restart; re-query repositories on state entry (or on a fetch-completed signal)
- [ ] Error states on screen — `ScreenManager` currently degrades playback failures to log lines; surface "MPD unreachable" on the Now Playing screen instead of a dead progress bar

### Phase 3 — Future
- [ ] Feed management UI (add/remove RSS feeds) — device has no keyboard; plan is manual file sync of a feeds file the app reads instead of hardcoded `config.FEEDS`
- [ ] Listen history screen
- [ ] Web interface for remote management

## Key Notes

- MPD is already configured and running on the Pi. Use `python-mpd2` to connect on `localhost:6600`. If MPD is unreachable at startup, `main.py` logs and continues — the UI still comes up.
- Waveshare provides Python demo code on their wiki — use it as the display/touch driver base, don't rewrite from scratch.
- RSS feeds are hardcoded in `config.py` as `FeedConfig` frozen dataclasses (currently 4 feeds so scrolling is exercisable).
- No audio files stored locally — playback always streams from `episode.audio_url`.
- Partial refresh is used for all in-screen updates (scroll, play/pause toggle, skip, periodic progress redraw); full refresh only on state transitions.
- All UI development happens locally with `--simulate`. MPD integration is tested on the Pi only. On Windows every player command raises inside `ScreenManager._player_command` and becomes a log line — that's the expected simulator behavior, not a bug.
- To verify UI changes without clicking through the simulator: drive `ScreenManager` with scripted touches against a fake driver that saves each frame as a PNG (a capturing driver + fake player satisfying the Protocols is ~60 lines; see the Protocols in `display/drivers/base.py` and `display/playback.py`).
