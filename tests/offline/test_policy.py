"""Offline tests for the write-permission policy and the command classifier (no Live needed).
run: python3 -m unittest discover -s tests/offline -v
"""
import ast, os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "..", "..", "remote_script", "WavReadBridge")
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
                             "restore_", "rename_", "duplicate_")) and not c.endswith("_status") \
                    and c != "set_approval_mode":    # META by design: its own guard (off needs an authorized Set)
                self.assertEqual(policy.classify(c), WRITE, c)
            if c.startswith(("list_", "get_", "inspect_", "validate_")):
                self.assertIn(policy.classify(c), (READ, META), c)


class Authorization(unittest.TestCase):
    def setUp(self):
        self.a = policy.Authorization()

    def test_fails_closed_without_authorization(self):
        with self.assertRaises(PolicyError):
            self.a.check_write("set_mixer", ID_A)

    def test_authorize_requires_exact_identity(self):
        with self.assertRaises(PolicyError):
            self.a.authorize(ID_A, "/sets/other.als", "aaa")
        with self.assertRaises(PolicyError):
            self.a.authorize(ID_A, "/sets/a.als", "zzz")
        self.assertTrue(self.a.authorize(ID_A, "/sets/a.als", "aaa")["authorized"])
        self.a.check_write("set_mixer", ID_A)

    def test_set_without_id_cannot_be_authorized(self):
        with self.assertRaises(PolicyError):
            self.a.authorize(dict(ID_A, set_id=""), "/sets/a.als", "")

    def test_switching_sets_revokes(self):
        self.a.authorize(ID_A, "/sets/a.als", "aaa")
        for other in (dict(ID_A, file_path="/sets/b.als"), dict(ID_A, set_id="bbb"), dict(ID_A, doc_key="s2"),
                      dict(ID_A, file_path="")):
            self.a.authorize(ID_A, "/sets/a.als", "aaa")
            with self.assertRaises(PolicyError):
                self.a.check_write("set_mixer", other)
            # and it stays revoked, even back on the original Set
            with self.assertRaises(PolicyError):
                self.a.check_write("set_mixer", ID_A)
            self.assertIsNotNone(self.a.last_revoked)

    def test_revoke(self):
        self.a.authorize(ID_A, "/sets/a.als", "aaa")
        self.a.revoke()
        with self.assertRaises(PolicyError):
            self.a.check_write("set_mixer", ID_A)

    def test_deletes_also_need_scratch(self):
        self.a.authorize(ID_A, "/sets/a.als", "aaa")
        with self.assertRaises(PolicyError):
            self.a.check_write("delete_track", ID_A, scratch=False)
        self.a.check_write("delete_track", ID_A, scratch=True)


class CodeFlow(unittest.TestCase):
    """Human approval (0.4.0): authorize_set -> code in Live's status bar only -> confirm_authorization(code)."""

    def setUp(self):
        self.a = policy.Authorization()

    def request(self, now=1000.0, ident=ID_A):
        return self.a.request(ident, ident["file_path"], ident["set_id"], now)

    def test_request_alone_grants_nothing(self):
        self.request()
        with self.assertRaises(PolicyError):
            self.a.check_write("set_mixer", ID_A)
        self.assertFalse(self.a.status(ID_A)["authorized"])

    def test_code_never_in_the_reply_or_status(self):
        reply, code = self.request()
        self.assertEqual(len(code), policy.CODE_LENGTH)
        self.assertTrue(set(code) <= set(policy.CODE_ALPHABET))
        self.assertNotIn(code, repr(reply))
        self.assertNotIn(code, repr(self.a.status(ID_A)))

    def test_right_code_grants(self):
        reply, code = self.request()
        self.assertTrue(self.a.confirm(ID_A, code, 1001.0)["authorized"])
        self.a.check_write("set_mixer", ID_A)

    def test_code_is_case_and_space_tolerant(self):
        reply, code = self.request()
        self.assertTrue(self.a.confirm(ID_A, " %s " % code.lower(), 1001.0)["authorized"])

    def test_no_pending_request_refused(self):
        with self.assertRaises(PolicyError):
            self.a.confirm(ID_A, "ABCDEF", 1001.0)

    def test_wrong_code_refused_and_clears(self):
        reply, code = self.request()
        wrong = "".join("A" if c != "A" else "B" for c in code)
        with self.assertRaises(PolicyError):
            self.a.confirm(ID_A, wrong, 1001.0)
        with self.assertRaises(PolicyError):           # the right code no longer works: one attempt
            self.a.confirm(ID_A, code, 1002.0)
        with self.assertRaises(PolicyError):
            self.a.check_write("set_mixer", ID_A)

    def test_expired_code_refused(self):
        reply, code = self.request(now=1000.0)
        with self.assertRaises(PolicyError):
            self.a.confirm(ID_A, code, 1000.0 + policy.CODE_TTL_S + 1)
        with self.assertRaises(PolicyError):
            self.a.check_write("set_mixer", ID_A)

    def test_set_changed_before_confirm_refused(self):
        reply, code = self.request()
        with self.assertRaises(PolicyError):
            self.a.confirm(dict(ID_A, file_path="/sets/b.als"), code, 1001.0)

    def test_untitled_refused_everywhere(self):
        untitled = dict(ID_A, file_path="")
        with self.assertRaises(PolicyError):
            self.a.request(untitled, "", "aaa", 1000.0)
        with self.assertRaises(PolicyError):
            self.a.authorize(untitled, "", "aaa")
        self.a.authorize(ID_A, "/sets/a.als", "aaa")
        with self.assertRaises(PolicyError):
            self.a.check_write("set_mixer", untitled)

    def test_codes_differ(self):
        codes = {self.request(now=1000.0 + 61.0 * i)[1] for i in range(50)}   # spaced past the rate limit
        self.assertGreater(len(codes), 45)

    def test_revoke_clears_pending(self):
        reply, code = self.request()
        self.a.revoke()
        with self.assertRaises(PolicyError):
            self.a.confirm(ID_A, code, 1001.0)


class Hardening(unittest.TestCase):
    """Round-2 review additions."""

    def setUp(self):
        self.a = policy.Authorization()

    def test_codes_come_from_secrets(self):
        src = open(os.path.join(PKG, "policy.py")).read()
        self.assertIn("secrets.choice", src)
        self.assertNotIn("import random", src)

    def test_request_rate_limit(self):
        for k in range(policy.CODE_REQUESTS_PER_MIN):
            self.a.request(ID_A, ID_A["file_path"], ID_A["set_id"], 1000.0 + k)
        with self.assertRaises(PolicyError):
            self.a.request(ID_A, ID_A["file_path"], ID_A["set_id"], 1010.0)
        self.a.request(ID_A, ID_A["file_path"], ID_A["set_id"], 1061.0)      # a minute later it works again

    def test_replaced_code_refused(self):
        r1, c1 = self.a.request(ID_A, ID_A["file_path"], ID_A["set_id"], 1000.0)
        r2, c2 = self.a.request(ID_A, ID_A["file_path"], ID_A["set_id"], 1001.0)
        if c1 != c2:
            with self.assertRaises(PolicyError):
                self.a.confirm(ID_A, c1, 1002.0)

    def test_replayed_code_refused(self):
        r, c = self.a.request(ID_A, ID_A["file_path"], ID_A["set_id"], 1000.0)
        self.a.confirm(ID_A, c, 1001.0)
        with self.assertRaises(PolicyError):
            self.a.confirm(ID_A, c, 1002.0)

    def test_pending_code_bound_to_session(self):
        r, c = self.a.request(ID_A, ID_A["file_path"], ID_A["set_id"], 1000.0)
        with self.assertRaises(PolicyError):
            self.a.confirm(dict(ID_A, doc_key="s2"), c, 1001.0)          # another control-script session

    def test_inactivity_revokes(self):
        r, c = self.a.request(ID_A, ID_A["file_path"], ID_A["set_id"], 1000.0)
        self.a.confirm(ID_A, c, 1000.0)
        self.a.check_write("set_mixer", ID_A, now=1000.0 + policy.WRITE_IDLE_S - 10)    # a write resets the clock
        self.a.check_write("set_mixer", ID_A, now=1000.0 + 2 * policy.WRITE_IDLE_S - 20)
        with self.assertRaises(PolicyError):
            self.a.check_write("set_mixer", ID_A, now=1000.0 + 4 * policy.WRITE_IDLE_S)
        self.assertIn("no edits", self.a.last_revoked)

    def test_stop_always_allowed_even_recording(self):
        for action in ("stop", "stop_all_clips"):
            policy.gate(self.a, "transport", {"action": action}, ID_A, transport_records=True)
        with self.assertRaises(PolicyError):
            policy.gate(self.a, "transport", {"action": "continue"}, ID_A, transport_records=True)

    def test_transport_that_records_is_write(self):
        policy.gate(self.a, "transport", {"action": "play"}, ID_A, transport_records=False)
        for name in ("transport", "fire_clip"):
            with self.assertRaises(PolicyError):
                policy.gate(self.a, name, {"action": "play"}, ID_A, transport_records=True)

    def test_code_never_leaks(self):
        r, c = self.a.request(ID_A, ID_A["file_path"], ID_A["set_id"], 1000.0)
        texts = [repr(r), repr(self.a.status(ID_A))]
        for bad in ("ZZZZZZ", c.lower()[:-1], ""):
            r2, c2 = self.a.request(ID_A, ID_A["file_path"], ID_A["set_id"], 1100.0 + len(texts))
            try:
                self.a.confirm(ID_A, bad, 1101.0 + len(texts))
            except PolicyError as e:
                texts.append(str(e))
            texts.append(repr(r2))
            for t in texts:
                self.assertNotIn(c2, t)
            self.a = policy.Authorization()
        for t in texts:
            self.assertNotIn(c, t)
        # the control script only ever passes the code to show_message, never to log_message or a reply
        core = open(os.path.join(PKG, "__init__.py")).read()
        for line in core.splitlines():
            if "log_message" in line:
                self.assertNotIn("code", line.split("log_message", 1)[1], line)
        self.assertIn("reply, code = self._auth.request", core)
        self.assertIn("return reply", core)


class ApprovalSetting(unittest.TestCase):
    """The user's 'approval off' setting (0.4.0)."""

    def setUp(self):
        self.a = policy.Authorization()
        self.dir = tempfile.mkdtemp()
        self.st = policy.Settings(os.path.join(self.dir, "sub", "settings.json"))

    def test_default_and_unreadable_are_code(self):
        self.assertEqual(self.st.load(), policy.APPROVAL_CODE)
        os.makedirs(os.path.dirname(self.st.path))
        with open(self.st.path, "w") as f:
            f.write("{not json")
        self.assertEqual(self.st.load(), policy.APPROVAL_CODE)
        with open(self.st.path, "w") as f:
            f.write('{"approval": "maybe"}')
        self.assertEqual(self.st.load(), policy.APPROVAL_CODE)

    def test_turning_off_needs_one_approval(self):
        with self.assertRaises(PolicyError):
            policy.change_approval_mode(self.a, self.st, ID_A, policy.APPROVAL_OFF)
        r, c = self.a.request(ID_A, ID_A["file_path"], ID_A["set_id"], 1000.0)
        reply = self.a.confirm(ID_A, c, 1001.0)
        self.assertIn("set_approval_mode('off')", reply["next_step"])
        policy.change_approval_mode(self.a, self.st, ID_A, policy.APPROVAL_OFF)
        self.assertEqual(self.st.load(), policy.APPROVAL_OFF)       # persisted

    def test_authorization_for_another_set_cant_turn_it_off(self):
        self.a.authorize(ID_A, "/sets/a.als", "aaa")
        with self.assertRaises(PolicyError):
            policy.change_approval_mode(self.a, self.st, dict(ID_A, file_path="/sets/b.als"), policy.APPROVAL_OFF)

    def test_turning_on_always_allowed(self):
        self.assertEqual(policy.change_approval_mode(self.a, self.st, ID_A, policy.APPROVAL_CODE)["approval"], "code")
        with self.assertRaises(PolicyError):
            policy.change_approval_mode(self.a, self.st, ID_A, "sometimes")

    def test_off_allows_writes_without_codes_but_keeps_guards(self):
        other = dict(ID_A, file_path="/sets/b.als", set_id="bbb", doc_key="s9")
        policy.gate(self.a, "set_mixer", {"track": 0}, other, approval=policy.APPROVAL_OFF)
        with self.assertRaises(PolicyError):                        # untitled still refused
            policy.gate(self.a, "set_mixer", {}, dict(other, file_path=""), approval=policy.APPROVAL_OFF)
        with self.assertRaises(PolicyError):                        # deletes still need a disposable Set
            policy.gate(self.a, "delete_track", {"track": 0}, other, approval=policy.APPROVAL_OFF, scratch=False)
        policy.gate(self.a, "delete_track", {"track": 0}, other, approval=policy.APPROVAL_OFF, scratch=True)
        with self.assertRaises(PolicyError):                        # and with codes on, refused as before
            policy.gate(self.a, "set_mixer", {"track": 0}, other, approval=policy.APPROVAL_CODE)


class Gate(unittest.TestCase):
    def setUp(self):
        self.a = policy.Authorization()

    def test_read_meta_transport_pass_unauthorized(self):
        for c in ("list_tracks", "get_set_identity", "transport", "confirm_authorization"):
            policy.gate(self.a, c, {}, ID_A)

    def test_write_refused_unauthorized(self):
        with self.assertRaises(PolicyError):
            policy.gate(self.a, "set_mixer", {"track": 0}, ID_A)

    def test_fire_clip_that_would_record_is_write(self):
        policy.gate(self.a, "fire_clip", {"track": 0, "slot": 0}, ID_A, fire_would_record=False)
        with self.assertRaises(PolicyError):
            policy.gate(self.a, "fire_clip", {"track": 0, "slot": 0}, ID_A, fire_would_record=True)

    def test_unknown_command_refused_unauthorized(self):
        with self.assertRaises(PolicyError):
            policy.gate(self.a, "brand_new", {}, ID_A)


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
