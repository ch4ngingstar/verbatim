import pytest
from ebooklib import epub as eb

from verbatim.ingest.epub import extract_cover, parse_epub


@pytest.fixture
def sample_epub(tmp_path):
    book = eb.EpubBook()
    book.set_identifier("test-id")
    book.set_title("Test Book")
    book.set_language("en")
    book.set_cover("cover.jpg", b"\xff\xd8\xff\xe0FAKEJPEG")

    chapters = []
    for i, (title, body) in enumerate([
        ("Chapter One", "<p>Anna walked in.</p><p>“Hello,” she said.</p>"),
        ("Table of Contents", "<p>1. Chapter One</p>"),
        ("Chapter Two", "<p>The end came quickly. " + "word " * 700 + "</p>"),
    ]):
        ch = eb.EpubHtml(title=title, file_name=f"ch{i}.xhtml", lang="en")
        ch.content = f"<h1>{title}</h1>{body}"
        book.add_item(ch)
        chapters.append(ch)

    book.toc = chapters
    book.add_item(eb.EpubNcx())
    book.add_item(eb.EpubNav())
    book.spine = ["nav", *chapters]
    path = tmp_path / "test.epub"
    eb.write_epub(str(path), book)
    return path


def test_parse_skips_boilerplate_and_indexes_chapters(sample_epub):
    parsed = parse_epub(sample_epub)
    titles = [c.title for c in parsed.chapters]
    assert titles == ["Chapter One", "Chapter Two"]
    assert parsed.total_chapters == 2
    assert parsed.chapters[0].chapter_index == 0
    assert parsed.chapters[1].chapter_index == 1


def test_chunks_respect_word_bounds(sample_epub):
    parsed = parse_epub(sample_epub)
    long_chapter = parsed.chapters[1]
    assert len(long_chapter.chunks) >= 2          # 700+ words must split
    for chunk in long_chapter.chunks:
        assert chunk.word_count <= 650            # CHUNK_MAX_WORDS


def test_parse_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_epub("does/not/exist.epub")


def test_extract_cover(sample_epub, tmp_path):
    out = extract_cover(sample_epub, tmp_path / "covers")
    assert out is not None
    assert out.exists()
    assert out.read_bytes().startswith(b"\xff\xd8")


def test_extract_cover_none_when_absent(tmp_path):
    book = eb.EpubBook()
    book.set_identifier("x")
    book.set_title("No Cover")
    book.set_language("en")
    ch = eb.EpubHtml(title="One", file_name="c.xhtml", lang="en")
    ch.content = "<h1>One</h1><p>text</p>"
    book.add_item(ch)
    book.add_item(eb.EpubNcx())
    book.add_item(eb.EpubNav())
    book.spine = [ch]
    path = tmp_path / "nocover.epub"
    eb.write_epub(str(path), book)
    assert extract_cover(path, tmp_path / "covers") is None
