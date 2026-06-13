from verbatim import config


def test_data_root_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "mydata"))
    root = config.data_root()
    assert root == (tmp_path / "mydata").resolve()
    assert root.is_dir()  # created on demand


def test_data_root_default_is_cwd_data(tmp_path, monkeypatch):
    monkeypatch.delenv("VERBATIM_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert config.data_root() == (tmp_path / "data").resolve()


def test_roundtrip_relative_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path))
    f = tmp_path / "voices" / "clip.wav"
    f.parent.mkdir()
    f.write_bytes(b"x")
    rel = config.to_stored(f)
    assert rel == "voices/clip.wav"  # forward slashes, no drive letter
    assert config.from_stored(rel) == f.resolve()


def test_to_stored_rejects_path_outside_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path / "root"))
    outside = tmp_path / "elsewhere" / "clip.wav"
    try:
        config.to_stored(outside)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_from_stored_passes_through_absolute(tmp_path, monkeypatch):
    monkeypatch.setenv("VERBATIM_DATA_DIR", str(tmp_path))
    p = (tmp_path / "x.wav").resolve()
    assert config.from_stored(str(p)) == p
