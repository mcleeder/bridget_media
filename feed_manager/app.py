from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, Response, g, send_from_directory

import config
from db.database import Database
from db.queries import FeedRepository
from feed_manager.routes import api_blueprint
from feeds.seed import seed_default_feeds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

_FRONTEND_DIST: Path = Path(__file__).parent / "frontend" / "dist"


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(_FRONTEND_DIST), static_url_path="")
    app.register_blueprint(api_blueprint, url_prefix="/api")

    @app.before_request
    def _open_db() -> None:
        g.db = Database(config.DB_PATH)

    @app.teardown_request
    def _close_db(exc: BaseException | None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.route("/")
    def index() -> Response:
        return send_from_directory(str(_FRONTEND_DIST), "index.html")

    return app


if __name__ == "__main__":
    with Database(config.DB_PATH) as seed_db:
        seed_default_feeds(FeedRepository(seed_db))

    application = create_app()
    logger.info("Feed manager listening on port %d", config.FEED_MANAGER_PORT)
    application.run(host="0.0.0.0", port=config.FEED_MANAGER_PORT, threaded=False)
