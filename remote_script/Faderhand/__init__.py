# Faderhand: a control script for Ableton Live 12.4 that serves the Faderhand MCP server.
#
# It runs beside the working AbletonMCP Remote Script (port 9877, untouched) and adds what that one lacks: return
# tracks, sends in verified dB, mixer, routing, audio buses, device chains, parameter snapshots and meters.
# Protocol: the same as AbletonMCP's, one JSON object per request {"type": ..., "params": {...}} and one JSON object
# back {"status": "success", "result": ...} or {"status": "error", "message": ...}. It listens on 127.0.0.1 only
# (AbletonMCP listens on every address), port 9878.
#
# Every Live Object Model call runs on Live's main thread (schedule_message), never on the socket thread.
# Design notes borrowed, with thanks, from elleural/ableton-mcp (MIT, Copyright (c) 2025 Siddharth Ahuja; see THIRD_PARTY_NOTICES.md):
# display_value writes with a str_for_value bisection fallback, routing resolved against the available routing lists,
# meters dBFS = 76 * raw - 70. Each of those is re-verified in Live by tests/ before a tool relies on it.
from __future__ import absolute_import, print_function, unicode_literals

import importlib
import json
import re
import socket
import threading
import time
import traceback

try:
    import Queue as queue
except ImportError:
    import queue

from _Framework.ControlSurface import ControlSurface

from . import policy

PORT = 9878
HOST = "127.0.0.1"
VERSION = "0.6.0"
SCRATCH_MARKER = "__TOOLING_SCRATCH__"   # destructive commands run only in a set that has a track with this name
LETTERS = "ABCDEFGHIJKL"
MAIN_THREAD_TIMEOUT = 20.0


def create_instance(c_instance):
    return Faderhand(c_instance)


class ToolError(Exception):
    pass


class Faderhand(ControlSurface):
    def __init__(self, c_instance):
        ControlSurface.__init__(self, c_instance)
        self._song = self.song()
        self._session = policy.new_set_id()     # this control-surface instance (Live re-creates it on Set load)
        self.running = True
        self.server = None
        self._start_server()
        self.log_message("Faderhand %s listening on %s:%d" % (VERSION, HOST, PORT))
        self.show_message("Faderhand: listening on port %d" % PORT)

    def disconnect(self):
        self.running = False
        try:
            if self.server:
                self.server.close()
        except Exception:
            pass
        ControlSurface.disconnect(self)

    # ------------------------------------------------------------------ socket
    def _start_server(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((HOST, PORT))
        self.server.listen(5)
        self.server.settimeout(1.0)
        t = threading.Thread(target=self._accept_loop)
        t.daemon = True
        t.start()

    def _accept_loop(self):
        while self.running:
            try:
                client, addr = self.server.accept()
            except socket.timeout:
                continue
            except Exception:
                if self.running:
                    time.sleep(0.5)
                continue
            if not str(addr[0]).startswith("127."):   # bound to 127.0.0.1; refuse anything else regardless
                try:
                    client.close()
                except Exception:
                    pass
                continue
            t = threading.Thread(target=self._client_loop, args=(client,))
            t.daemon = True
            t.start()

    def _client_loop(self, client):
        client.settimeout(None)
        buf = ""
        decoder = json.JSONDecoder()
        try:
            while self.running:
                data = client.recv(65536)
                if not data:
                    break
                buf += data.decode("utf-8")
                if len(buf) > policy.MAX_REQUEST_BYTES:
                    client.sendall(json.dumps({"status": "error", "message": "request too large"}).encode("utf-8"))
                    break
                while buf.strip():
                    try:
                        cmd, end = decoder.raw_decode(buf.lstrip())
                    except ValueError:
                        break
                    buf = buf.lstrip()[end:]
                    client.sendall(json.dumps(self._dispatch(cmd), default=str).encode("utf-8"))
        except Exception as e:
            self.log_message("Faderhand client error: %s" % e)
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _dispatch(self, cmd):
        name = cmd.get("type", "")
        params = cmd.get("params", {}) or {}
        handler = getattr(self, "cmd_" + name, None)
        if handler is None:
            # Phase 2 commands live in ext.py, which reload_extensions re-imports without restarting Live.
            fn = getattr(self._ext(), "cmd_" + name, None)
            if fn is not None:
                handler = lambda **kw: fn(self, **kw)
        if handler is None:
            return {"status": "error", "message": "unknown command %r" % name}
        timeout = float(params.pop("_timeout", MAIN_THREAD_TIMEOUT))
        q = queue.Queue()

        def task():
            try:
                # the permission gate runs on Live's main thread, against the Set open at this moment
                policy.gate(name, params, self._identity(create=False), scratch=self._is_scratch(),
                            fire_would_record=(name == "fire_clip" and self._fire_would_record(params)),
                            transport_records=(policy.classify(name) == policy.TRANSPORT and self._recording_armed()))
                q.put({"status": "success", "result": handler(**params)})
            except Exception as e:
                if type(e).__name__ in ("ToolError", "PolicyError"):   # by name: ext.py's ToolError survives a reload
                    q.put({"status": "error", "message": str(e)})
                else:
                    self.log_message(traceback.format_exc())
                    q.put({"status": "error", "message": "%s: %s" % (type(e).__name__, e)})

        try:
            self.schedule_message(0, task)
        except AssertionError:
            task()
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return {"status": "error", "message": "timeout after %.0f s waiting for Live's main thread (%s)" % (timeout, name)}

    # ------------------------------------------------------------------ references
    def _all_tracks(self):
        return list(self._song.tracks) + list(self._song.return_tracks) + [self._song.master_track]

    def _kind(self, track):
        if track == self._song.master_track:
            return "master"
        if track in list(self._song.return_tracks):
            return "return"
        if getattr(track, "is_foldable", False):
            return "group"
        if track.has_midi_input:
            return "midi"
        return "audio"

    def _ref(self, track):
        k = self._kind(track)
        if k == "master":
            return "master"
        if k == "return":
            return "return:" + LETTERS[list(self._song.return_tracks).index(track)]
        return "track:%d" % list(self._song.tracks).index(track)

    @staticmethod
    def _bare(name):
        m = re.match(r"^[A-L]-(.*)$", name)
        return m.group(1) if m else name

    def _track(self, ref):
        """int or 'track:N' -> song.tracks[N]; 'return:A' / 'return:0' -> song.return_tracks; 'master'; else an exact
        (case-insensitive) track or return name, a return's name without its letter included. Ambiguity is an error."""
        tracks, returns = list(self._song.tracks), list(self._song.return_tracks)
        if isinstance(ref, int) and not isinstance(ref, bool):
            if 0 <= ref < len(tracks):
                return tracks[ref]
            raise ToolError("track index %d out of range (0..%d)" % (ref, len(tracks) - 1))
        s = str(ref).strip()
        low = s.lower()
        if low in ("master", "main"):
            return self._song.master_track
        m = re.match(r"^track:(\d+)$", low)
        if m:
            return self._track(int(m.group(1)))
        m = re.match(r"^return:(.+)$", low)
        if m:
            key = m.group(1).strip()
            if re.match(r"^\d+$", key):
                i = int(key)
            elif len(key) == 1 and key.upper() in LETTERS:
                i = LETTERS.index(key.upper())
            else:
                hits = [r for r in returns if r.name.lower() == key or self._bare(r.name).lower() == key]
                if len(hits) != 1:
                    raise ToolError("return %r: %d matches; returns are %s" % (key, len(hits), [r.name for r in returns]))
                return hits[0]
            if 0 <= i < len(returns):
                return returns[i]
            raise ToolError("return %r out of range: the set has %d returns" % (key, len(returns)))
        hits = [t for t in tracks + returns if t.name.lower() == low or self._bare(t.name).lower() == low]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            raise ToolError("no track named %r; tracks are %s" % (s, [t.name for t in tracks + returns]))
        raise ToolError("%r names %d tracks; use track:N or return:X" % (s, len(hits)))

    def _send_index(self, ref):
        returns = list(self._song.return_tracks)
        if isinstance(ref, int) and not isinstance(ref, bool):
            i = ref
        else:
            s = str(ref).strip()
            if len(s) == 1 and s.upper() in LETTERS:
                i = LETTERS.index(s.upper())
            elif re.match(r"^\d+$", s):
                i = int(s)
            else:
                r = self._track(s if s.lower().startswith("return:") else "return:" + s)
                i = returns.index(r)
        if not 0 <= i < len(returns):
            raise ToolError("send %r out of range: the set has %d returns" % (ref, len(returns)))
        return i

    def _device(self, track, device, chain=None):
        """device: index or exact name on the track. chain: a path into racks, 'c' or 'c/d/c/d/c': chain index c of the
        rack, then device index d inside that chain (itself a rack), and so on; returns the device list of the last
        chain. '0' = the rack's first chain; '1/0/2' = chain 1, its device 0 (a nested rack), that rack's chain 2."""
        devices = list(track.devices)
        if chain not in (None, ""):
            parts = [int(p) for p in str(chain).split("/")]
            if len(parts) % 2 == 0:
                raise ToolError("chain path %r must end on a chain index ('c' or 'c/d/c')" % chain)
            rack = self._device(track, device)
            for n in range(0, len(parts), 2):
                if not getattr(rack, "can_have_chains", False):
                    raise ToolError("%s is not a rack" % rack.name)
                chains = list(rack.chains)
                c = parts[n]
                if not 0 <= c < len(chains):
                    raise ToolError("chain %d out of range on %s (%d chains)" % (c, rack.name, len(chains)))
                devices = list(chains[c].devices)
                if n + 1 < len(parts):
                    d = parts[n + 1]
                    if not 0 <= d < len(devices):
                        raise ToolError("device %d out of range in chain %d of %s" % (d, c, rack.name))
                    rack = devices[d]
            return devices
        if isinstance(device, int) and not isinstance(device, bool):
            if 0 <= device < len(devices):
                return devices[device]
            raise ToolError("device index %d out of range on %s (%d devices)" % (device, track.name, len(devices)))
        hits = [d for d in devices if d.name.lower() == str(device).lower()]
        if len(hits) != 1:
            raise ToolError("device %r on %s: %d matches; devices are %s" % (device, track.name, len(hits), [d.name for d in devices]))
        return hits[0]

    def _param(self, device, parameter):
        params = list(device.parameters)
        if isinstance(parameter, int) and not isinstance(parameter, bool):
            if 0 <= parameter < len(params):
                return params[parameter]
            raise ToolError("parameter index %d out of range on %s" % (parameter, device.name))
        key = str(parameter).strip().lower()
        hits = [p for p in params if p.name.lower() == key] or [p for p in params if p.original_name.lower() == key]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ToolError("parameter %r on %s is ambiguous (%d); pass its index" % (parameter, device.name, len(hits)))
        raise ToolError("no parameter %r on %s; parameters are %s" % (parameter, device.name, [p.name for p in params]))

    def _require_scratch(self):
        if not any(t.name == SCRATCH_MARKER for t in self._song.tracks):
            raise ToolError("refused: destructive commands run only in a disposable set with a track named %s" % SCRATCH_MARKER)

    # ------------------------------------------------------------------ values
    @staticmethod
    def _num(text):
        """Number from a display string in display_value's units (Hz, ms): '1.20 kHz' 1200, '2.5 s' 2500, '-inf dB'."""
        if text is None:
            return None
        t = str(text).strip()
        lo = t.lower()
        if "-inf" in lo:
            return float("-inf")
        if lo in ("c", "center"):
            return 0.0
        m = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", t)
        if not m:
            return None
        n = float(m.group(0))
        unit = re.match(r"[a-z%]*", t[m.end():].strip().lower()).group(0)
        if unit == "khz" or unit in ("s", "sec"):
            n *= 1000.0
        elif unit == "l":
            n = -abs(n)
        return n

    def _pout(self, p, index=None):
        out = {"name": p.name, "value": round(float(p.value), 6), "min": p.min, "max": p.max,
               "display": p.str_for_value(p.value), "quantized": bool(p.is_quantized), "enabled": bool(p.is_enabled)}
        try:
            out["display_value"] = float(p.display_value)
        except Exception:
            pass
        if index is not None:
            out["index"] = index
        if p.original_name != p.name:
            out["original_name"] = p.original_name
        if p.is_quantized:
            out["items"] = [str(i) for i in p.value_items]
        try:
            st = int(p.automation_state)
            if st:
                out["automation"] = ["none", "playing", "overridden"][st]
        except Exception:
            pass
        return out

    def _bisect(self, p, target, iterations=50):
        lo, hi = float(p.min), float(p.max)
        dlo, dhi = self._num(p.str_for_value(lo)), self._num(p.str_for_value(hi))
        if dlo is None or dhi is None:
            raise ToolError("%s has no numeric display" % p.name)
        inc = dhi >= dlo
        if target <= min(dlo, dhi):
            return lo if inc else hi
        if target >= max(dlo, dhi):
            return hi if inc else lo
        for _ in range(iterations):
            mid = (lo + hi) / 2.0
            d = self._num(p.str_for_value(mid))
            if d is None:
                break
            if (d < target) == inc:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    def _set_param(self, p, value, units="auto"):
        """units: 'raw' (p.value, clamped check), 'display' (dB, Hz, ms, %, pan -50..50 as Live shows them), 'auto'
        (strings are quantized items or display values, numbers are raw). Returns before, after and the method used."""
        if not p.is_enabled:
            raise ToolError("%s is disabled (macro-mapped or Max-controlled)" % p.name)
        before = self._pout(p)
        method = None
        if isinstance(value, bool):
            p.value = p.max if value else p.min
            method = "bool"
        elif isinstance(value, str) and p.is_quantized:
            items = [str(i).lower() for i in p.value_items]
            if value.strip().lower() not in items:
                raise ToolError("%r is not a value of %s: %s" % (value, p.name, list(p.value_items)))
            p.value = p.min + items.index(value.strip().lower())
            method = "item"
        elif units == "raw" or (units == "auto" and not isinstance(value, str)):
            v = float(value)
            if not p.min - 1e-9 <= v <= p.max + 1e-9:
                raise ToolError("%r outside %s's raw range %g..%g (now %s); pass units='display' for dB/Hz/ms" %
                                (value, p.name, p.min, p.max, p.str_for_value(p.value)))
            p.value = v
            method = "raw"
        else:
            target = self._num(value) if isinstance(value, str) else float(value)
            if target is None:
                raise ToolError("cannot read a number from %r" % value)
            ok = False
            if target != float("-inf"):
                try:
                    p.display_value = target
                    shown = self._num(p.str_for_value(p.value))
                    ok = shown is not None and abs(shown - target) <= max(abs(target) * 0.02, 0.06)
                    method = "display_value"
                except Exception:
                    ok = False
            if not ok:
                p.value = p.min if target == float("-inf") else self._bisect(p, target)
                method = "bisect"
        return {"parameter": p.name, "before": before, "after": self._pout(p), "method": method}

    @staticmethod
    def _db_from_display(text):
        t = str(text).strip().lower()
        if "-inf" in t:
            return None
        m = re.search(r"[-+]?\d+(?:\.\d+)?", t)
        return float(m.group(0)) if m else None

    # ------------------------------------------------------------------ serialisation
    def _routing(self, track):
        k = self._kind(track)
        out = {}
        try:
            out["output"] = {"type": track.output_routing_type.display_name,
                             "channel": track.output_routing_channel.display_name}
        except Exception:
            pass
        if k in ("audio", "midi"):
            try:
                out["input"] = {"type": track.input_routing_type.display_name,
                                "channel": track.input_routing_channel.display_name}
            except Exception:
                pass
            try:
                out["monitoring"] = ["in", "auto", "off"][int(track.current_monitoring_state)]
            except Exception:
                pass
        return out

    def _sends(self, track):
        out = []
        returns = list(self._song.return_tracks)
        for i, s in enumerate(track.mixer_device.sends):
            out.append({"send": LETTERS[i], "return": returns[i].name if i < len(returns) else None,
                        "value": round(float(s.value), 6), "display": s.str_for_value(s.value),
                        "db": self._db_from_display(s.str_for_value(s.value))})
        return out

    def _mixer(self, track):
        md = track.mixer_device
        out = {"volume_db": self._db_from_display(md.volume.str_for_value(md.volume.value)),
               "volume_value": round(float(md.volume.value), 6), "volume_display": md.volume.str_for_value(md.volume.value),
               "pan_display": md.panning.str_for_value(md.panning.value)}
        if self._kind(track) != "master":
            out["mute"] = bool(track.mute)
            out["solo"] = bool(track.solo)
        return out

    def _dev(self, d, index, params=False, depth=0):
        out = {"index": index, "name": d.name, "class_name": d.class_name,
               "type": {0: "undefined", 1: "instrument", 2: "audio_effect", 4: "midi_effect"}.get(int(d.type), str(d.type)),
               "active": bool(d.is_active)}
        try:
            on = d.parameters[0]
            out["on"] = bool(on.value)
        except Exception:
            pass
        if d.class_name in ("PluginDevice", "AuPluginDevice"):
            out["plugin"] = True
        if params:
            out["parameters"] = [self._pout(p, i) for i, p in enumerate(d.parameters)]
        if getattr(d, "can_have_chains", False) and depth < 3:
            out["chains"] = [{"index": ci, "name": c.name,
                              "devices": [self._dev(cd, di, params, depth + 1) for di, cd in enumerate(c.devices)]}
                             for ci, c in enumerate(d.chains)]
        return out

    def _track_out(self, t, devices=True):
        out = {"ref": self._ref(t), "name": t.name, "kind": self._kind(t)}
        out.update(self._mixer(t))
        out["routing"] = self._routing(t)
        if self._kind(t) != "master":
            out["sends"] = self._sends(t)
        if devices:
            out["devices"] = [{"index": i, "name": d.name, "class_name": d.class_name, "on": bool(d.parameters[0].value) if len(d.parameters) else None}
                              for i, d in enumerate(t.devices)]
        return out

    # ------------------------------------------------------------------ commands: info and tracks
    # ------------------------------------------------------------------ write permission (policy.py)
    def _identity(self, create=False):
        doc = self.application().get_document()
        sid = doc.get_data(policy.SET_ID_KEY, None)
        if not sid and create:
            sid = policy.new_set_id()
            doc.set_data(policy.SET_ID_KEY, sid)       # stored inside the Set; travels with the file
        return {"file_path": str(doc.file_path or ""), "name": str(getattr(doc, "name", "") or ""),
                "set_id": str(sid or ""), "doc_key": self._session}

    def _is_scratch(self):
        return any(t.name == SCRATCH_MARKER for t in self.application().get_document().tracks)

    def _fire_would_record(self, params):
        """Launching records when the track is armed (explicitly or by a controller) and the slot is empty, or when
        it's armed while record mode or Session record is on (overdub). Unknown -> True (fail closed)."""
        try:
            t = self._track(params.get("track"))
            cslot = list(t.clip_slots)[int(params.get("slot", 0))]
            armed = bool(getattr(t, "arm", False) or getattr(t, "implicit_arm", False))
            return armed and ((not cslot.has_clip) or self._recording_armed())
        except Exception:
            return True

    def _recording_armed(self):
        """True when starting playback would record: Arrangement record mode or Session record is on. (An armed track
        alone doesn't record on play. A controller arms the selected MIDI track implicitly, which is why arm isn't
        counted here; fire_clip checks arm itself.) Unknown -> True (fail closed)."""
        try:
            doc = self.application().get_document()
            return bool(doc.record_mode) or bool(getattr(doc, "session_record", False))
        except Exception:
            return True

    def cmd_get_set_identity(self):
        """The open Set's identity: file path, name, and a set_id stored inside the Set (created on first call)."""
        return self._identity(create=True)

    def cmd_write_status(self):
        """Whether edits may run on the open Set: any saved Set (untitled Sets are refused); deletes only in a
        disposable Set."""
        cur = self._identity(create=False)
        return {"writes_allowed": bool(cur.get("file_path")), "scratch_set": self._is_scratch(),
                "current_identity": cur,
                "rules": "edits run on any saved Set; untitled Sets are refused (save first); deletes run only in a "
                         "disposable Set (a track named %s)" % policy.SCRATCH_MARKER}

    # ------------------------------------------------------------------ extensions (hot-reloadable)
    def _ext(self):
        mod = getattr(self, "_ext_mod", None)
        if mod is None:
            from . import ext as mod
            self._ext_mod = mod
        return mod

    def cmd_reload_extensions(self):
        """Re-import ext.py (Phase 2 commands) without restarting Live. Core commands in this file still need a
        restart: Live loads Remote Scripts only at startup."""
        mod = importlib.reload(self._ext())
        self._ext_mod = mod
        return {"ext_version": getattr(mod, "EXT_VERSION", None),
                "commands": sorted(n[4:] for n in dir(mod) if n.startswith("cmd_"))}

    def cmd_info(self):
        return {"name": "Faderhand", "version": VERSION, "port": PORT, "live_version": "%d.%d.%d" % (
            self.application().get_major_version(), self.application().get_minor_version(), self.application().get_bugfix_version()),
            "tracks": len(self._song.tracks), "returns": len(self._song.return_tracks),
            "scratch_set": any(t.name == SCRATCH_MARKER for t in self._song.tracks),
            "commands": sorted(n[4:] for n in dir(self) if n.startswith("cmd_")),
            "ext_version": getattr(self._ext(), "EXT_VERSION", None),
            "ext_commands": sorted(n[4:] for n in dir(self._ext()) if n.startswith("cmd_"))}

    def cmd_list_tracks(self, devices=True):
        return [self._track_out(t, devices) for t in self._all_tracks()]

    def cmd_list_return_tracks(self):
        out = []
        for i, r in enumerate(self._song.return_tracks):
            o = self._track_out(r)
            o["letter"] = LETTERS[i]
            o["fed_by"] = [{"track": self._ref(t), "name": t.name, "display": t.mixer_device.sends[i].str_for_value(t.mixer_device.sends[i].value)}
                           for t in list(self._song.tracks) + list(self._song.return_tracks)
                           if i < len(t.mixer_device.sends) and float(t.mixer_device.sends[i].value) > float(t.mixer_device.sends[i].min)]
            out.append(o)
        return out

    def cmd_create_return_track(self, name=None):
        before = len(self._song.return_tracks)
        self._song.create_return_track()
        returns = list(self._song.return_tracks)
        if len(returns) != before + 1:
            raise ToolError("create_return_track: return count %d -> %d" % (before, len(returns)))
        r = returns[-1]
        if name:
            r.name = name
        return self._track_out(r)

    def cmd_create_track(self, kind="audio", index=-1, name=None):
        before = len(self._song.tracks)
        if kind == "audio":
            self._song.create_audio_track(index)
        elif kind == "midi":
            self._song.create_midi_track(index)
        else:
            raise ToolError("kind must be 'audio' or 'midi'")
        tracks = list(self._song.tracks)
        if len(tracks) != before + 1:
            raise ToolError("create_track: track count %d -> %d" % (before, len(tracks)))
        t = tracks[index if index >= 0 else len(tracks) - 1]
        if name:
            t.name = name
        return self._track_out(t)

    def cmd_rename_track(self, track, name):
        t = self._track(track)
        if t == self._song.master_track:
            raise ToolError("the master track cannot be renamed here")
        t.name = name
        return {"ref": self._ref(t), "name": t.name}

    def cmd_delete_track(self, track):
        self._require_scratch()
        t = self._track(track)
        if self._kind(t) == "return":
            i = list(self._song.return_tracks).index(t)
            self._song.delete_return_track(i)
        elif t == self._song.master_track:
            raise ToolError("cannot delete the master")
        else:
            if t.name == SCRATCH_MARKER:
                raise ToolError("refused: that is the scratch marker track")
            self._song.delete_track(list(self._song.tracks).index(t))
        return {"deleted": track}

    # ------------------------------------------------------------------ mixer and sends
    def cmd_get_mixer(self, track):
        t = self._track(track)
        return dict(self._mixer(t), ref=self._ref(t), name=t.name)

    def cmd_set_mixer(self, track, volume_db=None, pan=None, mute=None, solo=None):
        """volume_db: dB as Live shows it ('-inf' or None to leave); pan: -50 (50L) .. 50 (50R)."""
        t = self._track(track)
        md = t.mixer_device
        out = {"ref": self._ref(t)}
        if volume_db is not None:
            out["volume"] = self._set_param(md.volume, volume_db, "display")
        if pan is not None:
            out["pan"] = self._set_param(md.panning, float(pan), "display")
        if mute is not None:
            if t == self._song.master_track:
                raise ToolError("the master has no mute")
            t.mute = bool(mute)
        if solo is not None:
            t.solo = bool(solo)
        out["now"] = self._mixer(t)
        return out

    def cmd_get_track_sends(self, track):
        t = self._track(track)
        return {"ref": self._ref(t), "name": t.name, "sends": self._sends(t)}

    def cmd_set_track_send(self, track, send, db=None, value=None):
        """db: the send in dB as Live displays it (-inf or None = off when value is None too); value: raw 0..1."""
        t = self._track(track)
        i = self._send_index(send)
        sends = list(t.mixer_device.sends)
        if i >= len(sends):
            raise ToolError("%s has %d sends (a return cannot send to itself or earlier returns)" % (t.name, len(sends)))
        p = sends[i]
        if value is not None:
            r = self._set_param(p, float(value), "raw")
        elif db is None or str(db).strip().lower() in ("-inf", "off"):
            p.value = p.min
            r = {"parameter": p.name, "after": self._pout(p), "method": "min"}
        else:
            r = self._set_param(p, float(db), "display")
        r["send"] = LETTERS[i]
        r["return"] = self._song.return_tracks[i].name
        r["db"] = self._db_from_display(p.str_for_value(p.value))
        return r

    def cmd_send_curve(self, track, send, points=21):
        """Raw value -> display table of a send knob (the dB mapping as Live itself computes it)."""
        t = self._track(track)
        p = t.mixer_device.sends[self._send_index(send)]
        n = max(2, int(points))
        return [{"value": round(p.min + (p.max - p.min) * k / (n - 1.0), 4),
                 "display": p.str_for_value(p.min + (p.max - p.min) * k / (n - 1.0))} for k in range(n)]

    # ------------------------------------------------------------------ devices
    def cmd_get_track_devices(self, track, params=False):
        t = self._track(track)
        return {"ref": self._ref(t), "name": t.name, "devices": [self._dev(d, i, params) for i, d in enumerate(t.devices)]}

    def cmd_get_device_parameters(self, track, device, chain=None, chain_device=None):
        t = self._track(track)
        d = self._device(t, device)
        if chain not in (None, ""):
            d = self._device(t, device, chain)[int(chain_device or 0)]
        return {"track": self._ref(t), "device": d.name, "class_name": d.class_name,
                "parameters": [self._pout(p, i) for i, p in enumerate(d.parameters)]}

    def cmd_set_device_parameter(self, track, device, parameter, value, units="auto", chain=None, chain_device=None):
        t = self._track(track)
        d = self._device(t, device)
        if chain not in (None, ""):
            d = self._device(t, device, chain)[int(chain_device or 0)]
        r = self._set_param(self._param(d, parameter), value, units)
        r.update({"track": self._ref(t), "device": d.name})
        return r

    def cmd_set_device_parameters(self, track, device, values, units="auto", chain=None, chain_device=None):
        """values: {parameter name or index: value}. All are validated by name before any is written.
        chain/chain_device reach a device inside a rack, as in set_device_parameter."""
        t = self._track(track)
        d = self._device(t, device)
        if chain not in (None, ""):
            d = self._device(t, device, chain)[int(chain_device or 0)]
        resolved = [(self._param(d, int(k) if re.match(r"^\d+$", str(k)) else k), v) for k, v in values.items()]
        return {"track": self._ref(t), "device": d.name, "results": [self._set_param(p, v, units) for p, v in resolved]}

    def cmd_set_device_on(self, track, device, on=True):
        t = self._track(track)
        d = self._device(t, device)
        p = d.parameters[0]
        if p.original_name not in ("Device On", "On"):
            raise ToolError("%s's first parameter is %r, not Device On" % (d.name, p.original_name))
        p.value = p.max if on else p.min
        return {"track": self._ref(t), "device": d.name, "on": bool(p.value), "active": bool(d.is_active)}

    def cmd_insert_native_device(self, track, name, index=-1):
        """Track.insert_device (Live 12.3+): native Live devices by exact browser name ('Echo', 'Hybrid Reverb')."""
        t = self._track(track)
        before = [d.name for d in t.devices]
        if index is None or int(index) < 0:
            d = t.insert_device(name)
        else:
            d = t.insert_device(name, int(index))
        after = [x.name for x in t.devices]
        if len(after) != len(before) + 1:
            raise ToolError("insert_device(%r): devices %s -> %s" % (name, before, after))
        pos = [i for i, x in enumerate(t.devices) if x == d]
        return {"track": self._ref(t), "inserted": d.name, "class_name": d.class_name, "position": pos[0] if pos else None,
                "devices": after}

    def _browser_find(self, uri, max_depth=8):
        b = self.application().browser
        roots = []
        prefix = uri.split("#")[0].lower() if "#" in uri else ""
        order = [("plugins", "plugins"), ("audiofx", "audio_effects"), ("instruments", "instruments"),
                 ("midifx", "midi_effects"), ("drums", "drums"), ("sounds", "sounds"), ("samples", "samples"),
                 ("packs", "packs"), ("userlibrary", "user_library"), ("maxfor", "max_for_live")]
        for key, attr in order:
            if key in prefix:
                roots.insert(0, attr)
            else:
                roots.append(attr)
        seen = set()
        for attr in roots:
            if attr in seen:
                continue
            seen.add(attr)
            root = getattr(b, attr, None)
            if root is None:
                continue
            stack = [(root, 0)]
            while stack:
                item, depth = stack.pop()
                if getattr(item, "uri", None) == uri:
                    return item
                # Recurse whatever is_folder says: Live's category roots (browser.plugins, ...) report
                # is_folder False although they have children (found 2026-11-10: every plugin URI missed).
                if depth < max_depth:
                    try:
                        stack.extend((c, depth + 1) for c in item.children)
                    except Exception:
                        pass
        return None

    def cmd_load_browser_item(self, track, uri, position=None):
        """Load a browser item (plugin, preset, native device) by URI onto any track, return tracks included (the
        working AbletonMCP can only target song.tracks). Then optionally move it to `position` in the chain.
        Verifies that exactly this track gained exactly one device."""
        t = self._track(track)
        item = self._browser_find(uri)
        if item is None:
            raise ToolError("browser item not found: %s" % uri)
        if not item.is_loadable:
            raise ToolError("browser item is not loadable: %s" % uri)
        snapshot = {self._ref(x): [d.name for d in x.devices] for x in self._all_tracks()}
        self._song.view.selected_track = t
        if len(t.devices):
            self._song.view.select_device(t.devices[-1])
        self.application().browser.load_item(item)
        return {"track": self._ref(t), "uri": uri, "item": item.name, "requested_position": position,
                "before": snapshot, "note": "load_item is asynchronous: call verify_load next tick"}

    def cmd_verify_load(self, track, before, position=None):
        t = self._track(track)
        now = {self._ref(x): [d.name for d in x.devices] for x in self._all_tracks()}
        changed = sorted(k for k in now if now[k] != before.get(k))
        mine = self._ref(t)
        if changed != [mine] or len(now[mine]) != len(before.get(mine, [])) + 1:
            return {"ok": False, "changed": changed, "now": {k: now[k] for k in changed}}
        devices = list(t.devices)
        new = [d for d in devices if d.name not in before[mine]] or [devices[-1]]
        d = new[-1]
        if position is not None and int(position) >= 0:
            self._song.move_device(d, t, int(position))
        return {"ok": True, "track": mine, "loaded": d.name, "class_name": d.class_name,
                "devices": [x.name for x in t.devices]}

    def cmd_move_device(self, track, device, to_position, to_track=None):
        t = self._track(track)
        d = self._device(t, device)
        dest = self._track(to_track) if to_track is not None else t
        self._song.move_device(d, dest, int(to_position))
        return {"track": self._ref(dest), "devices": [x.name for x in dest.devices]}

    def cmd_delete_device(self, track, device):
        self._require_scratch()
        t = self._track(track)
        d = self._device(t, device)
        i = list(t.devices).index(d)
        t.delete_device(i)
        return {"track": self._ref(t), "devices": [x.name for x in t.devices]}

    def cmd_snapshot_device(self, track, device):
        t = self._track(track)
        d = self._device(t, device)
        return {"track": self._ref(t), "device": d.name, "class_name": d.class_name, "taken": time.time(),
                "values": [{"index": i, "name": p.name, "value": float(p.value), "display": p.str_for_value(p.value)}
                           for i, p in enumerate(d.parameters)]}

    def cmd_restore_device_snapshot(self, track, device, snapshot):
        """Writes raw values back by index, only where the parameter name still matches; reports every mismatch."""
        t = self._track(track)
        d = self._device(t, device)
        params = list(d.parameters)
        written, skipped = 0, []
        for e in snapshot["values"]:
            i = int(e["index"])
            if i >= len(params) or params[i].name != e["name"]:
                skipped.append(e["name"])
                continue
            if not params[i].is_enabled:
                skipped.append(e["name"] + " (disabled)")
                continue
            if abs(float(params[i].value) - float(e["value"])) > 1e-9:
                params[i].value = float(e["value"])
                written += 1
        diff = [e["name"] for e in snapshot["values"] if int(e["index"]) < len(params) and params[int(e["index"])].name == e["name"]
                and params[int(e["index"])].is_enabled and abs(float(params[int(e["index"])].value) - float(e["value"])) > 1e-6]
        return {"track": self._ref(t), "device": d.name, "written": written, "skipped": skipped, "still_different": diff}

    # ------------------------------------------------------------------ routing
    def _routing_lists(self, t):
        k = self._kind(t)
        out = {"output_types": [x.display_name for x in t.available_output_routing_types],
               "output_channels": [x.display_name for x in t.available_output_routing_channels]}
        if k in ("audio", "midi"):
            out["input_types"] = [x.display_name for x in t.available_input_routing_types]
            out["input_channels"] = [x.display_name for x in t.available_input_routing_channels]
        return out

    def cmd_get_routing(self, track, options=True):
        t = self._track(track)
        out = {"ref": self._ref(t), "name": t.name, "kind": self._kind(t)}
        out.update(self._routing(t))
        if options:
            out["available"] = self._routing_lists(t)
        return out

    def _pick_routing(self, t, direction, target):
        items = list(getattr(t, "available_%s_routing_types" % direction))
        if not any(x.display_name for x in items):
            raise ToolError("routing lists of %s are not ready (track created this tick): retry" % t.name)
        aliases = {"master": "main", "none": "no output" if direction == "output" else "no input", "off": "no output" if direction == "output" else "no input"}
        if isinstance(target, str):
            key = aliases.get(target.strip().lower(), target.strip().lower())
            exact = [x for x in items if x.display_name.lower() == key]
            if len(exact) == 1:
                return exact[0]
            try:
                dest = self._track(target)
            except ToolError:
                raise ToolError("%s routing %r for %s not offered; choices are %s" % (direction, target, t.name, [x.display_name for x in items]))
        else:
            dest = self._track(target)
        hits = [x for x in items if getattr(x, "attached_object", None) == dest]
        if len(hits) != 1:
            raise ToolError("%s cannot route %s to %s (%d matches); choices are %s" %
                            (t.name, direction, dest.name, len(hits), [x.display_name for x in items]))
        return hits[0]

    def _snapshot_routing(self):
        return {self._ref(x): self._routing(x) for x in self._all_tracks()}

    def cmd_set_routing(self, track, direction, target, channel=None):
        """direction 'output' or 'input'; target is a routing name offered by Live ('Main', 'No Output', 'Ext. In',
        'Sends Only') or a track ref, matched by the routing type's attached track, never by label or index alone."""
        t = self._track(track)
        if direction not in ("output", "input"):
            raise ToolError("direction must be 'output' or 'input'")
        if direction == "input" and self._kind(t) not in ("audio", "midi"):
            raise ToolError("%s has no input routing" % t.name)
        before = self._snapshot_routing()
        rt = self._pick_routing(t, direction, target)
        setattr(t, "%s_routing_type" % direction, rt)
        if channel is not None:
            chans = list(getattr(t, "available_%s_routing_channels" % direction))
            hits = [c for c in chans if c.display_name.lower() == str(channel).lower()]
            if len(hits) != 1:
                raise ToolError("channel %r not offered: %s" % (channel, [c.display_name for c in chans]))
            setattr(t, "%s_routing_channel" % direction, hits[0])
        after = self._snapshot_routing()
        changed = sorted(k for k in after if after[k] != before[k])
        return {"ref": self._ref(t), "now": self._routing(t), "changed_tracks": changed}

    def cmd_set_monitoring(self, track, state):
        t = self._track(track)
        states = {"in": 0, "auto": 1, "off": 2}
        if self._kind(t) not in ("audio", "midi"):
            raise ToolError("%s has no monitoring" % t.name)
        t.current_monitoring_state = states[str(state).lower()]
        return {"ref": self._ref(t), "monitoring": ["in", "auto", "off"][int(t.current_monitoring_state)]}

    def cmd_get_routing_graph(self):
        """Every track's input, output, monitoring, mute/solo/volume and active sends, plus the problems found."""
        nodes = []
        tracks = self._all_tracks()
        for t in tracks:
            n = {"ref": self._ref(t), "name": t.name, "kind": self._kind(t)}
            n.update(self._routing(t))
            n.update(self._mixer(t))
            try:
                dest = t.output_routing_type.attached_object
                n["output_track"] = self._ref(dest) if dest is not None and dest in tracks else None
            except Exception:
                n["output_track"] = None
            if self._kind(t) in ("audio", "midi"):
                try:
                    src = t.input_routing_type.attached_object
                    n["input_track"] = self._ref(src) if src is not None and src in tracks else None
                except Exception:
                    n["input_track"] = None
                n["armed"] = bool(getattr(t, "arm", False)) if getattr(t, "can_be_armed", False) else False
            if self._kind(t) != "master":
                n["active_sends"] = [s["send"] for s, raw in zip(self._sends(t), t.mixer_device.sends) if float(raw.value) > float(raw.min)]
                n["has_audio_out"] = n.get("output", {}).get("type") not in ("No Output", None)
            nodes.append(n)
        return {"nodes": nodes, "problems": self._problems(nodes)}

    def _problems(self, nodes):
        by = {n["ref"]: n for n in nodes}
        out = []
        # edges: output routing to a track, input routing from a track, active sends to returns
        edges = {}
        for n in nodes:
            e = set()
            if n.get("output_track"):
                e.add(n["output_track"])
            for s in n.get("active_sends", []):
                e.add("return:" + s)
            edges[n["ref"]] = e
        for n in nodes:
            if n.get("input_track") and n.get("monitoring") != "off":
                edges.setdefault(n["input_track"], set()).add(n["ref"])
        # cycles (feedback loops)
        colour = {}

        def visit(v, path):
            colour[v] = 1
            for w in edges.get(v, ()):
                if colour.get(w) == 1:
                    out.append({"severity": "error", "problem": "feedback loop", "path": path[path.index(w):] + [w] if w in path else path + [w]})
                elif not colour.get(w):
                    visit(w, path + [w])
            colour[v] = 2
        for v in list(edges):
            if not colour.get(v):
                visit(v, [v])
        feeders = {}
        for n in nodes:
            if n.get("output_track"):
                feeders.setdefault(n["output_track"], []).append(n["ref"])
        for n in nodes:
            # double routing: a track heard on Main directly and again through a bus that takes it as its input
            if n.get("input_track") and n.get("monitoring") in ("in", "auto"):
                src = by.get(n["input_track"])
                if src and src.get("output", {}).get("type") == "Main" and n.get("output", {}).get("type") == "Main":
                    out.append({"severity": "warning", "problem": "double routing to Main", "tracks": [src["ref"], n["ref"]]})
            if n["ref"] in feeders:
                if n.get("monitoring") == "off":
                    out.append({"severity": "error", "problem": "silent bus: monitoring Off", "bus": n["ref"], "sources": feeders[n["ref"]]})
                if n.get("output", {}).get("type") == "No Output":
                    out.append({"severity": "error", "problem": "silent bus: No Output", "bus": n["ref"]})
                if n.get("mute"):
                    out.append({"severity": "warning", "problem": "bus muted", "bus": n["ref"]})
                if n.get("volume_db") is None:
                    out.append({"severity": "warning", "problem": "bus fader at -inf", "bus": n["ref"]})
                if n.get("solo") and not any(by[s].get("solo") for s in feeders[n["ref"]]):
                    out.append({"severity": "info", "problem": "bus soloed: check that its sources stay audible", "bus": n["ref"]})
            if n["kind"] == "return" and n.get("output", {}).get("type") == "No Output":
                out.append({"severity": "warning", "problem": "return has No Output", "track": n["ref"]})
        return out

    # ------------------------------------------------------------------ meters and transport
    def cmd_get_meters(self, tracks=None):
        """Output meters. dbfs = 76 * raw - 70 (elleural's calibration on Live 12.4.6; re-verified by
        tests/calibrate_meters.py before any tool treats it as fact). raw 0 means -70 dBFS or lower."""
        ts = [self._track(r) for r in tracks] if tracks else self._all_tracks()
        out = {}
        for t in ts:
            try:
                lvl = float(t.output_meter_level)
                out[self._ref(t)] = {"level": round(lvl, 5), "left": round(float(t.output_meter_left), 5),
                                     "right": round(float(t.output_meter_right), 5),
                                     "dbfs": round(76.0 * lvl - 70.0, 2) if lvl > 0 else None}
            except Exception as e:
                out[self._ref(t)] = {"error": str(e)}
        return {"playing": bool(self._song.is_playing), "time": float(self._song.current_song_time), "meters": out}

    def cmd_transport(self, action, time_beats=None):
        if action == "play":
            if time_beats is not None:
                self._song.current_song_time = float(time_beats)
            self._song.start_playing()
        elif action == "continue":
            self._song.continue_playing()
        elif action == "stop":
            self._song.stop_playing()
        elif action == "stop_all_clips":
            self._song.stop_all_clips()
        else:
            raise ToolError("action: play, continue, stop, stop_all_clips")
        return {"playing": bool(self._song.is_playing), "tempo": float(self._song.tempo)}

    def cmd_make_test_clip(self, track, slot=0, length=4.0, notes=None, name=None, fire=False):
        """A session MIDI clip of test notes [[pitch, start_beats, length_beats, velocity], ...] on a MIDI track."""
        t = self._track(track)
        if not t.has_midi_input:
            raise ToolError("%s is not a MIDI track" % t.name)
        cs = t.clip_slots[int(slot)]
        if cs.has_clip:
            raise ToolError("slot %d of %s already holds a clip" % (slot, t.name))
        cs.create_clip(float(length))
        clip = cs.clip
        if name:
            clip.name = name
        notes = notes or [[60, 0.0, float(length), 100]]
        try:
            import Live
            specs = [Live.Clip.MidiNoteSpecification(pitch=int(p), start_time=float(s), duration=float(d), velocity=float(v), mute=False)
                     for p, s, d, v in notes]
            clip.add_new_notes(tuple(specs))
        except Exception:
            clip.set_notes(tuple((int(p), float(s), float(d), int(v), False) for p, s, d, v in notes))
        clip.looping = True
        if fire:
            cs.fire()
        return {"track": self._ref(t), "slot": int(slot), "notes": len(notes)}

    def cmd_fire_clip(self, track, slot=0):
        t = self._track(track)
        t.clip_slots[int(slot)].fire()
        return {"track": self._ref(t), "slot": int(slot)}
