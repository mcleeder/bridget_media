from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from flask import Blueprint, Response, g, jsonify, request

import config
from db.database import DatabaseError
from db.models import Feed
from db.queries import EpisodeRepository, FeedRepository
from feeds.fetcher import FeedFetcher, FeedFetchError, InvalidFeedUrlError
from feeds.itunes_search import ItunesSearchClient, ItunesSearchError
from network.controller import NetworkController, NetworkError

logger = logging.getLogger(__name__)

api_blueprint = Blueprint("api", __name__)

_itunes_client = ItunesSearchClient()
_network = NetworkController(config.HOTSPOT_CREDENTIALS_PATH, config.NETWORK_SCAN_CACHE_PATH)

# Join attempts since the process started. Reset when the hotspot drops, which
# in practice means when the watchdog restarts networking — good enough for a
# control whose job is to stop a stranger grinding through passwords during a
# 20-minute window, on a device with one user.
_join_attempts = 0
_join_lock = threading.Lock()


def _feed_to_dict(feed: Feed) -> dict[str, object]:
    return {
        "id": feed.id,
        "name": feed.name,
        "url": feed.url,
        "last_fetched": feed.last_fetched.isoformat() if feed.last_fetched else None,
    }


@api_blueprint.get("/feeds")
def list_feeds() -> Response:
    repository = FeedRepository(g.db)
    feeds = repository.get_all()
    return jsonify([_feed_to_dict(feed) for feed in feeds])


@api_blueprint.post("/feeds")
def add_feed() -> tuple[Response, int]:
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    url = str(body.get("url", "")).strip()
    if not name or not url:
        return jsonify({"error": "name and url are required"}), 400

    feed_repository = FeedRepository(g.db)
    episode_repository = EpisodeRepository(g.db)
    fetcher = FeedFetcher(feed_repository, episode_repository)
    try:
        feed = fetcher.fetch_one(name, url)
    except InvalidFeedUrlError as exc:
        return jsonify({"error": str(exc)}), 400
    except FeedFetchError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(_feed_to_dict(feed)), 201


@api_blueprint.delete("/feeds/<int:feed_id>")
def delete_feed(feed_id: int) -> tuple[str, int]:
    repository = FeedRepository(g.db)
    repository.delete(feed_id)
    return "", 204


@api_blueprint.get("/search")
def search_podcasts() -> tuple[Response, int] | Response:
    term = request.args.get("q", "").strip()
    if not term:
        return jsonify([])

    offset = request.args.get("offset", default=0, type=int) or 0
    try:
        results = _itunes_client.search(term, offset=offset)
    except ItunesSearchError as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify(
        [
            {
                "name": result.name,
                "artist_name": result.artist_name,
                "feed_url": result.feed_url,
                "artwork_url": result.artwork_url,
            }
            for result in results
        ]
    )


def _require_hotspot() -> tuple[Response, int] | None:
    """Provisioning is reachable only from the setup hotspot.

    This is the structural control that replaces adding logins: a guest on the
    home LAN can meddle with podcasts, but cannot touch network config or read
    the list of networks the box can see. /api/network/status stays open
    because the frontend needs it to decide which view to open.
    """
    try:
        if _network.get_status().is_hotspot_active:
            return None
    except NetworkError:
        logger.exception("Could not confirm hotspot state; refusing network request")
    return jsonify({"error": "network setup is only available from the setup hotspot"}), 403


@api_blueprint.get("/network/status")
def network_status() -> tuple[Response, int] | Response:
    status = _network.get_status()
    return jsonify(
        {
            "is_online": status.is_online,
            "ssid": status.ssid,
            "ip_address": status.ip_address,
            "is_hotspot_active": status.is_hotspot_active,
        }
    )


@api_blueprint.get("/network/scan")
def network_scan() -> tuple[Response, int] | Response:
    refusal = _require_hotspot()
    if refusal is not None:
        return refusal
    # Deliberately the cached list, not a live scan: this endpoint is only
    # reachable while the hotspot is up, and the single radio cannot host an
    # AP and scan at the same time. The cache was taken moments before the AP
    # went up. See NetworkController._cache_scan_then_start.
    networks = _network.cached_networks()
    return jsonify(
        [
            {
                "ssid": network.ssid,
                "signal": network.signal,
                "is_secured": network.is_secured,
                "is_known": network.is_known,
            }
            for network in networks
        ]
    )


@api_blueprint.post("/network/join")
def network_join() -> tuple[Response, int]:
    """Accept credentials and answer *before* joining.

    Switching to the target network tears down the AP the caller is talking
    over, so a synchronous response would never arrive — the phone would show
    a failure for a join that actually worked. The real confirmation is on the
    e-ink panel, which is why the frontend says to watch it.
    """
    refusal = _require_hotspot()
    if refusal is not None:
        return refusal

    global _join_attempts
    with _join_lock:
        if _join_attempts >= config.MAX_JOIN_ATTEMPTS:
            return jsonify({"error": "too many join attempts — restart the box to try again"}), 429
        _join_attempts += 1

    body = request.get_json(silent=True) or {}
    ssid = str(body.get("ssid", "")).strip()
    password = str(body.get("password", ""))
    is_hidden = bool(body.get("is_hidden", False))
    if not ssid:
        return jsonify({"error": "ssid is required"}), 400

    _run_detached(lambda: _join_network(ssid, password, is_hidden))
    return jsonify({"status": "joining", "ssid": ssid}), 202


@api_blueprint.post("/network/forget")
def network_forget() -> tuple[Response, int]:
    refusal = _require_hotspot()
    if refusal is not None:
        return refusal
    body = request.get_json(silent=True) or {}
    ssid = str(body.get("ssid", "")).strip()
    if not ssid:
        return jsonify({"error": "ssid is required"}), 400
    _network.forget_network(ssid)
    return jsonify({"status": "forgotten", "ssid": ssid}), 200


def _join_network(ssid: str, password: str, is_hidden: bool) -> None:
    try:
        _network.join_network_from_hotspot(ssid, password, is_hidden)
    except NetworkError:
        # Nothing to answer to — the caller's connection died with the AP.
        # The panel is where the outcome shows up, so this only needs to
        # reach the journal. The message carries no password (see _run()).
        logger.exception("Background join failed for %s", ssid)


def _run_detached(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="network-join", daemon=True).start()


@api_blueprint.errorhandler(NetworkError)
def handle_network_error(exc: NetworkError) -> tuple[Response, int]:
    # NetworkError messages are redacted at the source, so this cannot leak a
    # Wi-Fi password even though it is echoed straight back to the caller.
    return jsonify({"error": str(exc)}), 502


@api_blueprint.errorhandler(DatabaseError)
def handle_database_error(exc: DatabaseError) -> tuple[Response, int]:
    return jsonify({"error": str(exc)}), 500
