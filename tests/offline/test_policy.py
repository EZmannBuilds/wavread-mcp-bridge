"""Offline tests for the write-permission policy and the command classifier (no Live needed).
run: python3 -m unittest discover -s tests/offline -v
"""
import ast, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "..", "..", "remote_script", "Faderhand")
sys.path.insert(0, PKG)
import policy  # noqa: E402
from policy import READ, WRITE, META, TRANSPORT, PolicyError  # noqa: E402


def commands(path):
    t = ast.parse(open(path).read())
    return {n.name[4:] for n in ast.walk(t) if isinstance(n, ast.FunctionDef) and n.name.startswith("cmd_")}


ALL = commands(os.path.join(PKG, "__init__.py")) | commands(os.path.join(PKG, "ext.py"))
ID_A = {"file_path": "/sets/a.als", "set_id": "aaa", "doc_key": "s1", "name": "a"}


class Classifier(unittest.TestCase):
    def test_every_command_is_classified_explicitly(self):
        missing = sorted(c for c in ALL if c not in policy.CLASSES)
        self.assertEqual(missing, [], "classify these in policy.CLASSES")

    def test_no_stale_entries(self):
        stale = sorted(c for c in policy.CLASSES if c not in ALL)
        self.assertEqual(stale, [], "policy lists commands that no longer exist")

    def test_unknown_is_write(self):
        self.assertEqual(policy.classify("some_new_command"), WRITE)

    def test_mutating_commands_are_write(self):
        for c in ("set_device_parameter", "set_mixer", "set_track_send", "move_arrangement_clip",
                  "trim_arrangement_clip", "split_arrangement_clip", "record_track_audio",
                  "record_arrangement_automation", "set_automation_points", "create_track", "load_browser_item",
                  "create_audio_clip", "set_song_time", "set_arm", "delete_track"):
            self.assertEqual(policy.classify(c), WRITE, c)

    def test_inspection_is_read(self):
        for c in ("list_tracks", "get_device_parameters", "get_automation", "probe", "get_meters", "get_clip"):
            self.assertEqual(policy.classify(c), READ, c)

    def test_names_follow_prefix_conventions(self):
        for c in ALL:
            if c.startswith(("set_", "create_", "delete_", "insert_", "move_", "copy_", "split_", "trim_",
                             "record_arrangement_automation", "record_track_audio", "add_", "load_", "make_",
                             "restore_", "rename_", "duplicate_")) and not c.endswith("_status"):
                self.assertEqual(policy.classify(c), WRITE, c)
            if c.startswith(("list_", "get_", "inspect_", "validate_")):
                self.assertIn(policy.classify(c), (READ, META), c)


UNTITLED = {"file_path": "", "set_id": "", "doc_key": "s1", "name": ""}


class Gate(unittest.TestCase):
    """0.5.0: no approval codes. Edits run on any saved Set; untitled Sets and deletes outside a disposable Set are
    refused; transport that would record counts as an edit; stop always runs."""

    def test_no_code_flow_left(self):
        for gone in ("authorize_set", "confirm_authorization", "set_approval_mode", "revoke_authorization"):
            self.assertNotIn(gone, ALL)
            self.assertNotIn(gone, policy.CLASSES)
        for gone in ("Authorization", "Settings", "change_approval_mode", "CODE_TTL_S"):
            self.assertFalse(hasattr(policy, gone), gone)

    def test_writes_run_on_a_saved_set(self):
        for c in ("set_mixer", "create_track", "load_browser_item", "set_song_time", "brand_new"):
            self.assertEqual(policy.gate(c, {}, ID_A), WRITE, c)

    def test_untitled_set_refused(self):
        for c in ("set_mixer", "create_track", "brand_new"):
            with self.assertRaises(PolicyError):
                policy.gate(c, {}, UNTITLED)

    def test_reads_run_anywhere(self):
        for c in ("list_tracks", "get_set_identity", "write_status", "transport", "show_view"):
            policy.gate(c, {}, UNTITLED)

    def test_deletes_need_scratch(self):
        for c in policy.DELETES:
            with self.assertRaises(PolicyError):
                policy.gate(c, {}, ID_A, scratch=False)
            policy.gate(c, {}, ID_A, scratch=True)

    def test_stop_always_allowed_even_recording(self):
        for action in ("stop", "stop_all_clips"):
            policy.gate("transport", {"action": action}, UNTITLED, transport_records=True)
        with self.assertRaises(PolicyError):
            policy.gate("transport", {"action": "continue"}, UNTITLED, transport_records=True)

    def test_transport_that_records_is_write(self):
        policy.gate("transport", {"action": "play"}, UNTITLED, transport_records=False)
        for name in ("transport", "fire_clip"):
            self.assertEqual(policy.gate(name, {"action": "play"}, ID_A, transport_records=True), WRITE)
            with self.assertRaises(PolicyError):
                policy.gate(name, {"action": "play"}, UNTITLED, transport_records=True)

    def test_fire_clip_that_would_record_is_write(self):
        policy.gate("fire_clip", {"track": 0, "slot": 0}, UNTITLED, fire_would_record=False)
        with self.assertRaises(PolicyError):
            policy.gate("fire_clip", {"track": 0, "slot": 0}, UNTITLED, fire_would_record=True)


class Validation(unittest.TestCase):
    def test_bad_names_and_types(self):
        for bad in ("Bad", "x;rm", "", "a" * 80):
            with self.assertRaises(PolicyError):
                policy.validate_params(bad, {})
        with self.assertRaises(PolicyError):
            policy.validate_params("list_tracks", {"x": object()})
        with self.assertRaises(PolicyError):
            policy.validate_params("list_tracks", {"x": "a\x00b"})
        with self.assertRaises(PolicyError):
            policy.validate_params("list_tracks", [])

    def test_audio_paths(self):
        d = tempfile.mkdtemp()
        wav = os.path.join(d, "x.wav")
        with open(wav, "wb") as f:
            f.write(b"RIFF")
        policy.validate_params("create_audio_clip", {"path": wav})
        for bad in ("relative.wav", os.path.join(d, "..", os.path.basename(d), "x.wav"), os.path.join(d, "x.txt"),
                    os.path.join(d, "missing.wav"), "", None):
            with self.assertRaises(PolicyError, msg=repr(bad)):
                policy.validate_params("create_audio_clip", {"path": bad})


if __name__ == "__main__":
    unittest.main()
