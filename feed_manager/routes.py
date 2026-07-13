from __future__ import annotations

from flask import Blueprint, Response, g, jsonify, request

from db.database import DatabaseError
from db.models import Feed
from db.queries import EpisodeRepository, FeedRepository
from feeds.fetcher import FeedFetcher, FeedFetchError
from feeds.itunes_search import ItunesSearchClient, ItunesSearchError

api_blueprint = Blueprint("api", __name__)

_itunes_client = ItunesSearchClient()


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


@api_blueprint.errorhandler(DatabaseError)
def handle_database_error(exc: DatabaseError) -> tuple[Response, int]:
    return jsonify({"error": str(exc)}), 500
