# Write-permission policy for the control script. Pure Python, no Live imports, so it is tested offline
# (tests/offline/test_policy.py).
#
# Model (fail closed):
# - Every command has one class. READ, META and TRANSPORT run freely. WRITE needs an authorization bound to the open
#   Set. A command missing from the table is WRITE.
# - A Set's identity is (file_path, set_id, doc_key):
#   - file_path is Song.file_path ("" while unsaved);
#   - set_id is a random id the script stores inside the Set with Song.set_data (it travels with the file and survives
#     a reopen);
#   - doc_key identifies the live document object for this session.
# - authorize(...) must be given the exact file_path and set_id that identity() reported, so authorizing is always a
#   deliberate act on a known Set; it never "inherits" from a previous Set.
# - Before every WRITE the current identity is compared with the authorized one. Any difference (another Set opened,
#   Save As to a new path, a reloaded Set object) revokes the authorization and refuses the command.
# - Deletion commands additionally require a disposable Set: one whose tracks include the scratch marker. That's a
#   second guard on top of authorization, never the only one.
from __future__ import absolute_import, print_function, unicode_literals

import json
import os
import re
import secrets
import uuid

READ, WRITE, META, TRANSPORT = "read", "write", "meta", "transport"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I: read off a screen by a person
CODE_LENGTH = 6
CODE_TTL_S = 120.0
CODE_REQUESTS_PER_MIN = 3     # rate limit on authorize_set (a fresh code may be requested if the status bar was overwritten)
WRITE_IDLE_S = 1800.0         # PROPOSED: an authorization with no write for 30 minutes is revoked
SET_ID_KEY = "wavread.set_id"
SCRATCH_MARKER = "__TOOLING_SCRATCH__"
MAX_REQUEST_BYTES = 1000000
AUDIO_EXT = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a")

CLASSES = {
    # meta: permission and identity tools, connection info, reloading command code (doesn't touch the Set)
    "info": META, "get_set_identity": META, "write_status": META, "authorize_set": META, "revoke_authorization": META,
    "confirm_authorization": META, "set_approval_mode": META,
    "reload_extensions": META,
    # read: inspection only
    "list_tracks": READ, "list_return_tracks": READ, "get_mixer": READ, "get_track_sends": READ, "send_curve": READ,
    "get_track_devices": READ, "get_device_parameters": READ, "snapshot_device": READ, "get_routing": READ,
    "get_routing_graph": READ, "get_meters": READ, "verify_load": READ, "probe": READ,
    "list_automatable_parameters": READ, "get_automation": READ, "validate_automation": READ, "param_state": READ,
    "inspect_device_sidechain": READ, "get_clip": READ, "list_arrangement_clips": READ,
    "record_arrangement_status": READ, "record_track_audio_status": READ, "capture_start": READ,
    "capture_result": READ,
    # transport: playback control that doesn't edit the Set (fire_clip is checked separately: launching an empty slot
    # on an armed track would record, so that case is WRITE)
    "transport": TRANSPORT, "fire_clip": TRANSPORT, "back_to_arrangement": TRANSPORT,
    # write: everything that changes the Set
    "create_track": WRITE, "rename_track": WRITE, "delete_track": WRITE, "create_return_track": WRITE,
    "set_mixer": WRITE, "set_track_send": WRITE, "set_routing": WRITE, "set_monitoring": WRITE,
    "insert_native_device": WRITE, "load_browser_item": WRITE, "move_device": WRITE, "delete_device": WRITE,
    "set_device_parameter": WRITE, "set_device_parameters": WRITE, "set_device_on": WRITE,
    "restore_device_snapshot": WRITE, "make_test_clip": WRITE,
    "set_automation_points": WRITE, "set_automation_curve": WRITE, "copy_automation": WRITE,
    "delete_automation": WRITE, "record_arrangement_automation": WRITE, "re_enable_automation": WRITE,
    "set_sidechain": WRITE, "create_effect_rack": WRITE, "add_rack_chain": WRITE, "insert_device_in_chain": WRITE,
    "set_chain_mixer": WRITE, "set_rack_macros": WRITE, "set_clip": WRITE, "warp_marker": WRITE,
    "create_audio_clip": WRITE, "duplicate_to_arrangement": WRITE, "delete_arrangement_clip": WRITE,
    "copy_arrangement_clip": WRITE, "move_arrangement_clip": WRITE, "trim_arrangement_clip": WRITE,
    "split_arrangement_clip": WRITE, "create_arrangement_midi_clip": WRITE, "record_track_audio": WRITE,
    "set_arm": WRITE, "set_song_time": WRITE,
}
DELETES = {"delete_track", "delete_device", "delete_arrangement_clip"}


class PolicyError(Exception):
    pass


# ------------------------------------------------------------------------------------------------ approval setting
APPROVAL_CODE, APPROVAL_OFF = "code", "off"
SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".wavread-bridge", "settings.json")


class Settings(object):
    """The user's approval mode, kept in a small JSON file outside Live so it survives restarts.
    "code" (default): every Set needs a one-time code before edits. "off": no codes. Untitled Sets are still refused
    and deletes still need a disposable Set. Turning approval off is allowed only while a Set is authorized (so it
    costs exactly one code read); turning it back on is always allowed. Limit: anything that can edit the user's
    files could edit this one too."""

    def __init__(self, path=SETTINGS_PATH):
        self.path = path

    def load(self):
        try:
            with open(self.path) as f:
                d = json.load(f)
            mode = d.get("approval")
            return mode if mode in (APPROVAL_CODE, APPROVAL_OFF) else APPROVAL_CODE
        except Exception:
            return APPROVAL_CODE                # missing or unreadable: fail closed

    def save(self, mode):
        if mode not in (APPROVAL_CODE, APPROVAL_OFF):
            raise PolicyError("approval mode is 'code' or 'off'")
        d = os.path.dirname(self.path)
        if not os.path.isdir(d):
            os.makedirs(d)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"approval": mode}, f)
        os.replace(tmp, self.path)
        return mode


def change_approval_mode(auth, settings, current, mode):
    """Turning codes off needs the open Set to be authorized now (one code read); turning them on never does."""
    if mode == APPROVAL_OFF:
        if not (auth.granted is not None and same_identity(auth.granted, current)):
            raise PolicyError("refused: turning approval codes off needs one approval first. Call authorize_set, "
                              "have the user read the code from Live's status bar, confirm_authorization, then "
                              "set_approval_mode('off')")
    elif mode != APPROVAL_CODE:
        raise PolicyError("approval mode is 'code' or 'off'")
    return {"approval": settings.save(mode)}


def classify(name):
    """The command's class; anything unknown is WRITE (fail closed)."""
    return CLASSES.get(name, WRITE)


def new_set_id():
    return uuid.uuid4().hex


def same_identity(a, b):
    return bool(a) and bool(b) and a.get("file_path") == b.get("file_path") and a.get("set_id") == b.get("set_id") \
        and a.get("doc_key") == b.get("doc_key") and bool(a.get("set_id"))


class Authorization(object):
    """In-memory, per control-surface instance: a new Set (which re-creates the control surface) starts with none.

    Granting needs a person (0.4.0). request() creates a one-time code that the control script shows ONLY in Live's
    status bar. It is never returned to the caller, logged, or stored where the LOM can read it. confirm() with that
    code grants. A wrong or expired code, or a second attempt, clears the pending request.
    What it is: out-of-band confirmation for assistants without screen access. It is NOT a guaranteed human-only
    approval: an assistant that can see the screen (screen capture or computer use) could read the code. Requests
    are rate-limited (CODE_REQUESTS_PER_MIN); a code is tied to the exact Set and control-script session, replaced
    by a newer request, used up by any confirm attempt (a replay is refused), and dead after a Set switch, Save As,
    reload or revoke. An authorization idle for WRITE_IDLE_S is revoked.
    """

    def __init__(self):
        self.granted = None          # the identity authorized, or None
        self.token = None
        self.last_revoked = None     # why the previous authorization ended
        self._pending = None         # {"identity", "code", "expires"}: never returned, never logged
        self._requests = []          # times of recent authorize_set calls (rate limit)
        self._last_write = None      # time of the last authorized write (inactivity timeout)

    def status(self, current):
        ok = self.granted is not None and same_identity(self.granted, current)
        return {"authorized": ok, "authorized_identity": self.granted, "current_identity": current,
                "last_revoked": self.last_revoked, "approval_pending": self._pending is not None}

    @staticmethod
    def _check_target(current, file_path, set_id):
        if not current.get("file_path"):
            raise PolicyError("refused: this Set is untitled. Save the Set first, then authorize it")
        if not current.get("set_id"):
            raise PolicyError("the open Set has no set_id yet: call get_set_identity first")
        if file_path != current.get("file_path") or set_id != current.get("set_id"):
            raise PolicyError("refused: file_path/set_id don't match the open Set (%r, %r). Call get_set_identity and "
                              "pass exactly what it reports" % (current.get("file_path"), current.get("set_id")))

    def request(self, current, file_path, set_id, now):
        """Start an approval. Returns (reply_for_the_caller, code_for_the_status_bar_only). A new request replaces
        any pending one, so an older code stops working."""
        self._check_target(current, file_path, set_id)
        now = float(now)
        self._requests = [t for t in self._requests if now - t < 60.0]
        if len(self._requests) >= CODE_REQUESTS_PER_MIN:
            raise PolicyError("refused: too many approval requests; wait a minute before asking for a new code")
        self._requests.append(now)
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        self._pending = {"identity": dict(current), "code": code, "expires": float(now) + CODE_TTL_S}
        reply = {"authorized": False, "approval_pending": True, "expires_in_s": CODE_TTL_S,
                 "message": "A %d-character approval code is shown in Live's status bar for %d s. Ask the user to "
                            "read it to you, then call confirm_authorization with it. One attempt." %
                            (CODE_LENGTH, int(CODE_TTL_S))}
        return reply, code

    def confirm(self, current, code, now):
        p, self._pending = self._pending, None          # one attempt: whatever happens, the request is used up
        if p is None:
            raise PolicyError("refused: no approval is pending. Call authorize_set first")
        if float(now) > p["expires"]:
            raise PolicyError("refused: the approval code expired. Call authorize_set again")
        if not same_identity(p["identity"], current):
            raise PolicyError("refused: the open Set changed since the approval was requested")
        if not isinstance(code, str) or not secrets.compare_digest(code.strip().upper(), p["code"]):
            raise PolicyError("refused: wrong approval code; the request is cleared. Call authorize_set again")
        self.granted = dict(current)
        self.token = uuid.uuid4().hex
        self.last_revoked = None
        self._last_write = float(now)
        return {"authorized": True, "identity": self.granted,
                "next_step": "Ask the user once: 'Turn off approval codes from now on? You won't be asked for a code "
                             "again (you can turn them back on any time).' If yes, call set_approval_mode('off') now, "
                             "while this Set is authorized."}

    def pending_is(self, code, now):
        """True while `code` is the live, unexpired pending code (used by the status-bar refresher; the code never
        leaves the control script)."""
        p = self._pending
        return p is not None and p["code"] == code and float(now) <= p["expires"]

    def authorize(self, current, file_path, set_id):
        """Direct grant without a person: kept only for offline tests of the identity logic. The control script
        never calls it (authorize_set goes through request/confirm)."""
        self._check_target(current, file_path, set_id)
        self.granted = dict(current)
        self.token = uuid.uuid4().hex
        self.last_revoked = None
        return {"authorized": True, "identity": self.granted, "token": self.token}

    def revoke(self, why="revoked"):
        if self.granted is not None:
            self.last_revoked = why
        self.granted = None
        self.token = None
        self._pending = None

    def check_write(self, name, current, scratch=False, now=None, approval=APPROVAL_CODE):
        """Raise PolicyError unless a WRITE command may run on the current Set. With `now`, an authorization idle for
        WRITE_IDLE_S is revoked first. With approval "off" (the user's setting), no authorization is needed; untitled
        Sets and deletes outside a disposable Set are still refused."""
        if approval == APPROVAL_OFF:
            if not current.get("file_path"):
                raise PolicyError("refused: %s changes the Set, and this Set is untitled. Save the Set first" % name)
            if name in DELETES and not scratch:
                raise PolicyError("refused: %s deletes material; it runs only in a disposable Set (one with a track "
                                  "named %s)" % (name, SCRATCH_MARKER))
            return
        if now is not None and self.granted is not None and self._last_write is not None \
                and float(now) - self._last_write > WRITE_IDLE_S:
            self.revoke("no edits for %d minutes" % int(WRITE_IDLE_S / 60))
        if not current.get("file_path"):
            if self.granted is not None:
                self.revoke("an untitled Set is open")
            raise PolicyError("refused: %s changes the Set, and this Set is untitled. Save the Set first" % name)
        if self.granted is None:
            raise PolicyError("refused: %s changes the Set, and this Set isn't authorized for writing. Call "
                              "authorize_set, then confirm_authorization with the code the user reads from Live's "
                              "status bar%s" %
                              (name, (" (last authorization ended: %s)" % self.last_revoked) if self.last_revoked else ""))
        if not same_identity(self.granted, current):
            self.revoke("the open Set changed (authorized %r, now %r)" % (self.granted.get("file_path"),
                                                                       current.get("file_path")))
            raise PolicyError("refused: the open Set is not the one authorized; authorization revoked. "
                              "Authorize this Set explicitly if you mean to edit it")
        if name in DELETES and not scratch:
            raise PolicyError("refused: %s deletes material; it runs only in a disposable Set (one with a track "
                              "named %s) that is also authorized" % (name, SCRATCH_MARKER))
        if now is not None:
            self._last_write = float(now)


def gate(auth, name, params, current, scratch=False, fire_would_record=False, transport_records=False, now=None,
         approval=APPROVAL_CODE):
    """Decide one request: returns its class, or raises PolicyError. Transport that would record (record mode or
    session record on, or an armed track) changes the Set, so it counts as a WRITE (fail closed)."""
    cls = classify(name)
    stopping = name == "transport" and isinstance(params, dict) and params.get("action") in ("stop", "stop_all_clips")
    # Stopping never records, so it's always allowed, even with record on (found in Live: the bridge must be able
    # to stop a recording it isn't authorized to start).
    if cls == TRANSPORT and not stopping and (transport_records or (name == "fire_clip" and fire_would_record)):
        cls = WRITE
    if cls == WRITE:
        auth.check_write(name, current, scratch, now, approval)
    validate_params(name, params)
    return cls


# ------------------------------------------------------------------------------------------------ input validation
_SAFE_SCALAR = (str, int, float, bool, type(None))


def _check_value(v, depth=0):
    if depth > 8:
        raise PolicyError("parameters nest too deeply")
    if isinstance(v, _SAFE_SCALAR):
        if isinstance(v, str) and (len(v) > 4096 or "\x00" in v):
            raise PolicyError("a string parameter is too long or contains NUL")
        return
    if isinstance(v, (list, tuple)):
        if len(v) > 20000:
            raise PolicyError("a list parameter is too long")
        for x in v:
            _check_value(x, depth + 1)
        return
    if isinstance(v, dict):
        if len(v) > 2000:
            raise PolicyError("an object parameter is too large")
        for k, x in v.items():
            if not isinstance(k, str):
                raise PolicyError("object keys must be strings")
            _check_value(x, depth + 1)
        return
    raise PolicyError("unsupported parameter type %s" % type(v).__name__)


def validate_path(path, exts):
    if not isinstance(path, str) or not path:
        raise PolicyError("path must be a non-empty string")
    if "\x00" in path or not os.path.isabs(path):
        raise PolicyError("path must be absolute")
    if ".." in path.split(os.sep):
        raise PolicyError("path must not contain '..'")
    norm = os.path.normpath(path)
    if not norm.lower().endswith(exts):
        raise PolicyError("unsupported file type: %s" % os.path.basename(norm))
    if not os.path.isfile(norm):
        raise PolicyError("no such file: %s" % norm)
    return norm


def validate_params(name, params):
    if not isinstance(params, dict):
        raise PolicyError("params must be an object")
    if not re.match(r"^[a-z_][a-z0-9_]{0,63}$", name or ""):
        raise PolicyError("invalid command name")
    _check_value(params)
    if name == "create_audio_clip":
        validate_path(params.get("path"), AUDIO_EXT)
