from __future__ import annotations

import httpx

from taxonfinder.config import InaturalistConfig
from taxonfinder.resolvers.cache import DiskCache, DiskCacheConfig
from taxonfinder.resolvers.inaturalist import INaturalistSearcher


def test_inaturalist_search_parses_results(tmp_path) -> None:
    payload = {
        "results": [
            {
                "id": 54586,
                "name": "Tilia",
                "rank": "genus",
                "preferred_common_name": {"name": "Lindens"},
                "matched_name": "липа",
                "score": 1.0,
                "ancestors": [
                    {"rank": "kingdom", "name": "Plantae"},
                    {"rank": "family", "name": "Malvaceae"},
                ],
                "names": [
                    {"locale": "ru", "name": "Липа"},
                ],
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    cache = DiskCache(DiskCacheConfig(path=tmp_path / "cache.db"))
    config = InaturalistConfig(base_url="https://api.inaturalist.org")

    searcher = INaturalistSearcher(http=client, config=config, cache=cache)
    results = searcher.search("липа", "ru")

    assert results[0].taxon_id == 54586
    assert results[0].taxonomy.kingdom == "Plantae"
    assert results[0].taxonomy.family == "Malvaceae"
    assert results[0].taxon_common_name_loc == "Липа"
