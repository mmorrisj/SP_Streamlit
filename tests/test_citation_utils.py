"""Unit tests for shared.utils.citation_utils.build_hyperlink* helpers."""
import uuid

import pytest

from shared.utils.citation_utils import build_hyperlink, build_hyperlinks_chunked


def _uuid_ids(n: int) -> list[str]:
    return [str(uuid.uuid4()) for _ in range(n)]


def test_build_hyperlink_empty_returns_empty_string():
    assert build_hyperlink([]) == ""


def test_build_hyperlink_single_id_format():
    url = build_hyperlink(["abc123"])
    assert url.startswith("https://atom.opensource.gov/searches?ss=id%3A(")
    assert "%22abc123%22" in url
    assert url.endswith(")&go=1")
    assert "+OR+" not in url


def test_build_hyperlink_joins_with_or():
    url = build_hyperlink(["a", "b", "c"])
    assert "%22a%22+OR+%22b%22+OR+%22c%22" in url


def test_build_hyperlinks_chunked_empty():
    assert build_hyperlinks_chunked([]) == []


def test_build_hyperlinks_chunked_under_chunk_size_returns_one_url():
    ids = _uuid_ids(10)
    urls = build_hyperlinks_chunked(ids, chunk_size=80)
    assert len(urls) == 1


def test_build_hyperlinks_chunked_splits_at_boundary():
    ids = _uuid_ids(200)
    urls = build_hyperlinks_chunked(ids, chunk_size=80)
    assert len(urls) == 3  # 80 + 80 + 40


def test_build_hyperlinks_chunked_covers_all_ids():
    ids = _uuid_ids(173)
    urls = build_hyperlinks_chunked(ids, chunk_size=80)
    # every id should appear exactly once across all urls
    appearances = sum(url.count(f"%22{d}%22") for d in ids for url in urls)
    assert appearances == len(ids)


def test_build_hyperlinks_chunked_url_under_4kb_for_uuid_ids():
    """80 UUID ids should comfortably fit under a 4 KB URL budget."""
    ids = _uuid_ids(80)
    urls = build_hyperlinks_chunked(ids, chunk_size=80)
    assert len(urls) == 1
    assert len(urls[0]) < 4096


def test_build_hyperlinks_chunked_url_under_8kb_for_aggressive_chunk():
    """A 150-id chunk of UUIDs should still fit under the typical 8 KB server limit."""
    ids = _uuid_ids(150)
    urls = build_hyperlinks_chunked(ids, chunk_size=150)
    assert len(urls) == 1
    assert len(urls[0]) < 8192
