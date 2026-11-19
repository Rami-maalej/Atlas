from actions import file_controller


def test_write_to_directory_requires_filename(monkeypatch, tmp_path):
    monkeypatch.setattr(file_controller, "_is_safe_path", lambda _target: True)
    result = file_controller.write_file(str(tmp_path), content="Hello World")

    assert "filename" in result.lower()
    assert list(tmp_path.iterdir()) == []


def test_move_protected_root_requires_source_name(monkeypatch, tmp_path):
    home = tmp_path / "home"
    documents = tmp_path / "Documents"
    home.mkdir()
    documents.mkdir()
    monkeypatch.setattr(
        file_controller,
        "_resolve_path",
        lambda raw: {"home": home, "documents": documents}[raw.lower()],
    )
    monkeypatch.setattr(file_controller, "_SAFE_ROOTS", [home, documents])
    moved = []
    monkeypatch.setattr(file_controller.shutil, "move", lambda *args: moved.append(args))

    result = file_controller.move_file("home", destination="documents")

    assert "source" in result.lower() and "name" in result.lower()
    assert not moved
    assert home.is_dir()


def test_write_uses_file_name_alias(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(file_controller, "_resolve_path", lambda _raw: home)
    monkeypatch.setattr(file_controller, "_SAFE_ROOTS", [home])

    result = file_controller.file_controller({
        "action": "write",
        "path": "home",
        "file_name": "test.txt",
        "content": "Hello World",
    })

    assert "Written to" in result
    assert (home / "test.txt").read_text(encoding="utf-8") == "Hello World"


def test_move_uses_file_name_alias(monkeypatch, tmp_path):
    home = tmp_path / "home"
    documents = tmp_path / "Documents"
    home.mkdir()
    documents.mkdir()
    (home / "file.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(
        file_controller,
        "_resolve_path",
        lambda raw: {"home": home, "documents": documents}[raw.lower()],
    )
    monkeypatch.setattr(file_controller, "_SAFE_ROOTS", [home, documents])

    result = file_controller.file_controller({
        "action": "move",
        "path": "home",
        "file_name": "file.txt",
        "destination": "documents",
    })

    assert "Moved:" in result
    assert (documents / "file.txt").read_text(encoding="utf-8") == "hello"


def test_disk_usage_result_is_conversational(monkeypatch, tmp_path):
    from collections import namedtuple

    usage = namedtuple("Usage", "total used free")(
        int(474.4 * 1024**3), int(50.1 * 1024**3), int(424.3 * 1024**3)
    )
    monkeypatch.setattr(file_controller, "_resolve_path", lambda _path: tmp_path)
    monkeypatch.setattr(file_controller.shutil, "disk_usage", lambda _path: usage)

    result = file_controller.get_disk_usage("home")

    assert result.startswith("You have about 424.3 GB free")
    assert "474.4 GB total" in result


def test_recently_dated_question_bypasses_fast_general_path():
    from core.jarvis_general import is_general_question

    assert not is_general_question("Who won the Nobel Prize in 2024?")
    assert is_general_question("What is photosynthesis?")

def test_rename_rejects_traversal(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "a.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(file_controller, "_resolve_path", lambda _raw: home)
    monkeypatch.setattr(file_controller, "_is_safe_path", lambda p: home in p.parents or p == home)

    result = file_controller.rename_file("home", "a.txt", "../../evil.txt")

    assert "Invalid new name" in result
    assert (home / "a.txt").exists()


def test_download_rejects_non_http_scheme(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(file_controller, "_resolve_path", lambda _raw: tmp_path)
    monkeypatch.setattr(file_controller, "_is_safe_path", lambda _p: True)
    result = file_controller.download("file:///etc/passwd", destination="downloads")

    assert "http" in result.lower()
    assert not called
