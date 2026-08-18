from __future__ import annotations

import argparse
import ipaddress
import logging
from pathlib import Path
from typing import Final

from flask import Flask, Response, g, jsonify, redirect, request, send_from_directory
from waitress import serve
from werkzeug.wrappers import Response as WerkzeugResponse

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


def _is_hotspot_client(remote_address: str | None) -> bool:
    """True for a phone connected to our own setup hotspot.

    NetworkManager's shared mode always hands out this /24, so the client's
    address is a cheap, exact signal — no nmcli call per request.
    """
    if not remote_address:
        return False
    try:
        return ipaddress.ip_address(remote_address) in ipaddress.ip_network(config.HOTSPOT_SUBNET)
    except ValueError:
        return False


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(_FRONTEND_DIST), static_url_path="")
    app.register_blueprint(api_blueprint, url_prefix="/api")

    # Registered first so a rejected Host never reaches the database.
    @app.before_request
    def _check_host() -> tuple[Response, int] | None:
        if _is_allowed_host(request.host):
            return None
        # Captive-portal DNS answers *every* hostname with this box's address,
        # so a phone's probe arrives as Host: connectivitycheck.gstatic.com —
        # which the allowlist above rightly refuses. Clients on the hotspot
        # subnet are therefore let through to be redirected to the portal, but
        # only for page requests: /api/ keeps strict host checking everywhere,
        # so nothing that reads or changes state loses rebinding protection.
        if _is_hotspot_client(request.remote_addr) and not request.path.startswith("/api/"):
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

    # The URLs phones fetch to decide whether a network has working internet.
    # Answering them with a redirect instead of the expected 204/success is
    # what pops the "Sign in to network" sheet. Best-effort by design: Android
    # increasingly just asks whether to stay connected, so the e-ink panel
    # states the hotspot name and portal URL outright rather than relying on
    # this firing.
    @app.route("/hotspot-detect.html")  # iOS / macOS
    @app.route("/library/test/success.html")  # iOS, older
    @app.route("/generate_204")  # Android
    @app.route("/gen_204")  # Android, older
    @app.route("/ncsi.txt")  # Windows
    @app.route("/connecttest.txt")  # Windows
    @app.route("/canonical.html")  # Ubuntu / GNOME
    def captive_portal_probe() -> WerkzeugResponse:
        return redirect(config.PORTAL_URL, code=302)

    @app.errorhandler(404)
    def unknown_path(exc: object) -> tuple[Response, int] | WerkzeugResponse:
        """Send stray requests to the portal, but only from the hotspot.

        Wildcard DNS in AP mode points every hostname at this box, so a phone
        opening any address at all lands on the setup page. On the home
        network this stays a plain 404 — silently redirecting every typo
        would be baffling.
        """
        if not request.path.startswith("/api/") and _is_hotspot_client(request.remote_addr):
            return redirect(config.PORTAL_URL, code=302)
        return jsonify({"error": "not found"}), 404

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
