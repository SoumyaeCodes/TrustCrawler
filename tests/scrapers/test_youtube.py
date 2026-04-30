import pytest

from src.errors import ScrapingError
from src.scrapers import youtube as yt_module
from src.scrapers.youtube import scrape_youtube


class _FakeSnippet:
    def __init__(self, text):
        self.text = text


def _mock_metadata(monkeypatch, **fields):
    base = {
        "title": "Sample Video",
        "uploader": "Sample Channel",
        "description": "A sample description with substantive content used "
                       "as a fallback when the transcript is not available "
                       "for whatever reason on the YouTube side.",
        "upload_date": "20240115",
        "channel_follower_count": 500_000,
        "channel_is_verified": True,
        "language": "en",
    }
    base.update(fields)
    monkeypatch.setattr(yt_module, "_fetch_metadata", lambda v: base)


def _mock_transcript(monkeypatch, segments=None, available=True):
    monkeypatch.setattr(
        yt_module,
        "_fetch_transcript",
        lambda video_id, language_hint: ([{"text": s} for s in (segments or [])], available),
    )


def test_resolve_video_id_bare():
    assert yt_module._resolve_video_id("aircAruvnKk") == "aircAruvnKk"


def test_resolve_video_id_watch_url():
    assert (
        yt_module._resolve_video_id("https://www.youtube.com/watch?v=aircAruvnKk&t=10s")
        == "aircAruvnKk"
    )


def test_resolve_video_id_short_url():
    assert yt_module._resolve_video_id("https://youtu.be/aircAruvnKk") == "aircAruvnKk"


def test_resolve_video_id_embed():
    assert (
        yt_module._resolve_video_id("https://www.youtube.com/embed/aircAruvnKk")
        == "aircAruvnKk"
    )


def test_resolve_video_id_invalid_raises():
    with pytest.raises(ScrapingError):
        yt_module._resolve_video_id("not a video at all")


def test_youtube_happy_path(monkeypatch):
    _mock_metadata(monkeypatch)
    segments = ["hello world this is a test"] * 30
    _mock_transcript(monkeypatch, segments=segments, available=True)

    raw, meta = scrape_youtube("aircAruvnKk")

    assert raw.source_type == "youtube"
    assert raw.author == "Sample Channel"
    assert str(raw.published_date) == "2024-01-15"
    assert raw.language == "en"
    assert raw.content_chunks  # transcript chunked
    assert meta["transcript_available"] is True
    assert meta["subscriber_count"] == 500_000
    assert meta["channel_verified"] is True
    assert meta["is_medical"] is False


def test_youtube_url_input(monkeypatch):
    _mock_metadata(monkeypatch)
    _mock_transcript(monkeypatch, segments=["hi"] * 30)
    raw, _ = scrape_youtube("https://www.youtube.com/watch?v=aircAruvnKk")
    assert "aircAruvnKk" in str(raw.source_url)


def test_youtube_transcripts_disabled_falls_back(monkeypatch):
    """REQUIRED per CLAUDE.md §10."""
    import youtube_transcript_api as yta

    _mock_metadata(monkeypatch, description="Fallback description used when no transcript exists.")

    class _FakeApiTD:
        def fetch(self, video_id, languages=None):
            raise yta.TranscriptsDisabled("dQw4w9WgXcQ")

    monkeypatch.setattr(yta, "YouTubeTranscriptApi", _FakeApiTD)

    raw, meta = scrape_youtube("dQw4w9WgXcQ")
    assert meta["transcript_available"] is False
    assert "Fallback description" in meta["body_text"]
    assert raw.content_chunks
    assert raw.content_chunks[0].startswith("Fallback description")


def test_youtube_no_transcript_no_description_uses_title(monkeypatch):
    _mock_metadata(monkeypatch, description="", title="Just A Title")
    _mock_transcript(monkeypatch, segments=[], available=False)
    raw, meta = scrape_youtube("aircAruvnKk")
    assert meta["transcript_available"] is False
    assert raw.content_chunks == ["Just A Title"]


def test_youtube_missing_subs_meta(monkeypatch):
    _mock_metadata(monkeypatch, channel_follower_count=None, channel_is_verified=False)
    _mock_transcript(monkeypatch, segments=["text"] * 20)
    _, meta = scrape_youtube("aircAruvnKk")
    assert meta["subscriber_count"] == 0
    assert meta["channel_verified"] is False


def test_youtube_invalid_upload_date(monkeypatch):
    _mock_metadata(monkeypatch, upload_date=None)
    _mock_transcript(monkeypatch, segments=["text"] * 20)
    raw, _ = scrape_youtube("aircAruvnKk")
    assert raw.published_date is None


def test_youtube_yt_dlp_failure_raises(monkeypatch):
    def boom(video_id):
        raise ScrapingError("yt-dlp failed", details={"error": "test"})
    monkeypatch.setattr(yt_module, "_fetch_metadata", boom)
    with pytest.raises(ScrapingError):
        scrape_youtube("aircAruvnKk")
