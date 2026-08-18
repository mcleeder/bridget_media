from __future__ import annotations

import argparse
import ipaddress
import logging
from pathlib import Path
from typing import Final

from flask import Flask, Response, g, jsonify, request, send_from_directory
from waitress import serve

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

# Names this app answers to. Anything else is either a misconfiguration or a
# DNS-rebinding attempt — an attacker's domain pointed at the device's private
# address, which is the standard way to reach an unauthenticated LAN service
# from a browser. Plain CSRF is already largely blocked (JSON content-type on
# POST, a CORS preflight on DELETE), but rebinding defeats both.
_ALLOWED_HOST_NAMES: Final[frozenset[str]] = frozenset(
    {config.FEED_MANAGER_HOST, config.MDNS_HOSTNAME, "localhost"}
)


def _hostname_only(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):  # IPv6 literal, e.g. [::1]:80
        return host.partition("]")[0].lstrip("[")
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


def _is_allowed_host(host_header: str) -> bool:
    hostname = _hostname_only(host_header)
    if not hostname:
        return False
    if hostname in _ALLOWED_HOST_NAMES:
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        # A name nobody here owns. The device's own LAN address changes with
        # the router, so addresses are allowed by range below rather than by
        # being listed — but names are not.
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(_FRONTEND_DIST), static_url_path="")
    app.register_blueprint(api_blueprint, url_prefix="/api")

    # Registered first so a rejected Host never reaches the database.
    @app.before_request
    def _check_host() -> tuple[Response, int] | None:
        if _is_allowed_host(request.host):
            return None
        logger.warning("Rejected request with Host header %r", request.host)
        return jsonify({"error": "unrecognised host"}), 403

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Pi Media feed manager")
    parser.add_argument(
        "--port",
        type=int,
        default=config.FEED_MANAGER_PORT,
        help="port to listen on (default %(default)s; use 8000 for local dev, "
        "which is what the Vite proxy expects)",
    )
    args = parser.parse_args()

    with Database(config.DB_PATH) as seed_db:
        seed_default_feeds(FeedRepository(seed_db))

    logger.info("Feed manager listening on port %d", args.port)
    # waitress, not app.run(): Werkzeug's dev server is explicitly not for
    # production, and this one holds port 80 on a box nobody can SSH into. It
    # also retires the single-threaded mode the dev server ran in, where one
    # slow feed fetch blocked the whole app.
    serve(create_app(), host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
