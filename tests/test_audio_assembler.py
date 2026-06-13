"""GPU-free tests for AudioAssembler and M4BExporter.

_run_ffmpeg / _dispatch_ffmpeg are monkeypatched — no FFmpeg binary required.
"""

import sys
from pathlib import Path

import pytest

VERBATIM_SRC = str(Path(__file__).parent.parent / "src")
if VERBATIM_SRC not in sys.path:
    sys.path.insert(0, VERBATIM_SRC)

from verbatim.audio.assembler import AudioAssembler
from verbatim.audio.m4b import M4BExporter
from verbatim.tts.emotion import wav_silence

# -- Helpers ------------------------------------------------------------------

def _make_wav(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav_silence(100))
    return path


def _fake_ffmpeg(cmd: list[str]) -> None:
    """Stub that writes an empty file to the output path instead of calling ffmpeg."""
    # Output is always the last argument in our commands
    out = Path(cmd[-1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"FAKE_MP3")


# -- AudioAssembler tests -----------------------------------------------------

def test_assembler_calls_ffmpeg(tmp_path, monkeypatch):
    """assemble_chapter invokes _run_ffmpeg with the concat command."""
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "data"))
    from verbatim import config as cfg_mod

    wav1 = _make_wav(tmp_path / "data" / "audio" / "ch_0001" / "line_0000.wav")
    wav2 = _make_wav(tmp_path / "data" / "audio" / "ch_0001" / "line_0001.wav")

    lines = [
        {"id": 1, "line_index": 0, "audio_path": cfg_mod.to_stored(wav1)},
        {"id": 2, "line_index": 1, "audio_path": cfg_mod.to_stored(wav2)},
    ]

    called_cmds: list[list[str]] = []
    asm = AudioAssembler()
    asm._run_ffmpeg = lambda cmd: (called_cmds.append(cmd), _fake_ffmpeg(cmd))[1]

    out = tmp_path / "output" / "ch_0001.mp3"
    asm.assemble_chapter(lines, out, title="Chapter 1", track_num=1)

    assert len(called_cmds) == 1
    cmd = called_cmds[0]
    assert "concat" in cmd
    assert str(out) in cmd


def test_assembler_skips_missing_wavs(tmp_path, monkeypatch):
    """Lines with missing WAV files are skipped without raising."""
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "data"))
    from verbatim import config as cfg_mod

    wav1 = _make_wav(tmp_path / "data" / "audio" / "ch_0001" / "line_0000.wav")
    lines = [
        {"id": 1, "line_index": 0, "audio_path": cfg_mod.to_stored(wav1)},
        {"id": 2, "line_index": 1, "audio_path": "audio/ch_0001/line_MISSING.wav"},
    ]

    asm = AudioAssembler()
    asm._run_ffmpeg = _fake_ffmpeg
    out = tmp_path / "output" / "ch_0001.mp3"
    asm.assemble_chapter(lines, out)
    # Should have assembled the one valid WAV without raising
    assert out.exists()


def test_assembler_raises_on_no_wavs(tmp_path, monkeypatch):
    """assemble_chapter raises ValueError when no WAV files are available."""
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "data"))

    asm = AudioAssembler()
    asm._run_ffmpeg = _fake_ffmpeg
    with pytest.raises(ValueError, match="No WAV files"):
        asm.assemble_chapter([], tmp_path / "out.mp3")


def test_assembler_respects_line_order(tmp_path, monkeypatch):
    """Concat list must list lines in ascending line_index order."""
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "data"))
    from verbatim import config as cfg_mod

    wav0 = _make_wav(tmp_path / "data" / "audio" / "ch_0002" / "line_0000.wav")
    wav1 = _make_wav(tmp_path / "data" / "audio" / "ch_0002" / "line_0001.wav")
    wav2 = _make_wav(tmp_path / "data" / "audio" / "ch_0002" / "line_0002.wav")

    # Deliberately shuffle order
    lines = [
        {"id": 3, "line_index": 2, "audio_path": cfg_mod.to_stored(wav2)},
        {"id": 1, "line_index": 0, "audio_path": cfg_mod.to_stored(wav0)},
        {"id": 2, "line_index": 1, "audio_path": cfg_mod.to_stored(wav1)},
    ]

    concat_contents: list[str] = []

    def _capture(cmd: list[str]) -> None:
        # Read the concat file path (-i argument after "-f concat -safe 0")
        i = cmd.index("-i")
        concat_path = Path(cmd[i + 1])
        concat_contents.append(concat_path.read_text())
        _fake_ffmpeg(cmd)

    asm = AudioAssembler()
    asm._run_ffmpeg = _capture
    asm.assemble_chapter(lines, tmp_path / "out.mp3")

    entries = [e for e in concat_contents[0].splitlines() if e.startswith("file")]
    # Filter out silence entries — only count the 3 real WAVs
    real = [e for e in entries if "line_" in e]
    assert real[0].endswith("line_0000.wav'")
    assert real[1].endswith("line_0001.wav'")
    assert real[2].endswith("line_0002.wav'")


# -- M4BExporter tests --------------------------------------------------------

def test_m4b_exporter_creates_output(tmp_path):
    """M4BExporter.export invokes ffmpeg twice and produces the output file."""
    mp3_1 = _make_wav(tmp_path / "ch_0001.mp3")
    mp3_2 = _make_wav(tmp_path / "ch_0002.mp3")

    chapters = [
        {"audio_path": str(mp3_1), "title": "Chapter 1", "duration_ms": 60000},
        {"audio_path": str(mp3_2), "title": "Chapter 2", "duration_ms": 90000},
    ]

    ffmpeg_calls: list[list[str]] = []

    def _capture(cmd: list[str]) -> None:
        ffmpeg_calls.append(cmd)
        _fake_ffmpeg(cmd)

    exp = M4BExporter()
    exp._run_ffmpeg = _capture
    out = tmp_path / "book.m4b"
    exp.export(chapters, out, book_title="My Book", author="Author")

    assert len(ffmpeg_calls) == 2  # concat → intermediate, then mux
    assert out.exists()


def test_m4b_chapter_markers(tmp_path):
    """FFMETADATA file contains correct chapter START/END markers."""
    mp3_1 = _make_wav(tmp_path / "ch_0001.mp3")
    mp3_2 = _make_wav(tmp_path / "ch_0002.mp3")

    chapters = [
        {"audio_path": str(mp3_1), "title": "Intro", "duration_ms": 10000},
        {"audio_path": str(mp3_2), "title": "Part 1", "duration_ms": 20000},
    ]

    meta_texts: list[str] = []

    def _capture(cmd: list[str]) -> None:
        # The meta file is the second -i argument
        if "-i" in cmd:
            idxs = [i for i, v in enumerate(cmd) if v == "-i"]
            for idx in idxs:
                p = Path(cmd[idx + 1])
                if p.suffix == ".ffmeta":
                    meta_texts.append(p.read_text())
        _fake_ffmpeg(cmd)

    exp = M4BExporter()
    exp._run_ffmpeg = _capture
    exp.export(chapters, tmp_path / "book.m4b")

    assert meta_texts, "ffmetadata file was never read"
    meta = meta_texts[0]
    assert "START=0" in meta
    assert "END=10000" in meta
    assert "START=10000" in meta
    assert "END=30000" in meta


def test_m4b_raises_on_empty(tmp_path):
    """M4BExporter.export raises ValueError when given no chapters."""
    exp = M4BExporter()
    with pytest.raises(ValueError, match="No chapters"):
        exp.export([], tmp_path / "out.m4b")
