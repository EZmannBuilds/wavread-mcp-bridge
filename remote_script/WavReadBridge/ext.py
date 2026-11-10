# WavReadBridge extensions (Phase 2): commands that can be re-imported with `reload_extensions`, no Live restart.
# Each command is a function cmd_<name>(cs, **params), where cs is the running WavReadBridge control surface:
# cs._song, cs._track(ref), cs._ref(track), cs._device(track, device, chain), cs._param(device, name),
# cs._set_param(param, value, units), cs._pout(param), cs._require_scratch(), cs.application().
# Runs on Live's main thread (the core's dispatcher schedules it). Raise ToolError for a clear, expected failure.
from __future__ import absolute_import, print_function, unicode_literals

EXT_VERSION = "0.2.0"


class ToolError(Exception):
    pass


# ---------------------------------------------------------------------------------------------- capability probe
def _resolve(cs, path):
    """'song', 'song.view', 'app', 'browser', 'track:N' / 'return:A' / 'master' / a name, then '/'-separated steps:
    'slot:S' (clip slot), 'clip:S' (session clip), 'aclip:I' (arrangement clip I), 'device:D', 'chain:C',
    'param:P' (index or name), 'mixer', 'envelope:P' (session clip envelope for device param P, via clip)."""
    parts = [p for p in str(path).split("/") if p]
    head = parts.pop(0) if parts else "song"
    if head == "song":
        obj = cs._song
    elif head == "song.view":
        obj = cs._song.view
    elif head == "app":
        obj = cs.application()
    elif head == "browser":
        obj = cs.application().browser
    else:
        obj = cs._track(head)
    for step in parts:
        key, _, arg = step.partition(":")
        if key == "slot":
            obj = list(obj.clip_slots)[int(arg)]
        elif key == "clip":
            obj = list(obj.clip_slots)[int(arg)].clip
            if obj is None:
                raise ToolError("no clip in slot %s" % arg)
        elif key == "aclip":
            obj = list(obj.arrangement_clips)[int(arg)]
        elif key == "device":
            ds = list(obj.devices)
            obj = ds[int(arg)] if arg.isdigit() else [d for d in ds if d.name == arg][0]
        elif key == "chain":
            obj = list(obj.chains)[int(arg)]
        elif key == "param":
            ps = list(obj.parameters)
            obj = ps[int(arg)] if arg.isdigit() else [p for p in ps if p.name == arg][0]
        elif key == "mixer":
            obj = obj.mixer_device
        elif key == "attr":
            obj = getattr(obj, arg)
        else:
            raise ToolError("unknown path step %r" % step)
    return obj


def cmd_probe(cs, path="song", values=True):
    """Read-only capability detection: list the public attributes Live exposes on one LOM object, with simple
    values. Used to decide what this Live version supports before a command relies on it."""
    obj = _resolve(cs, path)
    out = {}
    for name in dir(obj):
        if name.startswith("_") or name.endswith("_has_listener") or name.startswith("add_") and name.endswith(
                "_listener") or name.startswith("remove_") and name.endswith("_listener"):
            continue
        try:
            v = getattr(obj, name)
        except Exception as e:
            out[name] = "<error %s>" % type(e).__name__
            continue
        if callable(v):
            doc = (getattr(v, "__doc__", "") or "").strip().split("\n")[0][:160]
            out[name] = "method: " + doc
        elif not values:
            out[name] = type(v).__name__
        elif isinstance(v, (bool, int, float)) or v is None:
            out[name] = v
        elif isinstance(v, str):
            out[name] = v[:120]
        else:
            out[name] = "<%s>" % type(v).__name__
    return {"path": path, "type": type(obj).__name__, "attributes": out}


# ---------------------------------------------------------------------------------------------- musical time
def _beats_per_bar(cs):
    return cs._song.signature_numerator * 4.0 / cs._song.signature_denominator


def _beats(cs, pos):
    """A position in beats (quarter notes, clip-local). Numbers are beats. Strings are 'bar.beat.sixteenth', 1-based
    ('1.1.1' = 0, '7.1.1' = start of bar 7), or 'Nb' for N beats. Computed from integers, so no drift."""
    if isinstance(pos, (int, float)) and not isinstance(pos, bool):
        return float(pos)
    s = str(pos).strip()
    if s.endswith("b"):
        return float(s[:-1])
    parts = [float(x) for x in s.split(".")]
    while len(parts) < 3:
        parts.append(1.0)
    bar, beat, six = parts[:3]
    if bar < 1 or beat < 1 or six < 1:
        raise ToolError("positions are 1-based bar.beat.sixteenth: %r" % pos)
    beat_len = 4.0 / cs._song.signature_denominator
    return (bar - 1) * _beats_per_bar(cs) + (beat - 1) * beat_len + (six - 1) * 0.25


# ---------------------------------------------------------------------------------------------- automation targets
def _target_param(cs, track, target):
    """target: {"mixer": "volume"|"pan"|"send"|"activator", "send": "A"} or
    {"device": ref, "chain": "c/d/c", "chain_device": n, "parameter": name or index}."""
    t = cs._track(track)
    if not isinstance(target, dict):
        raise ToolError("target must be an object, e.g. {'mixer': 'volume'} or {'device': 0, 'parameter': 'Freq'}")
    if "mixer" in target:
        m = t.mixer_device
        k = target["mixer"]
        if k == "volume":
            return t, m.volume
        if k == "pan":
            return t, m.panning
        if k == "activator":
            return t, m.track_activator
        if k == "send":
            return t, list(m.sends)[cs._send_index(target.get("send"))]
        raise ToolError("mixer target is volume, pan, send or activator, not %r" % k)
    d = cs._device(t, target.get("device", 0))
    if target.get("chain") not in (None, ""):
        d = cs._device(t, target.get("device", 0), target["chain"])[int(target.get("chain_device") or 0)]
    return t, cs._param(d, target["parameter"])


def _to_raw(cs, p, value, units):
    if units == "raw" or (units == "auto" and not isinstance(value, str)):
        v = float(value)
        if not p.min - 1e-9 <= v <= p.max + 1e-9:
            raise ToolError("%r outside %s's raw range %g..%g" % (value, p.name, p.min, p.max))
        return v
    if isinstance(value, str) and p.is_quantized:
        items = [str(i).lower() for i in p.value_items]
        if value.strip().lower() not in items:
            raise ToolError("%r is not a value of %s: %s" % (value, p.name, list(p.value_items)))
        return float(p.min + items.index(value.strip().lower()))
    target = cs._num(value) if isinstance(value, str) else float(value)
    if target is None:
        raise ToolError("cannot read a number from %r" % value)
    if target == float("-inf"):
        return float(p.min)
    return float(cs._bisect(p, target))


def _clip(cs, track, slot):
    t = cs._track(track)
    slots = list(t.clip_slots)
    if not 0 <= int(slot) < len(slots) or slots[int(slot)].clip is None:
        raise ToolError("no session clip in %s slot %s" % (cs._ref(t), slot))
    return t, slots[int(slot)].clip


def _envelope(cs, track, slot, target, create=False):
    t, clip = _clip(cs, track, slot)
    pt, p = _target_param(cs, track, target)
    env = clip.automation_envelope(p)
    if env is None and create:
        env = clip.create_automation_envelope(p)
    return t, clip, p, env


def _read(p, env, beat):
    v = env.value_at_time(beat + 1e-4)   # on a breakpoint border value_at_time returns the value before it
    return {"beat": round(beat, 6), "raw": round(float(v), 6), "display": p.str_for_value(v)}


# ---------------------------------------------------------------------------------------------- automation commands
def cmd_list_automatable_parameters(cs, track, slot=None):
    """Every parameter a session clip on this track can automate: mixer (volume, pan, sends) and each device's
    parameters, racks included (with the chain path to reach them). With slot, marks which have an envelope."""
    t = cs._track(track)
    clip = _clip(cs, track, slot)[1] if slot is not None else None
    out = []

    def add(p, target):
        row = {"target": target, "name": p.name, "min": p.min, "max": p.max, "display": p.str_for_value(p.value),
               "quantized": bool(p.is_quantized), "enabled": bool(p.is_enabled)}
        if clip is not None:
            row["has_envelope"] = clip.automation_envelope(p) is not None
        out.append(row)

    m = t.mixer_device
    add(m.volume, {"mixer": "volume"})
    add(m.panning, {"mixer": "pan"})
    for i, s in enumerate(m.sends):
        add(s, {"mixer": "send", "send": "ABCDEFGHIJKL"[i]})

    # top-level devices, then their racks with chain paths "c" / "c/d/c"
    for i, d in enumerate(t.devices):
        for p in d.parameters:
            add(p, {"device": i, "parameter": p.name})
        if getattr(d, "can_have_chains", False):
            _walk_rack(cs, d, i, [], add)
    return {"track": cs._ref(t), "count": len(out), "parameters": out}


def _walk_rack(cs, rack, top, prefix, add):
    for c, ch in enumerate(rack.chains):
        for k, d in enumerate(ch.devices):
            path = "/".join(str(x) for x in prefix + [c])
            for p in d.parameters:
                add(p, {"device": top, "chain": path, "chain_device": k, "parameter": p.name})
            if getattr(d, "can_have_chains", False):
                _walk_rack(cs, d, top, prefix + [c, k], add)


def cmd_set_automation_points(cs, track, slot, target, points, units="auto", mode="ramp", replace=True):
    """Write breakpoints into a session clip's envelope for one parameter (created if needed).
    points: [{"at": "1.1.1" or beats, "value": v}, ...] in clip-local musical time. mode "ramp": straight lines
    between points; "step": each value holds until the next point. replace clears the points' span first.
    Values are raw, or display units (units="display": dB, Hz, %, ms) converted per point."""
    t, clip, p, env = _envelope(cs, track, slot, target, create=True)
    if env is None:
        raise ToolError("Live gave no envelope for %s (an arrangement clip, or a parameter on another track?)" % p.name)
    pts = sorted(((_beats(cs, x["at"]), _to_raw(cs, p, x["value"], x.get("units", units))) for x in points),
                 key=lambda a: a[0])
    if not pts:
        raise ToolError("no points")
    end = clip.loop_end if clip.looping else clip.end_marker
    for b, _ in pts:
        if b < -1e-9 or b > end + 1e-6:
            raise ToolError("point at beat %g is outside the clip (0..%g)" % (b, end))
    import Live
    if replace:
        env.delete_events_in_range(pts[0][0], pts[-1][0])
    for i, (b, v) in enumerate(pts):
        env.create_event(Live.Envelope.EnvelopeEvent(b, v))
        if mode == "step" and i + 1 < len(pts):
            env.create_event(Live.Envelope.EnvelopeEvent(pts[i + 1][0], v))
    readback = [_read(p, env, b) for b, _ in pts]
    # Two points at one time make a step; just after it Live reads the second, so only that one is compared.
    last_at = {}
    for i, (b, _) in enumerate(pts):
        last_at[round(b, 9)] = i
    bad = [r for i, (r, (b, v)) in enumerate(zip(readback, pts))
           if last_at[round(b, 9)] == i and abs(r["raw"] - v) > max(1e-3, abs(p.max - p.min) * 1e-3)]
    return {"track": cs._ref(t), "parameter": p.name, "points": len(pts), "mode": mode, "readback": readback,
            "mismatches": bad}


def _shape_points(cs, shape, start, end, frm, to, resolution, rate, duty, curve):
    import math
    a, b = _beats(cs, start), _beats(cs, end)
    if b <= a:
        raise ToolError("end must be after start")
    res = float(resolution)
    pts = []
    if shape in ("ramp", "fade", "sweep"):
        if curve == "linear":
            pts = [(a, frm), (b, to)]
        else:
            n = max(2, int((b - a) / res) + 1)
            for i in range(n + 1):
                x = i / float(n)
                y = {"ease": 0.5 - 0.5 * math.cos(math.pi * x), "exp": x * x, "log": 1 - (1 - x) * (1 - x)}.get(curve, x)
                pts.append((a + (b - a) * x, frm + (to - frm) * y))
    elif shape == "hold":
        pts = [(a, frm), (b, frm)]
    elif shape == "pulse":
        period = float(rate)
        x = a
        while x < b - 1e-9:
            on_end = min(x + period * float(duty), b)
            pts += [(x, to), (on_end, to), (on_end, frm), (min(x + period, b), frm)]
            x += period
    elif shape in ("sine", "lfo"):
        period = float(rate)
        n = max(4, int((b - a) / res) + 1)
        for i in range(n + 1):
            x = a + (b - a) * i / float(n)
            pts.append((x, frm + (to - frm) * (0.5 - 0.5 * math.cos(2 * math.pi * (x - a) / period))))
    else:
        raise ToolError("shape: ramp, fade, sweep, hold, pulse, sine")
    return pts


def cmd_set_automation_curve(cs, track, slot, target, shape, start, end, frm, to=None, units="auto",
                             resolution=0.25, rate=1.0, duty=0.5, curve="linear", replace=True):
    """A shaped automation segment in musical time. shape: ramp/sweep/fade (frm -> to; curve linear, ease, exp,
    log), hold (frm), pulse (to for duty of each rate-beat period, else frm), sine (frm..to, period rate beats).
    Display units are converted per point, so a fade in dB is linear in dB."""
    to = frm if to is None else to
    step = shape == "pulse"
    t, clip, p, env = _envelope(cs, track, slot, target, create=True)
    if env is None:
        raise ToolError("Live gave no envelope for %s" % p.name)
    import Live
    # Interpolate in display units when both ends are finite numbers there (a dB fade is then linear in dB, a Hz
    # sweep linear in Hz unless curve shapes it); otherwise (quantized, -inf) interpolate the raw values.
    disp = units == "display" or (units == "auto" and isinstance(frm, str))
    a_num = cs._num(frm) if isinstance(frm, str) else (float(frm) if frm is not None else None)
    b_num = cs._num(to) if isinstance(to, str) else (float(to) if to is not None else None)
    if disp and not p.is_quantized and None not in (a_num, b_num) and float("-inf") not in (a_num, b_num):
        pts = _shape_points(cs, shape, start, end, a_num, b_num, resolution, rate, duty, curve)
        raw = [(b, float(cs._bisect(p, v))) for b, v in pts]
    else:
        ra, rb = _to_raw(cs, p, frm, units), _to_raw(cs, p, to, units)
        raw = _shape_points(cs, shape, start, end, ra, rb, resolution, rate, duty, curve)
    if replace:
        env.delete_events_in_range(raw[0][0], raw[-1][0])
    for b, v in raw:
        env.create_event(Live.Envelope.EnvelopeEvent(b, v))
    probe = [raw[0][0], (raw[0][0] + raw[-1][0]) / 2.0, raw[-1][0] - 1e-3]
    return {"track": cs._ref(t), "parameter": p.name, "shape": shape, "events": len(raw), "stepped": step,
            "samples": [_read(p, env, b) for b in probe]}


def cmd_get_automation(cs, track, slot, target, start=0, end=None, step=1.0):
    """Sample a session clip's envelope in musical time (value_at_time just after each sample point)."""
    t, clip, p, env = _envelope(cs, track, slot, target)
    if env is None:
        return {"track": cs._ref(t), "parameter": p.name, "has_envelope": False}
    a = _beats(cs, start)
    b = _beats(cs, end) if end is not None else (clip.loop_end if clip.looping else clip.end_marker)
    st = float(step)
    out, x = [], a
    while x <= b + 1e-9:
        out.append(_read(p, env, min(x, b - 1e-3)))
        x += st
    return {"track": cs._ref(t), "parameter": p.name, "has_envelope": True, "clip_length": clip.length,
            "looping": bool(clip.looping), "samples": out}


def cmd_delete_automation(cs, track, slot, target=None):
    """Clear one parameter's envelope in a session clip, or every envelope when target is omitted."""
    t, clip = _clip(cs, track, slot)
    if target is None:
        clip.clear_all_envelopes()
        return {"track": cs._ref(t), "cleared": "all"}
    _, p = _target_param(cs, track, target)
    clip.clear_envelope(p)
    return {"track": cs._ref(t), "cleared": p.name, "has_envelope": clip.automation_envelope(p) is not None}


def cmd_copy_automation(cs, track, slot, target, to_track, to_slot, to_target=None, resolution=0.0625):
    """Copy an envelope by sampling it (every `resolution` beats, default a 64th) into another clip/parameter of the
    same raw range. Lossy only below the resolution."""
    t, clip, p, env = _envelope(cs, track, slot, target)
    if env is None:
        raise ToolError("no envelope for %s" % p.name)
    t2, clip2, p2, env2 = _envelope(cs, to_track, to_slot, to_target or target, create=True)
    import Live
    end = min(clip.loop_end if clip.looping else clip.end_marker, clip2.loop_end if clip2.looping else clip2.end_marker)
    env2.delete_events_in_range(0.0, end)
    x, n, prev = 0.0, 0, None
    while x <= end + 1e-9:
        v = float(env.value_at_time(min(x, end - 1e-4) + 1e-4))
        v = min(max(v, p2.min), p2.max)
        if prev is None or abs(v - prev) > 1e-6 or x + float(resolution) > end:
            env2.create_event(Live.Envelope.EnvelopeEvent(x, v))
            n += 1
        prev = v
        x += float(resolution)
    return {"from": [cs._ref(t), slot, p.name], "to": [cs._ref(t2), to_slot, p2.name], "events": n}


def cmd_validate_automation(cs, track, slot, target, expect, units="auto", tolerance=None):
    """Check a session envelope against expected values: expect [{"at": pos, "value": v}]. Also reports the loop
    wrap: the value just before the loop end against the value at the loop start."""
    t, clip, p, env = _envelope(cs, track, slot, target)
    if env is None:
        return {"ok": False, "reason": "no envelope for %s" % p.name}
    tol = float(tolerance) if tolerance is not None else max(1e-3, abs(p.max - p.min) * 0.01)
    rows, ok = [], True
    for e in expect:
        b = _beats(cs, e["at"])
        want = _to_raw(cs, p, e["value"], e.get("units", units))
        got = _read(p, env, b)
        good = abs(got["raw"] - want) <= tol
        ok = ok and good
        rows.append({"at": e["at"], "beat": b, "want_raw": round(want, 6), "want_display": p.str_for_value(want),
                     "got": got, "ok": good})
    ls = clip.loop_start if clip.looping else 0.0
    le = clip.loop_end if clip.looping else clip.end_marker
    wrap = {"value_at_loop_end": _read(p, env, le - 2e-3), "value_at_loop_start": _read(p, env, ls)}
    wrap["jump_raw"] = round(wrap["value_at_loop_start"]["raw"] - wrap["value_at_loop_end"]["raw"], 6)
    return {"ok": ok, "parameter": p.name, "tolerance_raw": tol, "points": rows, "loop_wrap": wrap,
            "automation_state": int(getattr(p, "automation_state", 0))}


# ---------------------------------------------------------------------------------------------- sidechain
def _routing_out(rt):
    return {"name": rt.display_name, "category": getattr(rt, "category", None),
            "attached": getattr(getattr(rt, "attached_object", None), "name", None)}


def _sc_device(cs, track, device, chain=None, chain_device=None):
    t = cs._track(track)
    d = cs._device(t, device)
    if chain not in (None, ""):
        d = cs._device(t, device, chain)[int(chain_device or 0)]
    return t, d


def cmd_inspect_device_sidechain(cs, track, device, chain=None, chain_device=None):
    """Whether a device's sidechain source is reachable through the LOM (routing lists on the device), its current
    source, its choices, and its S/C parameters."""
    t, d = _sc_device(cs, track, device, chain, chain_device)
    sc = [cs._pout(p) for p in d.parameters if p.name.startswith("S/C") or p.original_name.startswith("S/C")]
    out = {"track": cs._ref(t), "device": d.name, "class_name": d.class_name, "sc_parameters": sc,
           "routable": hasattr(d, "available_input_routing_types")}
    if out["routable"]:
        out["source"] = _routing_out(d.input_routing_type)
        out["channel"] = d.input_routing_channel.display_name
        out["choices"] = [_routing_out(r) for r in d.available_input_routing_types]
        out["channels"] = [c.display_name for c in d.available_input_routing_channels]
    return out


def cmd_set_sidechain(cs, track, device, source, channel=None, on=True, chain=None, chain_device=None, params=None,
                      units="display"):
    """Point a device's sidechain at a source (a track ref/name, or a routing choice's exact name), optionally a
    channel ('Pre FX', 'Post FX', 'Post Mixer'), turn S/C on, and set S/C parameters. Refuses a source that is the
    device's own track."""
    t, d = _sc_device(cs, track, device, chain, chain_device)
    if not hasattr(d, "available_input_routing_types"):
        raise ToolError("%s (%s) exposes no sidechain routing through the LOM" % (d.name, d.class_name))
    choices = list(d.available_input_routing_types)
    want = None
    try:
        src = cs._track(source)
        if src == t:
            raise ToolError("a device can't sidechain from its own track")
        want = [r for r in choices if getattr(r, "attached_object", None) == src]
    except ToolError as e:
        if "own track" in str(e):
            raise
        want = [r for r in choices if r.display_name == str(source)]
    except Exception:
        want = [r for r in choices if r.display_name == str(source)]
    if len(want) != 1:
        raise ToolError("sidechain source %r: %d matches; choices are %s" % (source, len(want),
                                                                             [r.display_name for r in choices]))
    d.input_routing_type = want[0]
    if channel is not None:
        chs = [c for c in d.available_input_routing_channels if c.display_name == channel]
        if len(chs) != 1:
            raise ToolError("channel %r not offered: %s" % (channel, [c.display_name for c in d.available_input_routing_channels]))
        d.input_routing_channel = chs[0]
    results = []
    if on is not None:
        p = [x for x in d.parameters if x.name == "S/C On"]
        if p:
            p[0].value = p[0].max if on else p[0].min
    for k, v in (params or {}).items():
        results.append(cs._set_param(cs._param(d, k), v, units))
    return {"device": d.name, "source": _routing_out(d.input_routing_type), "channel": d.input_routing_channel.display_name,
            "sc_on": [cs._pout(x) for x in d.parameters if x.name == "S/C On"], "params": results}


# ---------------------------------------------------------------------------------------------- racks
def cmd_create_effect_rack(cs, track, index=-1, name=None, kind="Audio Effect Rack"):
    """Insert an empty rack (Track.insert_device, Live 12.3+). kind: Audio Effect Rack, Instrument Rack,
    MIDI Effect Rack, Drum Rack."""
    t = cs._track(track)
    d = t.insert_device(kind) if index is None or int(index) < 0 else t.insert_device(kind, int(index))
    if name:
        d.name = name
    return {"track": cs._ref(t), "rack": d.name, "class_name": d.class_name,
            "index": list(t.devices).index(d), "chains": len(d.chains)}


def _rack(cs, track, device, chain=None, chain_device=None):
    t, d = _sc_device(cs, track, device, chain, chain_device)
    if not getattr(d, "can_have_chains", False):
        raise ToolError("%s is not a rack" % d.name)
    return t, d


def cmd_add_rack_chain(cs, track, device, name=None, index=-1, chain=None, chain_device=None):
    """Add a chain to a rack (RackDevice.insert_chain, Live 12.3+)."""
    t, r = _rack(cs, track, device, chain, chain_device)
    ch = r.insert_chain() if index is None or int(index) < 0 else r.insert_chain(int(index))
    if ch is None:
        ch = list(r.chains)[-1 if index is None or int(index) < 0 else int(index)]
    if name:
        ch.name = name
    return {"rack": r.name, "chains": [c.name for c in r.chains]}


def cmd_insert_device_in_chain(cs, track, device, chain_index, name, index=-1, chain=None, chain_device=None):
    """Insert a native device into a rack chain by its exact browser name (Chain.insert_device)."""
    t, r = _rack(cs, track, device, chain, chain_device)
    chains = list(r.chains)
    if not 0 <= int(chain_index) < len(chains):
        raise ToolError("chain %s out of range (%d chains)" % (chain_index, len(chains)))
    ch = chains[int(chain_index)]
    d = ch.insert_device(name) if index is None or int(index) < 0 else ch.insert_device(name, int(index))
    return {"rack": r.name, "chain": ch.name, "inserted": d.name, "devices": [x.name for x in ch.devices]}


def cmd_set_chain_mixer(cs, track, device, chain_index, volume_db=None, pan=None, active=None, chain=None,
                        chain_device=None):
    """A rack chain's volume (dB as displayed), pan (-50..50) and activator."""
    t, r = _rack(cs, track, device, chain, chain_device)
    ch = list(r.chains)[int(chain_index)]
    m = ch.mixer_device
    res = {}
    if volume_db is not None:
        res["volume"] = cs._set_param(m.volume, volume_db, "display")["after"]["display"]
    if pan is not None:
        res["pan"] = cs._set_param(m.panning, pan, "display")["after"]["display"]
    if active is not None:
        m.chain_activator.value = m.chain_activator.max if active else m.chain_activator.min
        res["active"] = bool(m.chain_activator.value)
    return {"rack": r.name, "chain": ch.name, "now": res}


def cmd_set_rack_macros(cs, track, device, visible=None, values=None, units="auto", chain=None, chain_device=None):
    """Show `visible` macros (add_macro/remove_macro) and set macro values {"Macro 1": v}. Mapping a macro to a
    parameter is not in the LOM (see map_macro: a rack preset written with the mapping)."""
    t, r = _rack(cs, track, device, chain, chain_device)
    if visible is not None and hasattr(r, "visible_macro_count"):
        guard = 0
        while r.visible_macro_count < int(visible) and guard < 16:
            r.add_macro(); guard += 1
        while r.visible_macro_count > int(visible) and guard < 32:
            r.remove_macro(); guard += 1
    res = [cs._set_param(cs._param(r, k), v, units) for k, v in (values or {}).items()]
    return {"rack": r.name, "visible_macros": getattr(r, "visible_macro_count", None),
            "has_macro_mappings": getattr(r, "has_macro_mappings", None), "results": res}


# ---------------------------------------------------------------------------------------------- clips
def _any_clip(cs, track, slot=None, arrangement_index=None):
    t = cs._track(track)
    if arrangement_index is not None:
        cl = list(t.arrangement_clips)
        if not 0 <= int(arrangement_index) < len(cl):
            raise ToolError("arrangement clip %s out of range (%d)" % (arrangement_index, len(cl)))
        return t, cl[int(arrangement_index)]
    return _clip(cs, track, slot)


def _clip_out(c):
    out = {"name": c.name, "is_audio": bool(c.is_audio_clip), "length": c.length, "looping": bool(c.looping),
           "start_marker": c.start_marker, "end_marker": c.end_marker, "loop_start": c.loop_start,
           "loop_end": c.loop_end}
    if getattr(c, "is_arrangement_clip", False):
        out["start_time"] = c.start_time
        out["end_time"] = c.end_time
    if c.is_audio_clip:
        out.update({"pitch_coarse": c.pitch_coarse, "pitch_fine": c.pitch_fine, "gain": c.gain,
                    "gain_display": c.gain_display_string, "warping": bool(c.warping), "warp_mode": c.warp_mode,
                    "available_warp_modes": list(c.available_warp_modes), "file_path": c.file_path,
                    "sample_rate": getattr(c, "sample_rate", None)})
        try:
            out["warp_markers"] = [{"beat": w.beat_time, "seconds": w.sample_time} for w in c.warp_markers]
        except Exception:
            pass
    return out


def cmd_get_clip(cs, track, slot=None, arrangement_index=None):
    t, c = _any_clip(cs, track, slot, arrangement_index)
    return dict(_clip_out(c), track=cs._ref(t))


def cmd_set_clip(cs, track, slot=None, arrangement_index=None, name=None, pitch_coarse=None, pitch_fine=None,
                 gain=None, warping=None, warp_mode=None, looping=None, loop_start=None, loop_end=None,
                 start_marker=None, end_marker=None):
    """Clip properties in musical time (positions as beats or 'bar.beat.sixteenth'). warp_mode: 0 beats, 1 tones,
    2 texture, 3 re-pitch, 4 complex, 6 complex pro. Reads everything back."""
    t, c = _any_clip(cs, track, slot, arrangement_index)
    if name is not None:
        c.name = name
    if c.is_audio_clip:
        if warping is not None:
            c.warping = bool(warping)
        if warp_mode is not None:
            if int(warp_mode) not in list(c.available_warp_modes):
                raise ToolError("warp mode %s not available: %s" % (warp_mode, list(c.available_warp_modes)))
            c.warp_mode = int(warp_mode)
        if pitch_coarse is not None:
            c.pitch_coarse = int(pitch_coarse)
        if pitch_fine is not None:
            c.pitch_fine = float(pitch_fine)
        if gain is not None:
            c.gain = float(gain)
    # Live ignores start_marker writes on an unlooped clip (measured 2026-11-10), so markers are written while the
    # clip loops, and looping is switched off last.
    was = bool(c.looping)
    if (start_marker is not None or end_marker is not None) and not was:
        c.looping = True
    if loop_end is not None:
        c.loop_end = _beats(cs, loop_end)
    if loop_start is not None:
        c.loop_start = _beats(cs, loop_start)
    if end_marker is not None:
        c.end_marker = _beats(cs, end_marker)
    if start_marker is not None:
        c.start_marker = _beats(cs, start_marker)
    if looping is not None:
        c.looping = bool(looping)
    elif c.looping != was:
        c.looping = was
    return dict(_clip_out(c), track=cs._ref(t))


def cmd_warp_marker(cs, track, action, beat, slot=None, arrangement_index=None, seconds=None, delta=None):
    """action add (beat + seconds), move (beat, delta beats) or remove (beat) on an audio clip."""
    import Live
    t, c = _any_clip(cs, track, slot, arrangement_index)
    if not c.is_audio_clip:
        raise ToolError("warp markers need an audio clip")
    b = _beats(cs, beat)
    if action == "add":
        c.add_warp_marker(Live.Clip.WarpMarker(sample_time=float(seconds), beat_time=b))
    elif action == "move":
        c.move_warp_marker(b, float(delta))
    elif action == "remove":
        c.remove_warp_marker(b)
    else:
        raise ToolError("action: add, move, remove")
    return dict(_clip_out(c), track=cs._ref(t))


def cmd_set_song_time(cs, tempo=None, numerator=None, denominator=None, loop=None, loop_start=None, loop_length=None,
                      position=None):
    """Tempo, time signature (denominator 1/2/4/8/16) and the arrangement loop brace, in musical time."""
    s = cs._song
    if tempo is not None:
        s.tempo = float(tempo)
    if numerator is not None:
        s.signature_numerator = int(numerator)
    if denominator is not None:
        s.signature_denominator = int(denominator)
    if loop_start is not None:
        s.loop_start = _beats(cs, loop_start)
    if loop_length is not None:
        s.loop_length = float(loop_length) if not isinstance(loop_length, str) else _beats(cs, loop_length)
    if loop is not None:
        s.loop = bool(loop)
    if position is not None:
        # Playback starts from the start marker (Song.start_time), not the playhead: setting only
        # current_song_time while stopped still started at beat 0 (measured 2026-11-10). Set both.
        b = _beats(cs, position)
        s.start_time = b
        s.current_song_time = b
    return {"tempo": s.tempo, "position": s.current_song_time, "start_marker": s.start_time, "signature": "%d/%d" % (s.signature_numerator, s.signature_denominator),
            "loop": bool(s.loop), "loop_start": s.loop_start, "loop_length": s.loop_length,
            "note": "loop changes apply on Live's next tick: read back with set_song_time() after a moment"}


# ---------------------------------------------------------------------------------------------- in-Live capture
_CAPTURE = {}


def cmd_capture_start(cs, tracks, seconds=16.0, params=None):
    """Sample output meters (dBFS = 76*raw-70) and optional parameters inside Live on every UI tick (about 10 Hz),
    stamped with song time, for `seconds`. params: [{"track": ref, "target": {...}}]. Read with capture_result."""
    ts = [cs._track(r) for r in tracks]
    ps = [(x, _target_param(cs, x["track"], x["target"])[1]) for x in (params or [])]
    cap = {"rows": [], "done": False, "until": None}
    _CAPTURE["current"] = cap
    import time as _t
    cap["until"] = _t.time() + float(seconds)

    def tick():
        if _CAPTURE.get("current") is not cap:
            return
        row = {"t": round(float(cs._song.current_song_time), 4), "playing": bool(cs._song.is_playing)}
        for t in ts:
            lvl = float(t.output_meter_level)
            row[cs._ref(t)] = round(76.0 * lvl - 70.0, 2) if lvl > 0 else None
        for x, p in ps:
            row["%s:%s" % (x["track"], p.name)] = round(float(p.value), 5)
        cap["rows"].append(row)
        if _t.time() < cap["until"]:
            cs.schedule_message(1, tick)
        else:
            cap["done"] = True

    cs.schedule_message(1, tick)
    return {"started": True, "seconds": seconds}


def cmd_capture_result(cs):
    cap = _CAPTURE.get("current")
    if cap is None:
        raise ToolError("no capture started")
    return {"done": cap["done"], "count": len(cap["rows"]), "rows": cap["rows"] if cap["done"] else []}


# ---------------------------------------------------------------------------------------------- arrangement
def cmd_duplicate_to_arrangement(cs, track, slot, at):
    """Copy a session clip into the Arrangement at a musical position (Track.duplicate_clip_to_arrangement).
    Reports whether the copy kept its clip envelopes (the repos disagree; measure it here)."""
    t, clip = _clip(cs, track, slot)
    before = len(list(t.arrangement_clips))
    t.duplicate_clip_to_arrangement(clip, _beats(cs, at))
    cl = list(t.arrangement_clips)
    new = [c for c in cl if abs(c.start_time - _beats(cs, at)) < 1e-6]
    c = new[-1] if new else cl[-1]
    return {"track": cs._ref(t), "arrangement_clips": len(cl), "added": len(cl) - before,
            "start": c.start_time, "end": c.end_time, "source_had_envelopes": bool(clip.has_envelopes),
            "copy_has_envelopes": bool(getattr(c, "has_envelopes", False)),
            "index": cl.index(c)}


def cmd_delete_arrangement_clip(cs, track, index):
    cs._require_scratch()
    t = cs._track(track)
    cl = list(t.arrangement_clips)
    t.delete_clip(cl[int(index)])
    return {"track": cs._ref(t), "arrangement_clips": len(list(t.arrangement_clips))}


_REC = {}
SETTLE_BEATS = 0.5   # wait this long after recording starts rolling before the gesture (see record_arrangement_automation)


def _interp(pts, x):
    if x <= pts[0][0]:
        return pts[0][1]
    for (a, va), (b, vb) in zip(pts, pts[1:]):
        if a <= x <= b:
            if b - a < 1e-9:
                return vb
            return va + (vb - va) * (x - a) / (b - a)
    return pts[-1][1]


def cmd_record_arrangement_automation(cs, track, target, points, units="auto", preroll_bars=1):
    """Record automation into the Arrangement in real time: Automation Arm on, Arrangement Record on, play from a bar
    before the first point, write the parameter every UI tick (~10 Hz) inside a begin/end gesture, then stop and
    restore the transport state. points: [{"at": pos, "value": v}] in song time (bars from the song start); straight
    lines between points. Armed tracks are disarmed for the pass so nothing else records. Asynchronous: poll
    record_arrangement_status. The LOM can't draw arrangement automation, so this is the supported route."""
    t, p = _target_param(cs, track, target)
    pts = sorted(((_beats(cs, x["at"]), _to_raw(cs, p, x["value"], x.get("units", units))) for x in points),
                 key=lambda a: a[0])
    if len(pts) < 2:
        raise ToolError("give at least two points")
    s = cs._song
    if s.is_playing:
        raise ToolError("stop playback first")
    state = {"loop": s.loop, "time": s.current_song_time, "aarm": s.session_automation_record,
             "armed": [x for x in s.tracks if getattr(x, "can_be_armed", False) and x.arm],
             "punch_in": s.punch_in, "punch_out": s.punch_out}
    for x in state["armed"]:
        x.arm = False
    # A MIDI controller makes Live arm the selected MIDI track implicitly (Track.implicit_arm), which `arm` doesn't
    # show; that pass then records silence over the track's clips (measured 2026-11-10: it overwrote an 8-bar clip).
    # Select the Main track for the pass so nothing is implicitly armed.
    state["selected"] = s.view.selected_track
    s.view.selected_track = s.master_track
    implicit = [x.name for x in s.tracks if getattr(x, "implicit_arm", False)]
    if implicit:
        raise ToolError("tracks still implicitly armed: %s" % implicit)
    start = max(0.0, pts[0][0] - float(preroll_bars) * _beats_per_bar(cs))
    rec = {"phase": "arming", "written": 0, "done": False, "error": None, "start": start, "end": pts[-1][0],
           "parameter": p.name, "first_value": None}
    _REC["current"] = rec
    p.value = pts[0][1]
    s.stop_all_clips()
    if s.back_to_arranger:
        s.back_to_arranger = False        # "Back to Arrangement": tracks follow the Arrangement again
    s.loop = False
    s.punch_in = False
    s.punch_out = False
    s.session_automation_record = True
    s.current_song_time = start

    def finish(err=None):
        try:
            if rec.get("gesture"):
                p.end_gesture()
        except Exception:
            pass
        s.record_mode = False
        s.stop_playing()
        s.session_automation_record = state["aarm"]
        s.loop = state["loop"]
        s.punch_in, s.punch_out = state["punch_in"], state["punch_out"]
        for x in state["armed"]:
            x.arm = True
        try:
            s.view.selected_track = state["selected"]
        except Exception:
            pass
        rec["error"] = err
        rec["done"] = True
        rec["phase"] = "done"

    def tick():
        if _REC.get("current") is not rec or rec["done"]:
            return
        try:
            if rec["phase"] == "arming":
                live = [x.name for x in s.tracks if getattr(x, "can_be_armed", False)
                        and (x.arm or getattr(x, "implicit_arm", False))]
                if live:                      # never record over clips: refuse instead
                    finish("tracks still armed, refusing to record: %s" % live)
                    return
                s.record_mode = True          # starts playback ("Start Playback with Record")
                rec["phase"] = "rolling"
            else:
                now = float(s.current_song_time)
                rec["record_mode_seen"] = rec.get("record_mode_seen", False) or bool(s.record_mode)
                rec["playing_seen"] = rec.get("playing_seen", False) or bool(s.is_playing)
                # Begin the gesture only once Live is really recording and rolling: a gesture begun in the tick
                # record_mode was switched on is not recorded at all (measured 2026-11-10, a pass from bar 1).
                if not rec.get("rolling_since") and s.record_mode and s.is_playing:
                    rec["rolling_since"] = now
                settle = rec.get("rolling_since") is not None and now >= rec["rolling_since"] + float(SETTLE_BEATS)
                if now >= pts[0][0] and not rec.get("gesture") and settle:
                    p.begin_gesture()
                    rec["gesture"] = True
                if rec.get("gesture"):
                    v = _interp(pts, now)
                    p.value = min(max(v, p.min), p.max)
                    rec["written"] += 1
                if now >= pts[-1][0]:
                    p.value = pts[-1][1]
                    finish()
                    return
            cs.schedule_message(1, tick)
        except Exception as e:
            finish("%s: %s" % (type(e).__name__, e))

    cs.schedule_message(1, tick)
    return {"started": True, "parameter": p.name, "from_beat": start, "to_beat": pts[-1][0],
            "seconds": (pts[-1][0] - start) * 60.0 / s.tempo}


def cmd_record_arrangement_status(cs):
    rec = _REC.get("current")
    if rec is None:
        raise ToolError("no recording started")
    return {k: v for k, v in rec.items() if k != "gesture"}


def cmd_param_state(cs, track, target):
    """A parameter's value and automation state (0 none, 1 playing, 2 overridden: re-enable to follow again)."""
    t, p = _target_param(cs, track, target)
    return {"parameter": p.name, "value": p.value, "display": p.str_for_value(p.value),
            "automation_state": int(getattr(p, "automation_state", 0))}


def cmd_re_enable_automation(cs, track=None, target=None):
    if target is not None:
        t, p = _target_param(cs, track, target)
        p.re_enable_automation()
        return {"parameter": p.name, "automation_state": int(p.automation_state)}
    cs._song.re_enable_automation()
    return {"song": True}


def cmd_set_arm(cs, track, arm):
    """Arm or disarm a track for recording; reports explicit and implicit (controller-selected) arm."""
    t = cs._track(track)
    if not getattr(t, "can_be_armed", False):
        raise ToolError("%s can't be armed" % t.name)
    t.arm = bool(arm)
    return {"track": cs._ref(t), "arm": bool(t.arm), "implicit_arm": bool(getattr(t, "implicit_arm", False))}


def cmd_back_to_arrangement(cs):
    """Press Back to Arrangement: every track follows the Arrangement (and its automation) again. Needed after
    stopping session clips, which leaves tracks detached from the Arrangement."""
    s = cs._song
    was = bool(s.back_to_arranger)
    if was:
        s.back_to_arranger = False
    return {"was_detached": was, "note": "applies on Live's next tick"}


# ---------------------------------------------------------------------------------------------- recording
_RECA = {}


def cmd_record_track_audio(cs, dst, source, slot=0, bars=2, channel=None, monitoring="off"):
    """Record a track's output into a session clip on an audio track: input = the source track (or "Resampling"
    for the Main), monitoring off (so the source isn't heard twice), arm, launch the slot recording, and stop it
    after exactly `bars` bars on Live's clock. Asynchronous: poll record_track_audio_status. The source must play
    (fire its clip or play the Arrangement) during the pass."""
    t = cs._track(dst)
    if t.has_midi_input:
        raise ToolError("%s is a MIDI track: record audio onto an audio track" % t.name)
    choices = list(t.available_input_routing_types)
    try:
        src = cs._track(source)
        want = [r for r in choices if getattr(r, "attached_object", None) == src]
    except Exception:
        want = [r for r in choices if r.display_name == str(source)]
    if len(want) != 1:
        raise ToolError("input %r: %d matches; choices %s" % (source, len(want), [r.display_name for r in choices]))
    t.input_routing_type = want[0]
    rec = {"phase": "routing", "done": False, "error": None}
    _RECA["current"] = rec
    length = float(bars) * _beats_per_bar(cs)
    cslot = list(t.clip_slots)[int(slot)]
    if cslot.has_clip:
        raise ToolError("slot %s of %s already holds a clip" % (slot, t.name))

    def tick():
        if _RECA.get("current") is not rec or rec["done"]:
            return
        try:
            if rec["phase"] == "routing":       # routing applies on the next tick
                if channel is not None:
                    chs = [c for c in t.available_input_routing_channels if c.display_name == channel]
                    if len(chs) != 1:
                        raise ToolError("channel %r not offered: %s" % (channel, [c.display_name for c in t.available_input_routing_channels]))
                    t.input_routing_channel = chs[0]
                t.current_monitoring_state = {"in": 0, "auto": 1, "off": 2}[monitoring]
                t.arm = True
                rec["input"] = t.input_routing_type.display_name
                rec["channel"] = t.input_routing_channel.display_name
                rec["phase"] = "launch"
            elif rec["phase"] == "launch":
                try:
                    cslot.fire(record_length=length)
                    rec["method"] = "fire(record_length)"
                except TypeError:
                    cslot.fire()
                    rec["method"] = "fire() + timed stop"
                rec["phase"] = "recording"
            elif rec["phase"] == "recording":
                c = cslot.clip
                if c is not None and c.is_recording:
                    rec["started"] = True
                if rec.get("started") and c is not None and not c.is_recording:
                    t.arm = False
                    rec.update(phase="done", done=True, clip_length=c.length, file=c.file_path)
                    return
                if rec.get("method", "").startswith("fire()") and c is not None and c.is_recording \
                        and c.length >= length:
                    cslot.fire()                 # a second launch ends the recording
            cs.schedule_message(1, tick)
        except Exception as e:
            t.arm = False
            rec.update(phase="done", done=True, error="%s: %s" % (type(e).__name__, e))

    cs.schedule_message(1, tick)
    return {"started": True, "dst": cs._ref(t), "bars": bars, "beats": length}


def cmd_record_track_audio_status(cs):
    rec = _RECA.get("current")
    if rec is None:
        raise ToolError("no recording started")
    return dict(rec)


def cmd_create_audio_clip(cs, track, path, slot=None, at=None):
    """Load an audio file as a clip: into a session slot (ClipSlot.create_audio_clip) or into the Arrangement at a
    musical position (Track.create_audio_clip). Audio tracks only; the path must be absolute. In the Arrangement it
    pastes over whatever is there (it splits or trims existing clips)."""
    import os
    t = cs._track(track)
    if t.has_midi_input:
        raise ToolError("%s is a MIDI track" % t.name)
    if not os.path.isabs(path) or not os.path.exists(path):
        raise ToolError("not an existing absolute path: %s" % path)
    if slot is not None:
        cslot = list(t.clip_slots)[int(slot)]
        if cslot.has_clip:
            raise ToolError("slot %s already holds a clip" % slot)
        cslot.create_audio_clip(path)
        return dict(_clip_out(cslot.clip), track=cs._ref(t), slot=int(slot))
    if at is None:
        raise ToolError("give slot or at")
    c = t.create_audio_clip(path, _beats(cs, at))
    return dict(_clip_out(c), track=cs._ref(t))


# ---------------------------------------------------------------------------------------------- arrangement editing
# Measured on 12.4.16: an unlooped arrangement clip's length follows its markers (end_time = start_time + end_marker -
# start_marker); start_marker moves the content, not the clip; there is no API to move or resize a clip in place, so a
# move is a verified copy (duplicate_clip_to_arrangement, which pastes over whatever is there) and a delete. Moves go
# through a temporary spot past the track's last clip so a short shift never pastes over its own source.
def _aclips(t):
    return list(t.arrangement_clips)


def _aclip_at(t, start, tol=1e-6):
    hits = [c for c in _aclips(t) if abs(c.start_time - start) < tol]
    if not hits:
        raise ToolError("no arrangement clip starting at beat %g on %s" % (start, t.name))
    return hits[-1]


def _temp_pos(t):
    ends = [c.end_time for c in _aclips(t)]
    bpb = 4.0
    return (max(ends) if ends else 0.0) + 16 * bpb


def _same(a, b):
    return abs(a.length - b.length) < 1e-6 and a.name == b.name and a.is_audio_clip == b.is_audio_clip


def _aclip_ref(cs, track, index=None, at=None):
    t = cs._track(track)
    if at is not None:
        return t, _aclip_at(t, _beats(cs, at))
    cl = _aclips(t)
    if index is None or not 0 <= int(index) < len(cl):
        raise ToolError("arrangement clip index %s out of range (%d clips)" % (index, len(cl)))
    return t, cl[int(index)]


def cmd_list_arrangement_clips(cs, track):
    t = cs._track(track)
    return {"track": cs._ref(t), "clips": [{"index": i, "name": c.name, "start": c.start_time, "end": c.end_time,
                                             "looping": bool(c.looping), "audio": bool(c.is_audio_clip)}
                                            for i, c in enumerate(_aclips(t))]}


def cmd_copy_arrangement_clip(cs, track, to, index=None, at=None, to_track=None):
    """Copy an arrangement clip to a musical position (and optionally another track of the same kind). The copy
    pastes over whatever is at the destination."""
    t, c = _aclip_ref(cs, track, index, at)
    dt = cs._track(to_track) if to_track is not None else t
    if dt.has_midi_input != t.has_midi_input:
        raise ToolError("copy MIDI clips to MIDI tracks and audio clips to audio tracks")
    new = dt.duplicate_clip_to_arrangement(c, _beats(cs, to))
    return {"track": cs._ref(dt), "start": new.start_time, "end": new.end_time, "name": new.name}


def cmd_move_arrangement_clip(cs, track, to, index=None, at=None, to_track=None):
    """Move an arrangement clip: copy to a temporary spot, verify, delete the original, copy to the destination,
    verify, delete the temporary copy. Content (markers, loop, envelopes the clip carries) moves with it."""
    t, c = _aclip_ref(cs, track, index, at)
    dt = cs._track(to_track) if to_track is not None else t
    if dt.has_midi_input != t.has_midi_input:
        raise ToolError("move MIDI clips to MIDI tracks and audio clips to audio tracks")
    dest = _beats(cs, to)
    tmp_pos = max(_temp_pos(t), _temp_pos(dt))
    tmp = dt.duplicate_clip_to_arrangement(c, tmp_pos)
    if not _same(tmp, c):
        dt.delete_clip(tmp)
        raise ToolError("temporary copy didn't match the source; nothing moved")
    t.delete_clip(c)
    tmp = _aclip_at(dt, tmp_pos)
    new = dt.duplicate_clip_to_arrangement(tmp, dest)
    ok = _same(new, tmp)
    dt.delete_clip(_aclip_at(dt, tmp_pos))
    if not ok:
        raise ToolError("final copy didn't match; the clip is at beat %g, check it" % dest)
    new = _aclip_at(dt, dest)
    return {"track": cs._ref(dt), "start": new.start_time, "end": new.end_time, "name": new.name}


def cmd_trim_arrangement_clip(cs, track, index=None, at=None, start=None, end=None):
    """Trim an arrangement clip to [start, end) in song time, keeping its content in place (the clip is unlooped).
    Trimming the head shifts the start marker and moves the clip, so the audio/MIDI stays where it was."""
    t, c = _aclip_ref(cs, track, index, at)
    s0, e0 = c.start_time, c.end_time
    ns = _beats(cs, start) if start is not None else s0
    ne = _beats(cs, end) if end is not None else e0
    if not s0 - 1e-9 <= ns < ne <= e0 + 1e-9:
        raise ToolError("trim must stay inside the clip (%g..%g): got %g..%g" % (s0, e0, ns, ne))
    if c.looping:
        c.looping = False
    # For an unlooped clip, the LOM's clip start/end are loop_start/loop_end (the markers alone didn't carry into a
    # copy: a head-trimmed copy came out at full length, measured 2026-11-10). Set both pairs, end first.
    base = c.loop_start
    new_end = base + (ne - s0)
    c.loop_end = new_end
    c.end_marker = new_end
    if ns > s0 + 1e-9:
        new_start = base + (ns - s0)
        c.loop_start = new_start
        c.start_marker = new_start
        moved = cmd_move_arrangement_clip(cs, track, ns, at=s0)
        c = _aclip_at(t, ns)
    return {"track": cs._ref(t), "start": c.start_time, "end": c.end_time, "start_marker": c.start_marker,
            "end_marker": c.end_marker}


def cmd_split_arrangement_clip(cs, track, split_at, index=None, at=None):
    """Split an arrangement clip at a song position into two clips that play exactly as before."""
    t, c = _aclip_ref(cs, track, index, at)
    s0, e0 = c.start_time, c.end_time
    x = _beats(cs, split_at)
    if not s0 + 1e-9 < x < e0 - 1e-9:
        raise ToolError("split point %g is not inside the clip (%g..%g)" % (x, s0, e0))
    tmp_pos = _temp_pos(t)
    t.duplicate_clip_to_arrangement(c, tmp_pos)          # second half, prepared away from the source
    a = cmd_trim_arrangement_clip(cs, track, at=s0, end=x)
    b = cmd_trim_arrangement_clip(cs, track, at=tmp_pos, start=tmp_pos + (x - s0))
    moved = cmd_move_arrangement_clip(cs, track, x, at=tmp_pos + (x - s0))
    return {"track": cs._ref(t), "first": [a["start"], a["end"]], "second": [moved["start"], moved["end"]]}


def cmd_create_arrangement_midi_clip(cs, track, at, length, notes=None, name=None):
    """An empty or filled MIDI clip directly in the Arrangement (Track.create_midi_clip). notes: [[pitch, start,
    length, velocity], ...] in clip beats."""
    import Live
    t = cs._track(track)
    if not t.has_midi_input:
        raise ToolError("%s is not a MIDI track" % t.name)
    c = t.create_midi_clip(_beats(cs, at), float(length) if not isinstance(length, str) else _beats(cs, length))
    if name:
        c.name = name
    if notes:
        c.add_new_notes(tuple(Live.Clip.MidiNoteSpecification(pitch=int(p), start_time=float(s), duration=float(d),
                                                              velocity=float(v), mute=False) for p, s, d, v in notes))
    return {"track": cs._ref(t), "start": c.start_time, "end": c.end_time, "name": c.name}
