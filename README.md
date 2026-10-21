# grandMA2 MCP für Claude Code

Steuert **grandMA2 onPC** (oder eine grandMA2-Konsole im Netzwerk) aus **Claude Code** heraus –
inklusive automatischer **Lightshow zu einem Song**: Claude analysiert die Musik (BPM, Beats,
Abschnitte, Drops), entwirft passende Looks und programmiert eine zeitgesteuerte Cue-Liste,
die synchron zum Song läuft.

> *English summary:* MCP server that connects Claude Code to grandMA2 via Telnet. Patch
> fixtures, send any command, import/export XML, run Lua, analyse a song and build a
> beat-synced cue list. Windows install: `powershell -ExecutionPolicy Bypass -File install.ps1`.

---

## Was kann es?

| Tool | Zweck |
|---|---|
| `ma_command`, `ma_commands` | Beliebige grandMA2-Befehle ausführen (`List Fixture`, `Fixture 1 Thru 8 At 100`, …) |
| `ma_find_fixture_type`, `ma_patch` | Geräte in der MA-Library suchen und patchen |
| `song_analyze` | Song analysieren: BPM, Beat-Raster, Takte, Abschnitte, Energie, Drops |
| `ma_build_cuelist` | Komplette Cue-Liste bauen, jeder Cue mit Zeit-Trigger passend zum Song |
| `show_play`, `show_status`, `show_stop` | Song am PC abspielen und den Executor genau synchron starten |
| `ma_export`, `ma_import_xml` | Objekte (Sequenzen, Effekte, …) als XML lesen/schreiben |
| `ma_lua` | Lua-Code im grandMA2-Plugin-Kontext ausführen |
| `ma_status`, `ma_connect`, `ma_list_files` | Verbindung und Dateien prüfen |

Dazu kommt der Skill **`grandma2-lightshow`**, der Claude den Ablauf und Gestaltungsregeln für
Song→Lightshow beibringt (Intensität folgt Energie, Farben pro Abschnitt, Effekte im Song-Tempo,
Akzente auf Drops …).

## Voraussetzungen

- Windows 10/11
- [grandMA2 onPC](https://www.malighting.com/downloads/products/grandma2/) (getestet mit 3.9.61)
- [Python 3.10+](https://www.python.org/downloads/) (bei der Installation „Add python.exe to PATH“ anhaken)
- [Claude Code](https://claude.com/claude-code)

## Installation

```powershell
git clone https://github.com/<DEIN-NAME>/grandma2-mcp.git
cd grandma2-mcp
powershell -ExecutionPolicy Bypass -File install.ps1
```

Oder einfach Claude Code im geklonten Ordner sagen: **„Installiere dieses Repo“** – die Anleitung
für Claude steht in `CLAUDE.md`.

Das Skript
1. installiert die Python-Pakete (`mcp`, `librosa`, `soundfile`, `sounddevice`),
2. registriert den MCP-Server `grandma2` in Claude Code (für alle Projekte),
3. installiert den Skill `grandma2-lightshow` nach `~/.claude/skills`,
4. kopiert die Show `claude_base` (leer, Telnet bereits aktiviert) in den onPC-Showordner.

Optionen, z.B. für eine Konsole im Netzwerk:
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -GmaHost 192.168.0.50 -GmaPassword meinpasswort
```

### In grandMA2 einmalig

Telnet muss erlaubt sein. Entweder die Show **`claude_base`** laden (Backup → Load Show) oder in der
eigenen Show: **Setup → Console → Global Settings → Telnet → „Login Enabled“** und speichern.

Danach **eine neue Claude-Code-Sitzung starten**, damit die Tools geladen werden.

## Benutzung

Einfach in Claude Code schreiben, zum Beispiel:

- „Patch mir 8 Stairville LED Pars auf Universum 1 ab Adresse 1.“
- „Mach mir eine Lightshow zu `C:\Musik\song.mp3` auf Executor 1.1.“
- „Spiel die Show ab Sekunde 60 ab.“
- „Mach den Refrain röter und die Strophe ruhiger.“

Ablauf einer Song-Show:
1. `song_analyze` → BPM, Abschnitte, Drops
2. Claude entwirft pro Abschnitt einen Look und Akzente
3. `ma_build_cuelist` → Sequenz mit Go auf Cue 1 und Zeit-Triggern für alle weiteren Cues
4. `show_play` → Song läuft am PC, Go wird automatisch im richtigen Moment ausgelöst.
   Auf einer echten Konsole: Song starten und zum ersten Cue Go drücken.

Unterstützte Audioformate: WAV, MP3, FLAC, OGG.

## Konfiguration (Umgebungsvariablen)

| Variable | Standard | Bedeutung |
|---|---|---|
| `GMA2_HOST` | `127.0.0.1` | IP von onPC/Konsole |
| `GMA2_PORT` | `30000` | Telnet-Port |
| `GMA2_USER` | `administrator` | MA-Benutzer |
| `GMA2_PASSWORD` | `admin` | Passwort |
| `GMA2_DATA_DIR` | neuester `C:\ProgramData\MA Lighting Technologies\grandma\gma2_V_*` | onPC-Datenordner (für Import/Export, Lua) |

Werden über `install.ps1 -GmaHost … -GmaPassword …` gesetzt oder manuell:
```
claude mcp add --scope user grandma2 -e GMA2_HOST=192.168.0.50 -- python C:\pfad\grandma2-mcp\server.py
```

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| „Keine Verbindung zu grandMA2“ | onPC starten; Firewall; bei Konsole IP/Port prüfen |
| „Remote commandline disabled“ | Telnet „Login Enabled“ in den Global Settings (siehe oben) |
| Tools fehlen in Claude | Neue Sitzung starten; `claude mcp list` prüfen |
| Login schlägt fehl | `GMA2_USER`/`GMA2_PASSWORD` setzen |
| Show läuft nicht synchron | Mit `examples/make_test_song.py` Testsong erzeugen und `song_analyze` prüfen |

## Projektstruktur

```
server.py                        MCP-Server (Telnet, Tools)
audio.py                         Song-Analyse und synchrone Wiedergabe
skills/grandma2-lightshow/       Claude-Skill für Song → Lightshow
shows/claude_base.show.gz        Leere Show mit aktiviertem Telnet (grandMA2 3.9.61)
examples/make_test_song.py       Testsong mit bekannter Struktur (128 BPM)
install.ps1                      Installer für Windows
CLAUDE.md                        Hinweise für Claude (Installation, getestete MA-Syntax)
```

## Lizenz

MIT – siehe [LICENSE](LICENSE). grandMA2 ist eine Marke der MA Lighting Technology GmbH;
dieses Projekt ist nicht offiziell mit MA Lighting verbunden.
