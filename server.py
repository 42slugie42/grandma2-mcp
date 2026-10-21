"""
grandMA2 onPC MCP server.

Connects to grandMA2 (onPC or console) via its Telnet remote interface and
exposes the command line, XML import/export, Lua execution, patching, song
analysis and song-synced cue list building as MCP tools.

Requirements in grandMA2:
  Setup -> Console -> Global Settings -> Telnet: "Login Enabled"

Environment variables (all optional):
  GMA2_HOST      default 127.0.0.1
  GMA2_PORT      default 30000
  GMA2_USER      default administrator
  GMA2_PASSWORD  default admin
  GMA2_DATA_DIR  default: newest C:\\ProgramData\\MA Lighting Technologies\\grandma\\gma2_V_*
"""

from __future__ import annotations

import glob
import json
import os
import re
import socket
import threading
import time
from pathlib import Path

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

HOST = os.environ.get("GMA2_HOST", "127.0.0.1")
PORT = int(os.environ.get("GMA2_PORT", "30000"))
USER = os.environ.get("GMA2_USER", "administrator")
PASSWORD = os.environ.get("GMA2_PASSWORD", "admin")


def _find_data_dir() -> Path | None:
    env = os.environ.get("GMA2_DATA_DIR")
    if env:
        return Path(env)
    base = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                        "MA Lighting Technologies", "grandma", "gma2_V_*")
    candidates = sorted(glob.glob(base))
    return Path(candidates[-1]) if candidates else None


DATA_DIR = _find_data_dir()

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PROMPT_RE = re.compile(r"(\]| )>\s*$")  # "[Channel]>" or "EditSetup/Layers 4 >"


class TelnetClient:
    """Minimal telnet client (telnetlib was removed in Python 3.13)."""

    def __init__(self) -> None:
        self.sock: socket.socket | None = None
        self.lock = threading.Lock()

    # -- low level -------------------------------------------------------
    def _strip_negotiation(self, data: bytes) -> bytes:
        out = bytearray()
        i = 0
        while i < len(data):
            b = data[i]
            if b != IAC:
                out.append(b)
                i += 1
                continue
            if i + 1 >= len(data):
                break
            cmd = data[i + 1]
            if cmd in (DO, DONT, WILL, WONT) and i + 2 < len(data):
                opt = data[i + 2]
                if cmd == DO:
                    self.sock.sendall(bytes([IAC, WONT, opt]))
                elif cmd == WILL:
                    self.sock.sendall(bytes([IAC, DONT, opt]))
                i += 3
            elif cmd == SB:
                end = data.find(bytes([IAC, SE]), i)
                i = len(data) if end == -1 else end + 2
            elif cmd == IAC:
                out.append(IAC)
                i += 2
            else:
                i += 2
        return bytes(out)

    def _read(self, timeout: float, idle: float, expect: int = 1) -> str:
        """Read until `expect` commands have echoed and a prompt shows up,
        the line goes quiet, or timeout."""
        assert self.sock is not None
        buf = ""
        deadline = time.time() + timeout
        last_data = time.time()
        while time.time() < deadline:
            self.sock.settimeout(0.1)
            try:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("grandMA2 closed the telnet connection")
                buf += self._strip_negotiation(chunk).decode("utf-8", "replace")
                last_data = time.time()
                clean = ANSI_RE.sub("", buf)
                if PROMPT_RE.search(clean) and clean.count("Executing") >= expect:
                    # give trailing lines a brief chance to arrive
                    idle = min(idle, 0.2)
            except socket.timeout:
                pass
            if buf and time.time() - last_data > idle:
                break
        return buf

    @staticmethod
    def _clean(text: str) -> str:
        text = ANSI_RE.sub("", text).replace("\r", "")
        lines = [ln.rstrip() for ln in text.split("\n")]
        return "\n".join(ln for ln in lines if ln.strip())

    # -- connection ------------------------------------------------------
    def connect(self) -> str:
        self.close()
        try:
            self.sock = socket.create_connection((HOST, PORT), timeout=5)
        except OSError as e:
            self.sock = None
            raise ConnectionError(
                f"Keine Verbindung zu grandMA2 auf {HOST}:{PORT} ({e}). "
                "Läuft onPC und ist Setup -> Console -> Global Settings -> "
                "Telnet 'Login Enabled' aktiv?") from e
        try:
            banner = self._read(timeout=3, idle=0.5)
        except ConnectionError:
            banner = "disabled"
        if "disabled" in banner.lower():
            self.close()
            raise ConnectionError(
                "grandMA2 meldet 'Remote commandline disabled'. In onPC: Setup -> "
                "Console -> Global Settings -> Telnet auf 'Login Enabled' stellen.")
        self.sock.sendall(f'Login "{USER}" "{PASSWORD}"\r\n'.encode())
        login = self._read(timeout=5, idle=0.6)
        return self._clean(banner + "\n" + login)

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def command(self, cmd: str, timeout: float = 10, idle: float = 0.6) -> str:
        cmd = cmd.replace("\r", " ").replace("\n", " ").strip()
        with self.lock:
            for attempt in range(2):
                try:
                    if self.sock is None:
                        self.connect()
                    # drain anything left over from earlier asynchronous output
                    self.sock.setblocking(False)
                    try:
                        while self.sock.recv(65536):
                            pass
                    except (BlockingIOError, socket.timeout):
                        pass
                    self.sock.setblocking(True)
                    self.sock.sendall((cmd + "\r\n").encode("utf-8"))
                    # "A; B; C" echoes one "Executing" per command (ignore ';' inside quotes)
                    expect = re.sub(r'"[^"]*"', "", cmd).count(";") + 1
                    return self._clean(self._read(timeout, idle, expect))
                except (ConnectionError, OSError):
                    self.close()
                    if attempt == 1:
                        raise
        return ""


ma = TelnetClient()

INSTRUCTIONS = r"""
Steuert grandMA2 (onPC) über die Telnet-Kommandozeile. Alle Befehle sind normale
grandMA2-Kommandozeilenbefehle (wie in der Command Line der Konsole).

Arbeitsweise:
1. Erst erkunden: `List Fixture`, `List Attribute`, `List Group`, `List Sequence`,
   `List Effect`, `List Executor 1.1`. Patch prüfen, bevor programmiert wird.
2. Kein Patch vorhanden? `ma_find_fixture_type` + `ma_patch`.
3. Song -> Lightshow: `song_analyze` -> Cues entwerfen -> `ma_build_cuelist` -> `show_play`.
   (Ausführlicher Workflow: Skill "grandma2-lightshow".)
4. Komplexe Objekte lesen: `ma_export` (XML); verändert zurück per `ma_import_xml`.
5. Massenoperationen/Logik: `ma_lua` (gma.cmd, gma.show.getobj, gma.feedback).

Getestete Syntax (grandMA2 3.9):
- Mehrere Befehle in einer Zeile mit `;` trennen.
- Auswahl: `Fixture 1 Thru 10`, `Group 3`, `Fixture 1 + 3 + 5`, `Fixture 1 Thru 8 - 4`
- Dimmer: `At 100`, `At 0`, `Fixture 1 Thru 4 At 50`
- Attribute: `Attribute "ColorRGB1" At 100` (R), `ColorRGB2` (G), `ColorRGB3` (B), `Pan`, `Tilt`
  -> exakte Namen aus `List Attribute`.
- Effekte: `Import "predefined" At Effect 1 /nc` lädt 31 Standard-Effekte (1 Dimmer Sin,
  2 Dimmer Chase, 3 Dimmer PWM, 4 Dimmer Random, 5 Dimmer Even/Odd, 7 RGB Rainbow, 9 RGB Chase,
  10 RGB Blue White, 11 RGB Even/Odd, 12 RGB Random, 19 Tilt Sin, 20 Pan Sin, 23 P/T Circle, ...).
  Anwenden: `Fixture 1 Thru 8; At Effect 9`. Tempo: `PresetType "Color"; EffectBPM 128`
  (EffectBPM wirkt auf den aktiven PresetType: "Dimmer", "Position", "Color", ...).
- Cues: `Store Sequence 5 Cue 1 /o`, `Label Sequence 5 Cue 2 "Chorus"`,
  `Assign Sequence 5 Cue 2 /fade=1.5`, `Assign Sequence 5 Cue 2 /trig=time /trigtime=2.5`
  (Time-Trigger = Sekunden nach dem vorherigen Cue).
- Sequenz: `Label Sequence 5 "Song"`, `Assign Sequence 5 /track=off`, `Assign Sequence 5 At Executor 1.1`
- Gruppen: `Fixture 1 Thru 8; Store Group 10 /o; Label Group 10 "Wash"`
- Wiedergabe: `Go+ Executor 1.1`, `Off Executor 1.1`, `ClearAll`
- Optionen: `/o` (overwrite), `/nc` (noconfirm), `/merge`.

Vorsicht: `Delete`, `NewShow`, `LoadShow`, `Shutdown`, `Reboot` nur nach Rückfrage beim Nutzer.
Speichern mit `SaveShow` nicht vergessen, wenn der Nutzer das möchte.
"""

mcp = FastMCP("grandma2", instructions=INSTRUCTIONS)


@mcp.tool()
def ma_command(command: str, timeout: float = 10) -> str:
    """Führt einen grandMA2-Kommandozeilenbefehl aus und gibt die Telnet-Ausgabe zurück.
    Beispiele: 'List Sequence', 'Fixture 1 Thru 10 At 100', 'Store Cue 1 Sequence 5 /merge'.
    Mehrere Befehle in einer Zeile mit ';' trennen ist erlaubt."""
    out = ma.command(command, timeout=timeout)
    return out or "(keine Ausgabe)"


@mcp.tool()
def ma_commands(commands: list[str], stop_on_error: bool = True) -> str:
    """Führt eine Liste von grandMA2-Befehlen nacheinander aus (z.B. um eine ganze
    Cue-Liste zu programmieren). Gibt die Ausgabe je Befehl zurück."""
    results = []
    for cmd in commands:
        out = ma.command(cmd)
        results.append(f"> {cmd}\n{out}")
        if stop_on_error and re.search(r"\b(Error|Illegal|UNKNOWN COMMAND|NOT EXECUTED)\b", out, re.I):
            results.append("-- abgebrochen wegen Fehler --")
            break
    return "\n\n".join(results)


@mcp.tool()
def ma_connect() -> str:
    """(Neu-)Verbindung zu grandMA2 aufbauen und einloggen. Zeigt Banner/Login-Antwort."""
    with ma.lock:
        return ma.connect() or "Verbunden."


@mcp.tool()
def ma_status() -> str:
    """Zeigt Verbindungsparameter, Datenverzeichnis und vorhandene Shows."""
    shows = []
    if DATA_DIR and (DATA_DIR / "shows").exists():
        shows = sorted(p.name for p in (DATA_DIR / "shows").glob("*.show*"))
    return (f"Host: {HOST}:{PORT}  User: {USER}\n"
            f"Verbunden: {ma.sock is not None}\n"
            f"Datenordner: {DATA_DIR}\n"
            f"Shows: {', '.join(shows) or '(keine)'}")


def _importexport_dir() -> Path:
    if not DATA_DIR:
        raise RuntimeError("grandMA2-Datenordner nicht gefunden; GMA2_DATA_DIR setzen.")
    d = DATA_DIR / "importexport"
    d.mkdir(parents=True, exist_ok=True)
    return d


@mcp.tool()
def ma_export(object: str, filename: str = "mcp_export") -> str:
    """Exportiert ein Objekt (z.B. 'Sequence 1', 'Effect 3', 'Group 1 Thru 5', 'Preset 4.1')
    als XML in den importexport-Ordner und gibt das XML zurück. Ideal um Struktur zu lernen."""
    filename = re.sub(r"[^\w\-]", "_", filename)
    target = _importexport_dir() / f"{filename}.xml"
    if target.exists():
        target.unlink()
    out = ma.command(f'Export {object} "{filename}" /overwrite /noconfirm', timeout=15)
    for _ in range(30):
        if target.exists():
            break
        time.sleep(0.1)
    if not target.exists():
        return f"Export fehlgeschlagen. Ausgabe:\n{out}"
    xml = target.read_text(encoding="utf-8-sig", errors="replace")
    if len(xml) > 60000:
        xml = xml[:60000] + f"\n... (gekürzt, ganze Datei: {target})"
    return xml


@mcp.tool()
def ma_import_xml(xml: str, target: str, filename: str = "mcp_import") -> str:
    """Schreibt grandMA2-XML in den importexport-Ordner und importiert es.
    target ist das Zielobjekt, z.B. 'Sequence 10', 'Effect 20', 'Macro 5', 'Group 7'.
    Tipp: erst ein ähnliches Objekt mit ma_export ansehen und dessen Format nachbauen."""
    filename = re.sub(r"[^\w\-]", "_", filename)
    path = _importexport_dir() / f"{filename}.xml"
    path.write_text(xml, encoding="utf-8")
    return ma.command(f'Import "{filename}" At {target} /noconfirm', timeout=20)


@mcp.tool()
def ma_lua(code: str, timeout: float = 20) -> str:
    """Führt Lua-Code im grandMA2-Plugin-Kontext aus (gma.cmd(...), gma.show.getobj, ...).
    Ausgaben mit gma.feedback("...") erscheinen in der Rückgabe; gma.echo geht in den System Monitor."""
    if not DATA_DIR:
        raise RuntimeError("grandMA2-Datenordner nicht gefunden; GMA2_DATA_DIR setzen.")
    path = DATA_DIR / "plugins" / "_mcp_tmp.lua"
    path.write_text(code, encoding="utf-8")
    lua_path = str(path).replace("\\", "/")
    wrapper = (f"local ok,err=pcall(dofile,'{lua_path}') "
               f"if not ok then gma.feedback('LUA ERROR: '..tostring(err)) end")
    return ma.command(f'Lua "{wrapper}"', timeout=timeout, idle=1.0) or "(keine Ausgabe)"


@mcp.tool()
def ma_list_files(folder: str = "importexport") -> str:
    """Listet Dateien in einem grandMA2-Datenunterordner (importexport, shows, macros, plugins, effects, ...)."""
    if not DATA_DIR:
        return "Datenordner nicht gefunden."
    d = DATA_DIR / folder
    if not d.is_dir():
        return f"{d} existiert nicht."
    return "\n".join(sorted(p.name for p in d.iterdir())) or "(leer)"


# -- patch ------------------------------------------------------------------

ERROR_RE = re.compile(r"\b(Error|Illegal|UNKNOWN COMMAND|NOT EXECUTED|CANNOT)\b", re.I)


@mcp.tool()
def ma_find_fixture_type(query: str, limit: int = 40) -> str:
    """Sucht Fixture-Typen in der grandMA2-Library (Dateiname = Hersteller@Gerät@Modus).
    Mehrere Suchwörter mit Leerzeichen, z.B. 'stairville par', 'generic rgbw', 'robe spot'.
    Den Namen ohne Endung an ma_patch übergeben."""
    if not DATA_DIR:
        return "Datenordner nicht gefunden."
    words = query.lower().split()
    hits = [p.stem for p in (DATA_DIR / "library").iterdir()
            if all(w in p.name.lower() for w in words)]
    hits.sort()
    more = f"\n... und {len(hits) - limit} weitere" if len(hits) > limit else ""
    return "\n".join(hits[:limit]) + more if hits else "Nichts gefunden."


def _in_setup(path: str, cmds: str, timeout: float = 15) -> str:
    """Run commands inside EditSetup/<path>. 'cd /' only works as a command of its
    own (inside a ';' chain the '/' is parsed as an option), so it is sent separately."""
    ma.command("cd /")
    try:
        cd = "; ".join(f"cd {p}" for p in ["EditSetup", *path.split("/")] if p)
        return ma.command(f"{cd}; {cmds}", timeout=timeout)
    finally:
        ma.command("cd /")


def _fixture_types() -> dict[str, tuple[int, int]]:
    """Map of fixture type long name -> (number, DMX footprint) in the show."""
    out = _in_setup("FixtureTypes", "List")
    types = {}
    for line in out.splitlines():
        m = re.match(r"FixtureType\s+(\d+)\s+\d+\s+(.+?)\s{2,}.*?\s(\d+)\s+\d+\s", line)
        if m:
            types[m.group(2).strip()] = (int(m.group(1)), int(m.group(3)))
    return types


@mcp.tool()
def ma_patch(fixture_type: str, count: int, first_fixture_id: int, universe: int = 1,
             first_address: int = 1, name: str = "", layer_name: str = "",
             address_step: int = 0) -> str:
    """Patcht `count` Geräte in einen neuen Layer.
    fixture_type: Library-Name aus ma_find_fixture_type (z.B. 'generic@led_-_rgbw@8_bit')
                  oder Nummer eines schon importierten Fixture-Typs (z.B. '3').
    Fixture-IDs ab first_fixture_id, DMX ab universe.first_address, Abstand = Footprint
    (oder address_step). name: Namenspräfix, z.B. 'Par' -> 'Par 1', 'Par 2', ..."""
    log = []
    if fixture_type.isdigit():
        type_no = int(fixture_type)
        footprint = next((fp for no, fp in _fixture_types().values() if no == type_no), 0)
    else:
        before = _fixture_types()
        nums = [no for no, _ in before.values()]
        slot = max(nums, default=0) + 1
        out = _in_setup("FixtureTypes", f'Import "{fixture_type}" At {slot}', timeout=30)
        log.append(out)
        if "imported" not in out:
            return "Fixture-Typ konnte nicht importiert werden:\n" + out
        after = _fixture_types()
        type_no, footprint = next(v for v in after.values() if v[0] == slot)
    step = address_step or footprint or 1

    layers = _in_setup("Layers", "List")
    used = [int(n) for n in re.findall(r"^Layer\s+(\d+)", layers, re.M)]
    layer = max(used, default=0) + 1
    layer_label = layer_name or name or f"Layer {layer}"
    log.append(_in_setup("Layers", f'Store {layer}; Assign {layer} /name="{layer_label}"'))

    cmds = [f"Store 1 Thru {count}", f"Assign FixtureType {type_no} At 1 Thru {count}"]
    for i in range(count):
        fid = first_fixture_id + i
        addr = first_address + i * step
        uni, addr = universe + (addr - 1) // 512, (addr - 1) % 512 + 1
        # options must be assigned one per command, combined options are ignored
        cmds.append(f"Assign {i + 1} /fixid={fid}")
        cmds.append(f'Assign {i + 1} /patch="{uni}.{addr}"')
        if name:
            cmds.append(f'Assign {i + 1} /name="{name} {i + 1}"')
    for chunk in range(0, len(cmds), 20):
        part = "; ".join(cmds[chunk:chunk + 20])
        log.append(_in_setup(f"Layers/{layer}", part, timeout=30))

    errors = [ln for ln in "\n".join(log).splitlines() if ERROR_RE.search(ln)]
    summary = ma.command(f"List Fixture {first_fixture_id} Thru {first_fixture_id + count - 1}")
    return (f"Layer {layer} '{layer_label}', FixtureType {type_no}, Footprint {footprint}.\n"
            + ("FEHLER:\n" + "\n".join(errors) + "\n" if errors else "") + summary)


# -- song analysis & show building ------------------------------------------

_analysis_cache: dict[str, dict] = {}


def _shows_file() -> Path:
    return _importexport_dir() / "mcp_shows.json"


def _load_shows() -> dict:
    try:
        return json.loads(_shows_file().read_text(encoding="utf-8"))
    except (OSError, ValueError, RuntimeError):
        return {}


@mcp.tool()
def song_analyze(path: str, sections: int = 0, include_beats: bool = False) -> str:
    """Analysiert einen Song (mp3/wav/flac/ogg): BPM, Beat-Raster, Takte mit Energie,
    Abschnitte (Intro/Strophe/Drop... als Energie-Level) und Akzente (Drops/Lifts).
    Zeiten in Sekunden ab Songbeginn. sections=0 wählt die Anzahl automatisch.
    include_beats=True liefert zusätzlich alle Beat-Zeiten (für Chases auf jeden Beat)."""
    import audio

    key = f"{Path(path).resolve()}|{sections}"
    if key not in _analysis_cache:
        _analysis_cache[key] = audio.analyze(path, sections or None)
    r = dict(_analysis_cache[key])
    bars = r.pop("bars")
    beats = r.pop("beat_times")
    lines = [json.dumps({k: v for k, v in r.items() if k not in ("sections", "accents")},
                        ensure_ascii=False)]
    lines.append("SECTIONS (start-end s, bars, energy 0-1, bass, level, change):")
    for s in r["sections"]:
        lines.append(f"  {s['section']:>2}: {s['start']:7.2f}-{s['end']:7.2f}  {s['bars']:>3} bars  "
                     f"E={s['energy']:.2f} B={s['bass']:.2f} {s['level']:<4} {s.get('change', '')}")
    lines.append("ACCENTS: " + ", ".join(f"{a['t']:.2f}s bar {a['bar']} {a['type']}"
                                         for a in r["accents"]) if r["accents"] else "ACCENTS: -")
    lines.append("BARS (bar: start s / energy / bass / brightness):")
    lines.append("  " + "  ".join(f"{b['bar']}:{b['t']:.2f}/{b['energy']:.2f}/{b['bass']:.2f}/{b['bright']:.2f}"
                                  for b in bars))
    if include_beats:
        lines.append("BEATS: " + " ".join(f"{t:.3f}" for t in beats))
    return "\n".join(lines)


@mcp.tool()
def ma_build_cuelist(sequence: int, cues: list[dict], name: str = "", executor: str = "1.1",
                     song_path: str = "", replace: bool = False, tracking: bool = False) -> str:
    """Baut eine komplette, zeitgesteuerte Cue-Liste (z.B. eine Lightshow zu einem Song).

    cues: Liste von {"time": Sekunden ab Songstart, "commands": ["Fixture 1 Thru 8 At 100", ...]
          oder ein String mit ';', "label": "Drop", "fade": 0.5}
    Jeder Cue: ClearAll -> commands -> Store. Cue 1 startet mit Go, alle weiteren bekommen
    automatisch Time-Trigger, so dass die Show nach einem Go synchron zum Song läuft.
    tracking=False (empfohlen): jeder Cue enthält nur das, was in seinen commands steht.
    replace=True löscht eine bestehende Sequenz dieser Nummer vorher (sonst Abbruch).
    song_path wird gemerkt, damit show_play den Song abspielen und Go synchron auslösen kann."""
    if not cues:
        return "Keine Cues übergeben."
    cues = sorted(cues, key=lambda c: float(c["time"]))
    exists = "NO OBJECTS" not in ma.command(f"List Sequence {sequence}")
    if exists and not replace:
        return f"Sequence {sequence} existiert schon. replace=True setzen oder andere Nummer wählen."
    if exists:
        ma.command(f"Delete Sequence {sequence} /nc")

    errors = []
    prev_t = round(float(cues[0]["time"]), 2)
    for i, cue in enumerate(cues, start=1):
        t = round(float(cue["time"]), 2)
        cmds = cue.get("commands", [])
        if isinstance(cmds, str):
            cmds = [c for c in cmds.split(";")]
        cmds = [c.strip() for c in cmds if c.strip()]
        line = ["ClearAll", *cmds, f"Store Sequence {sequence} Cue {i} /o"]
        opts = []
        if i > 1:
            # Time trigger = seconds after the previous cue; computed from rounded
            # absolute times so rounding never accumulates into drift
            opts.append(f"/trig=time /trigtime={max(t - prev_t, 0.0):.2f}")
        if cue.get("fade") is not None:
            opts.append(f"/fade={float(cue['fade']):.2f}")
        if opts:
            line.append(f"Assign Sequence {sequence} Cue {i} " + " ".join(opts))
        if cue.get("label"):
            line.append(f'Label Sequence {sequence} Cue {i} "{str(cue["label"]).replace(chr(34), "")}"')
        out = ma.command("; ".join(line), timeout=30)
        for ln in out.splitlines():
            if ERROR_RE.search(ln):
                errors.append(f"Cue {i} ({t:.2f}s): {ln}")
        prev_t = t
    tail = ["ClearAll"]
    if name:
        tail.append(f'Label Sequence {sequence} "{name}"')
    if not tracking:
        tail.append(f"Assign Sequence {sequence} /track=off")
    if executor:
        tail.append(f"Assign Sequence {sequence} At Executor {executor}")
    out = ma.command("; ".join(tail))
    errors += [ln for ln in out.splitlines() if ERROR_RE.search(ln)]

    shows = _load_shows()
    shows[str(sequence)] = {"name": name, "executor": executor, "song": song_path,
                            "first_cue_time": float(cues[0]["time"]), "cues": len(cues),
                            "length": float(cues[-1]["time"])}
    _shows_file().write_text(json.dumps(shows, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = (f"Sequence {sequence} '{name}' mit {len(cues)} Cues gebaut "
               f"({cues[0]['time']:.2f}s bis {cues[-1]['time']:.2f}s), Executor {executor or '-'}.")
    if errors:
        summary += "\nFEHLER:\n" + "\n".join(errors[:40])
    return summary


_player = None


@mcp.tool()
def show_play(sequence: int, start_at: float = 0.0, song_path: str = "") -> str:
    """Spielt den Song zur Sequenz über die Lautsprecher dieses PCs ab und löst den
    Executor genau zur Zeit des ersten Cues aus (Go+). start_at überspringt die ersten
    Sekunden des Songs (dann wird per Goto zum passenden Cue gesprungen)."""
    global _player
    import audio

    info = _load_shows().get(str(sequence), {})
    song = song_path or info.get("song")
    executor = info.get("executor") or "1.1"
    if not song or not Path(song).exists():
        return "Kein Song bekannt/gefunden. song_path angeben."
    first = float(info.get("first_cue_time", 0.0))
    ma.command(f"Off Executor {executor}")
    events = []
    if start_at <= first:
        events.append((first, lambda: ma.command(f"Go+ Executor {executor}", timeout=2, idle=0.05)))
    else:
        # find the cue playing at start_at from the sequence's trigger times
        out = ma.command(f"List Cue Sequence {sequence}")
        t, cue_at = first, 1
        for m in re.finditer(r"^Cue\s+\d+\s+([\d.]+)\s+\*?\s*(Go|Time)\s*([\d.]*)", out, re.M):
            if m.group(2) == "Time" and m.group(3):
                t += float(m.group(3))
            if t <= start_at:
                cue_at = m.group(1)
        events.append((start_at, lambda: ma.command(
            f"Goto Executor {executor} Cue {cue_at}", timeout=2, idle=0.05)))
    _player = _player or audio.Player()
    _player.play(song, events, start=start_at)
    return f"Spiele '{Path(song).name}' ab {start_at:.1f}s, Go auf Executor {executor} bei {max(first, start_at):.2f}s."


@mcp.tool()
def show_status(sequence: int) -> str:
    """Zeigt Song-Position und aktuellen Cue des Executors der Sequenz."""
    info = _load_shows().get(str(sequence), {})
    executor = info.get("executor") or "1.1"
    out = ma_lua(f'gma.cmd("Select Executor {executor}") '
                 'gma.feedback("CUE "..tostring(gma.show.getvar("SELECTEDEXECCUE")))')
    m = re.search(r"CUE (\S+)", out)
    pos = _player.position() if _player else None
    return (f"Song: {'%.2fs' % pos if pos is not None else 'gestoppt'}, "
            f"Executor {executor} Cue: {m.group(1) if m else '?'}")


@mcp.tool()
def show_stop(sequence: int = 0) -> str:
    """Stoppt die Song-Wiedergabe und schaltet den Executor der Sequenz aus."""
    if _player:
        _player.stop()
    info = _load_shows().get(str(sequence), {}) if sequence else {}
    executor = info.get("executor")
    if executor:
        ma.command(f"Off Executor {executor}")
    return "Gestoppt."


if __name__ == "__main__":
    mcp.run()
