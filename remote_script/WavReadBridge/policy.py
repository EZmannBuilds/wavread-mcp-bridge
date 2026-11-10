# Write-permission policy for the control script. Pure Python, no Live imports, so it is tested offline
# (tests/offline/test_policy.py).
#
# Model (fail closed), 0.5.0:
# - Every command has one class. READ, META and TRANSPORT run freely. A command missing from the table is WRITE.
# - WRITE runs on any saved Set. An untitled Set is refused ("save first"), so every edit lands in a file the user
#   can find, back up and reopen.
# - Deletion commands also need a disposable Set: one whose tracks include the scratch marker.
# - Transport that would record (record mode or Session record on, or launching an empty slot on an armed track)
#   changes the Set, so it counts as WRITE. Stopping is always allowed.
# The approval codes of 0.3.0-0.4.0 are gone (the owner, 2026-11-10: "Will other people have to run the code? If so just
# remove it"). What protects the user now: loopback-only connections (the control script), the rules above, and
# backups of important Sets.
from __future__ import absolute_import, print_function, unicode_literals

import os
import re
import uuid

READ, WRITE, META, TRANSPORT = "read", "write", "meta", "transport"
SET_ID_KEY = "wavread.set_id"
SCRATCH_MARKER = "__TOOLING_SCRATCH__"
MAX_REQUEST_BYTES = 1000000
AUDIO_EXT = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a")

CLASSES = {
    # meta: identity and permission status, connection info, reloading command code (doesn't touch the Set)
    "info": META, "get_set_identity": META, "write_status": META, "reload_extensions": META,
    # read: inspection only
    "list_tracks": READ, "list_return_tracks": READ, "get_mixer": READ, "get_track_sends": READ, "send_curve": READ,
    "get_track_devices": READ, "get_device_parameters": READ, "snapshot_device": READ, "get_routing": READ,
    "get_routing_graph": READ, "get_meters": READ, "verify_load": READ, "probe": READ,
    "list_automatable_parameters": READ, "get_automation": READ, "validate_automation": READ, "param_state": READ,
    "inspect_device_sidechain": READ, "get_clip": READ, "list_arrangement_clips": READ,
    "record_arrangement_status": READ, "record_track_audio_status": READ, "capture_start": READ,
    "capture_result": READ, "show_clip": READ, "show_devices": READ, "show_view": READ,   # view only: what's on screen
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


def classify(name):
    """The command's class; anything unknown is WRITE (fail closed)."""
    return CLASSES.get(name, WRITE)


def new_set_id():
    return uuid.uuid4().hex


def check_write(name, current, scratch=False):
    """Raise PolicyError unless a WRITE command may run on the open Set: it must be saved, and a delete needs a
    disposable Set."""
    if not current.get("file_path"):
        raise PolicyError("refused: %s changes the Set, and this Set is untitled. Save the Set first" % name)
    if name in DELETES and not scratch:
        raise PolicyError("refused: %s deletes material; it runs only in a disposable Set (one with a track named %s)"
                          % (name, SCRATCH_MARKER))


def gate(name, params, current, scratch=False, fire_would_record=False, transport_records=False):
    """Decide one request: returns its class, or raises PolicyError. Transport that would record (record mode or
    session record on, or an armed track) changes the Set, so it counts as a WRITE (fail closed)."""
    cls = classify(name)
    stopping = name == "transport" and isinstance(params, dict) and params.get("action") in ("stop", "stop_all_clips")
    # Stopping never records, so it's always allowed, even with record on.
    if cls == TRANSPORT and not stopping and (transport_records or (name == "fire_clip" and fire_would_record)):
        cls = WRITE
    if cls == WRITE:
        check_write(name, current, scratch)
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
