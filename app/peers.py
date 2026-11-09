"""Bounded, asynchronous reads of the configured tailnet peers."""
import copy
import http.client
import ipaddress
import json
import math
import socket
import threading
import time
from pathlib import Path


_RANGES = (ipaddress.ip_network("100.64.0.0/10"),)
_lock = threading.Lock()
_peers = []
_token_file = None
_results = []
_round_id = 0
_running = False
_callback = None


def load(path=None):
    """Replace the peer list. Invalid or unreadable configuration yields no peers."""
    global _peers, _token_file, _results, _round_id, _running
    path = Path.home() / ".config/nixi-companion/peers.json" if path is None else path
    try:
        config = json.loads(Path(path).read_text())
        entries = config["peers"]
        if not isinstance(entries, list):
            raise ValueError("peers must be a list")
    except (OSError, ValueError, TypeError, KeyError):
        config, entries = {}, []
    peers = []
    for entry in entries:
        try:
            if not isinstance(entry["address"], str):
                continue
            address = ipaddress.IPv4Address(entry["address"])
            port = entry["port"]
            name = entry["name"]
            if (address == ipaddress.IPv4Address("100.100.100.100") or
                    not any(address in network for network in _RANGES) or
                    not isinstance(name, str) or not name or
                    type(port) is not int or not 1 <= port <= 65535):
                continue
            peers.append({"name": name, "address": str(address), "port": port})
        except (KeyError, TypeError, ValueError, ipaddress.AddressValueError):
            continue
    token_file = config.get("token_file")
    if not isinstance(token_file, str):
        token_file = None
    with _lock:
        _round_id += 1
        _running = False
        _peers = peers
        _token_file = token_file
        _results = [{"name": peer["name"], "state": "asking", "status": None,
                     "last_ok": None} for peer in peers]
    return peers


def _number(value):
    return type(value) is int or type(value) is float and math.isfinite(value)


def _status(body):
    value = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if not isinstance(value, dict):
        raise ValueError()
    strings = ("host", "generation", "rev", "built")
    for key in strings:
        if key not in value or value[key] is not None and not isinstance(value[key], str):
            raise ValueError()
    for key in ("cpu_pct", "uptime_s"):
        if key not in value or value[key] is not None and not _number(value[key]):
            raise ValueError()
    if value.get("failed") is not None or "failed" not in value:
        raise ValueError()
    mem = value.get("mem")
    if "mem" not in value or mem is not None and (not isinstance(mem, dict) or
            any(type(mem.get(key)) is not int for key in ("total", "available"))):
        raise ValueError()
    disks = value.get("disks")
    if "disks" not in value or disks is not None and (not isinstance(disks, list) or
            any(not isinstance(disk, dict) or not isinstance(disk.get("path"), str) or
                any(type(disk.get(key)) is not int for key in ("total", "used")) for disk in disks)):
        raise ValueError()
    net = value.get("net")
    if "net" not in value or net is not None and (not isinstance(net, dict) or
            any(key not in net or net[key] is not None and type(net[key]) is not int
                for key in ("rx_bps", "tx_bps"))):
        raise ValueError()
    failed = value.get("failed_system")
    if "failed_system" not in value or failed is not None and (not isinstance(failed, list) or
            any(not isinstance(unit, str) for unit in failed)):
        raise ValueError()
    return {**{key: value[key] for key in strings},
            **{key: value[key] for key in ("cpu_pct", "uptime_s")},
            "failed": None, "mem": None if mem is None else {key: mem[key] for key in ("total", "available")},
            "disks": None if disks is None else [{key: disk[key] for key in ("path", "total", "used")} for disk in disks],
            "net": None if net is None else {key: net[key] for key in ("rx_bps", "tx_bps")},
            "failed_system": failed}


def _ask(peer, token, results, index, conns):
    conn = http.client.HTTPConnection(peer["address"], peer["port"], timeout=1.5)
    try:
        conn.connect()
        conns[index] = conn.sock                       # the raw socket, so the round can cut it off (the response drops conn.sock)
        conn.request("GET", "/v1/status", headers={"Authorization": "Bearer " + token})
        response = conn.getresponse()
        if response.status != 200:
            results[index] = (None, "unreachable")
            return
        try:
            body = response.read(16 * 1024 + 1)
            if len(body) > 16 * 1024:
                raise ValueError()
            results[index] = (_status(body), None, time.time())
        except (OSError, ValueError, UnicodeError, RecursionError, http.client.HTTPException):
            results[index] = (None, "gave an answer Nixi can't read")
    except (OSError, http.client.HTTPException):
        results[index] = (None, "unreachable")
    finally:
        conn.close()


def _round(number, peers, token_file):
    global _running, _results
    deadline = time.monotonic() + 2
    try:
        token = Path(token_file).read_text().strip() if token_file else ""
    except (OSError, UnicodeError):
        token = ""
    answers = [None] * len(peers)
    if token:
        conns = [None] * len(peers)
        threads = [threading.Thread(target=_ask, args=(peer, token, answers, i, conns), daemon=True)
                   for i, peer in enumerate(peers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        for i, thread in enumerate(threads):           # a peer still talking at the deadline is cut off: the socket timeout only bounds silence
            if thread.is_alive() and conns[i] is not None:
                try:
                    conns[i].shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
    answers = answers.copy()
    with _lock:
        if number != _round_id:
            return
        previous = _results
        _results = []
        for i, peer in enumerate(peers):
            answer = answers[i]
            old = previous[i]
            status = answer[0] if answer else None
            row = {"name": peer["name"], "state": "up" if status is not None else "down",
                   "status": status, "last_ok": answer[2] if status is not None else old["last_ok"]}
            if status is None:
                row["note"] = "no token" if not token else answer[1] if answer else "unreachable"
            _results.append(row)
        _running = False
        callback = _callback
    if callback:
        callback()


def snapshot():
    """Return cached states immediately and start one background round."""
    global _running
    with _lock:
        result = copy.deepcopy(_results)
        if not _running and _peers:
            _running = True
            number, peers, token_file = _round_id, list(_peers), _token_file
            threading.Thread(target=_round, args=(number, peers, token_file), daemon=True).start()
    return result


def current():
    """Return cached states without starting a round."""
    with _lock:
        return copy.deepcopy(_results)


def stop():
    """Discard any running round and all cached readings."""
    global _round_id, _running, _results
    with _lock:
        _round_id += 1
        _running = False
        _results = [{"name": peer["name"], "state": "asking", "status": None,
                     "last_ok": None} for peer in _peers]


def on_round(cb):
    global _callback
    with _lock:
        _callback = cb
