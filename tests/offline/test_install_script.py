"""Offline: tools/install_remote_script.sh in a fake HOME (no Live)."""
import os, shutil, subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT = os.path.join(ROOT, "tools", "install_remote_script.sh")
pytestmark = __import__("pytest").mark.skipif(shutil.which("shasum") is None, reason="needs shasum")


def run(home, *args):
    env = dict(os.environ, HOME=str(home), FADERHAND_BACKUP_DIR=str(home / "bk"))
    r = subprocess.run(["bash", SCRIPT, *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def rs(home):
    return home / "Music" / "Ableton" / "User Library" / "Remote Scripts"


def cleanup_backups():
    pass


def test_fresh_install_only_creates_faderhand(tmp_path):
    try:
        run(tmp_path)
        assert (rs(tmp_path) / "Faderhand" / "__init__.py").exists()
        assert not (rs(tmp_path) / "WavReadBridge").exists()
    finally:
        cleanup_backups()


def test_existing_old_folder_is_updated_and_uninstall_spares_it(tmp_path):
    old = rs(tmp_path) / "WavReadBridge"
    other = rs(tmp_path) / "SomeOtherSurface"
    for d in (old, other):
        d.mkdir(parents=True)
        (d / "__init__.py").write_text("stale")
    try:
        run(tmp_path)
        assert "class Faderhand" in (old / "__init__.py").read_text()
        assert (other / "__init__.py").read_text() == "stale"
        run(tmp_path, "--uninstall")
        assert not (rs(tmp_path) / "Faderhand").exists()
        assert old.exists() and other.exists()
    finally:
        cleanup_backups()
