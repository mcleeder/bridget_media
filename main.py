from __future__ import annotations

import argparse
import logging
import threading
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

import config
from db import Database, EpisodeRepository, FeedRepository, QueueRepository
from display.drivers.base import DisplayDriver
from display.manager import ScreenManager
from feeds import FeedFetcher
from player import PlayerController, PlayerError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

_POLL_INTERVAL_SEC: float = 0.1   # touch poll rate
_NOW_PLAYING_REFRESH_SEC: float = 5.0  # how often to redraw now-playing progress


def _build_driver(simulate: bool) -> DisplayDriver:
    if simulate:
        from display.drivers.simulator import SimulatorDriver
        return SimulatorDriver()
    from display.drivers.waveshare import WaveshareDriver
    return WaveshareDriver()


def main(simulate: bool) -> None:
    logger.info("Starting Pi Media (simulate=%s)", simulate)

    with Database(config.DB_PATH) as db:
        feed_repo = FeedRepository(db)
        episode_repo = EpisodeRepository(db)
        queue_repo = QueueRepository(db)
        fetcher = FeedFetcher(feed_repo, episode_repo)

        # The UI comes up from the database immediately; the first fetch (minutes
        # on the Pi) runs in the scheduler thread and the main loop reloads the
        # podcast list when this event fires.
        fetch_completed = threading.Event()

        def fetch_all_and_signal() -> None:
            fetcher.fetch_all()
            fetch_completed.set()

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            fetch_all_and_signal,
            trigger="interval",
            hours=config.FEED_REFRESH_INTERVAL_HOURS,
            next_run_time=datetime.now(),
            id="feed_refresh",
        )
        scheduler.start()
        logger.info("Feed fetch running in background; showing UI from database")

        driver = _build_driver(simulate)
        player = PlayerController()

        if not simulate:
            try:
                player.connect()
            except PlayerError:
                # The UI must still come up on the device even if MPD is down;
                # playback commands will log their own failures.
                logger.exception("Could not connect to MPD — starting without playback")

        manager = ScreenManager(
            driver=driver,
            feed_repository=feed_repo,
            episode_repository=episode_repo,
            queue_repository=queue_repo,
            player=player,
        )

        last_refresh = time.monotonic()

        try:
            while True:
                for x, y in driver.read_touch():
                    manager.handle_touch(x, y)

                if fetch_completed.is_set():
                    fetch_completed.clear()
                    manager.reload_feeds()

                now = time.monotonic()
                if now - last_refresh >= _NOW_PLAYING_REFRESH_SEC:
                    manager.refresh_playback()
                    last_refresh = now

                time.sleep(_POLL_INTERVAL_SEC)

        except KeyboardInterrupt:
            logger.info("Shutting down…")
        finally:
            scheduler.shutdown(wait=False)
            player.disconnect()
            driver.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pi Media podcast player")
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run with tkinter display simulator instead of e-ink hardware",
    )
    args = parser.parse_args()
    main(simulate=args.simulate)
