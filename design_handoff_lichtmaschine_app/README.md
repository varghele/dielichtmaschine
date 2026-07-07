# Handoff: Die Lichtmaschine · Qt6 Desktop App (North Star, Glutorange)

## Overview
"Die Lichtmaschine" (dielichtmaschine.de) ist eine Open-Source-Desktop-App zum Erstellen von Lichtshows:
visuelles Authoring auf einer beat-synchronen Timeline, 3D-Preview mit volumetrischen Beams, automatische
Show-Generierung aus Audio-Analyse, Live-Betrieb ueber ArtNet/DMX, Export zu Lichtsteuersoftware (u. a. QLC+ .qxw).
Ziel-Plattformen: Windows, Linux, Raspberry Pi (Pi = headless, nur Show-Playback, keine Visualisierung).
Aktueller Stack: Python + Qt (PyQt), Stack ist aber NICHT fest - waehle das im Ziel-Repo etablierte Framework.
Dieses Paket ist der North Star fuer einen kompletten Redesign der bestehenden App (QLCplusShowCreator).

## About the Design Files
Die HTML-Dateien in diesem Paket sind **Design-Referenzen** (in HTML gebaute Mockups), kein Produktionscode.
Aufgabe: diese Designs in der Zielumgebung des Codebases nachbauen (Qt6/QSS, QGraphicsScene etc.),
nicht das HTML uebernehmen. `Lichtmaschine App North Star.dc.html` + `support.js` im Browser oeffnen, um alles zu sehen.
Die Seite ist ein Canvas mit nummerierten Options-Karten (1a, 3a, 6c ...); Referenzen unten nutzen diese IDs.

## Fidelity
**High-fidelity.** Farben, Typografie, Abstaende und Copy sind final gemeint. Pixel-genau nachbauen,
mit den Konventionen des Ziel-Frameworks (z. B. QSS statt Inline-Styles, echte QMenus statt Icon-Attrappen).

## Entschieden vs. offen
- Akzent: **Glutorange #F0562E** - ENTSCHIEDEN (finale Wahl, Messinggold verworfen)
- Live-Screen: ZWEI Varianten enthalten (3a Konsolen-Layout mit Gruppen-Busk-Panels, 3b Select->Palette-Philosophie). Entscheidung offen - beide bauen sich um dieselben Konzepte; 3a ist der selbsterklaerende Default fuer Einsteiger.
- Slogan: DE "ES WERDE LICHT" / EN "LET THERE BE LIGHT"
- Keine Emdashes in UI-Copy; Trennzeichen ist " · ".

## Design Tokens

### Farben (Dark Theme, Default)
| Token | Wert |
|---|---|
| window | #141416 |
| panel | #1E1E1E |
| raised | #252526 |
| border | #3A3A3A |
| text | #F4F1EA (warmes Off-White, nie #FFF) |
| text-secondary / Stahl | #8D9299 |
| text-tertiary | #5C6068 |
| Akzent (Flaeche + Linie) | #F0562E, Text darauf #141416 |
| Akzent-Tint (Flaechen) | rgba(240,86,46,0.10-0.18) |

### Farben (Light Theme)
window #ECE9E2 · panel #F4F1EA · raised #FAF8F3 · border #C9C4B8 · text #141416 · text-2nd #5C6068 ·
Akzent-Flaechen bleiben #F0562E mit dunklem Text; Akzent als Linie/Text wird #C33E1C.
Theme-Wechsel: ein Token-Dict -> QSS-Template -> app.setStyleSheet() (Karte 8a).

### Funktionsfarben (nie fuer Brand-Akzente verwenden)
Erfolg #4CAF50 · Info #2196F3 · Warnung #FF9800 · Destruktiv/Fehler #F44336 (DBO-Button, Kill).

### Gruppenfarben (Dark / Light)
Amber #D9A441/#B07F24 · Cyan #4ECBD4/#2A9AA3 · Magenta #C95FD0/#A53FAE · Gruen #6F9E4C/#557D36 · Stahl #8D9299/#5C6068.
Verwendung: 3px Border-links an Lane-Headern/Zeilen, Block-Rahmen + Tint (~0.16-0.22 Alpha), Fader-Top-Border.

### Typografie (alle Google Fonts, shippen mit der App)
- Display/Headlines/Tab-Labels: **Barlow Condensed** 600-800, ALL-CAPS, letter-spacing 0.04-0.12em
- UI/Fliesstext: **Barlow** 400-600
- Numerik/Readouts/Labels (BPM, DMX, Zeiten, Micro-Labels): **IBM Plex Mono** 400-600, Micro-Labels letter-spacing 0.1-0.2em
- Skala im Mock (1920x1080): Micro-Labels 8-10px mono · UI-Text 12-14px · Panel-Titel 15-18px cond · Screen-Titel 22px cond · Hero 44-72px cond

### Sonstige Werte
- Border-Radius: 0 ueberall (harte Kanten, Datasheet-Aesthetik). Keine Schatten. Keine Gradients ausser Funktionsflaechen (Colour-Swatches, Region-Tints).
- Grid/Schema-Motive: feines Engineering-Grid (rgba(141,146,153,0.04-0.07), 24-48px Zellen), Registrierungs-Kreuze in Ecken, 1px-Trennlinien.

## Brand
- Logo-Glyph: "Rotor im Registrierungsring" - segmentierter Kreis (8 Segmente, stroke-dasharray) + duenner Aussenring + Akzent-Zentrum. 16px-Variante ohne Aussenring. Dateien: assets/brand/.
- Wortmarke: DIE LICHTMASCHINE, Barlow Condensed 800 caps, Glyph links daneben.
- Animation (Screensaver/Loader): innerer Rotor dreht (10-16s/U), Aussenring gegenlaeufig langsamer (24-40s/U), Zentrum pulsiert.

## App-Struktur
Hauptnavigation (Tabs, 48px-Topbar): **SETUP · SHOW · AUTO · LIVE**
Topbar: Glyph+Wortmarke links, Tabs, rechts: 6 Icon-Buttons (30x30, 1px Border; Speichern, Export, Morphen, Audio, Einstellungen, Menue "alles Weitere" als QMenu) + Dateiname + Output-Status-Chip (gruener Punkt, "OUTPUT LIVE · U1 U2 · 44 Hz").
Icons: 16x16 Line-SVGs, stroke 1.5, currentColor (im HTML inline, fuer Qt als Dateien extrahieren oder QIcon aus SVG-Text).
Statusbar unten: 26px, mono 10px, kontextuelle Hinweise + Shortcut.

### Screens (Karten-IDs im HTML)
1. **Home (1a)**: Hero mit Logo, Slogan, letzte Shows, Quick-Actions.
2. **Setup · Fixtures (1c)**: Tabelle mit Gruppen-Tints pro Zeile, Inspector rechts.
3. **Setup · Universes (1d)**: Patch-Uebersicht.
4. **Setup · Stage (5a)**: 2D-Buehnenplan, QGraphicsScene. Ebenen-System: aktive Ebene waehlbar (BUEHNE 0.8m / RISER +0.4m / FLOWN 4.0m / + EBENE / DEFINIEREN); nur aktive Ebene selektier-/beweglich, andere 25% Opacity + gesperrt (QGraphicsItemGroup, setOpacity + setEnabled(false)). Fixtures haben ein EBENE-Feld im Inspector. Items/Fixtures als SVG-Symbole (assets/stageplot/), Rahmenfarbe = Gruppe, gestrichelt = nicht-aktive Ebene. Raster 0.5m. Truss-Bibliothek (gerade/Tower/Ecke/Kreis), Fixtures docken an Trusse.
5. **Show · Structure (1e)**: Song-Teile als farbige Karten (Gruppenfarbe oben als 3px-Bar + Tint), Master-Grid mit Region-Baendern, "SHOW AUS AUDIO GENERIEREN" Einstiegspunkt.
6. **Show · Timeline (4a)**: REAPER-artig. Regions-Zeile (INTRO/VERSE/CHORUS farbig), Grid-Umschalter (1/4, 1/2, 1 BAR, 2, 4) + SWING %, Lane pro Gruppe (128px), Lane-Header 260px mit 4 Sub-Zeilen-Labels DIM/COL/MOV/SPC (je 24px). Effekt-Block = Container ueber Takte mit 4 Sub-Lanes; JEDE Sub-Lane kann MEHRERE Bloecke halten (grid-snapped, 2px Gap). Overlap zweier Effekt-Bloecke: schraffierte Zone + Chip "OVERLAP: XFADE · 2 BARS" (Funktion waehlbar: XFADE/HTP/LTP). Playhead Akzent mit Zeit-Tag. Toolbar: Transport, BAR-Anzeige, Akzent-Button "SHOW AUS AUDIO GENERIEREN". 3D-Preview als kollabierbare rechte Pane mit POP-OUT (2. Monitor).
7. **Auto (1h)**: Auto-Modus (Audio-Analyse live), eigene Ansicht neben LIVE; hat ebenfalls 3D-Pane mit Pop-out.
8. **Autogen (1j)**: Show-Generierung aus Audiodatei, Parameter + Vorschau.
9. **Live 3a**: Konsolen-Anatomie: links Cue-Stack (GO gross, Akzent), Mitte Gruppen-Busk-Panels (pro Gruppe: Colour-Swatch-Reihe + FROM SHOW, Rudiment-Chips + RATE; Movers zusaetzlich POSITION-Presets und MOVE-Shapes mit SIZE/MIRROR; Zustand FOLLOWING SHOW vs MANUAL·BUSKING mit RELEASE), rechts Master-Fader GRAND/SUB + DBO (rot umrandet) + 3D-Pane, unten Playback-Fader-Bank (Seiten, FLASH-Buttons) + Riff-Grid. Busk-Logik: manuelle Eingriffe layern ueber der Show, RELEASE kehrt zur Timeline zurueck.
10. **Live 3b**: Select->Palette: SELECT-Zeile (Gruppen-Buttons, ALL, ODD/EVEN), FADE-Zeile (SNAP/0.5s/2s/4s/1 BAR/4 BARS), drei Pools QUADRATISCH (Colour 94x94, Position + Rudiments 104x104), Programmer-Statuszeile (REC->RIFF, BLIND, CLEAR), rechts ACTIVE PLAYBACKS (Kill je Zeile) + 3D-Pane.
11. **Screensaver (11a)**: Vollbild #0E0E10, animierter Rotor 220px, Wortmarke, grosse Uhr (mono 72px), Statuszeile (Pausenlicht, ArtNet aktiv, beliebige Taste beendet). Aktivierung: LIVE-Pause-Taste oder auto nach Idle.
12. **Morph-Wizard (6a)**: Dialog 1380px. Quelle->Ziel-Venue, Mapping-Zeilen pro Gruppe (AUTO/OFFEN/NEU + Anpassung wie "CHASE 4->6 KOEPFE GESPREIZT"), Optionen (Positionen skalieren, Farben beibehalten), Ergebnis = Kopie (show@venue.lms), Original unberuehrt. Fuer neue Ziel-Gruppen: LANES PATCHEN (einzelne Lanes anderer Gruppen erben, Live-Verknuepfung, Capability-Filter blockt inkompatible Lanes) / AUS RUDIMENTEN / LEER.
13. **Venue-Check (6b)**: Phase 2 des Morphs am FOH. 10-Punkte-Checkliste (Output/Patch, Identify, Dimmer, Blackout-Leckage, Weissabgleich, P/T-Kalibrierung mit Fine-Pad + Delta-Anzeige + OFFSET SPEICHERN wirkt auf ALLE Positions-Presets, Fokus/Zoom, Presets abfahren, Tilt-Limits, Probelauf). Ergebnisse persistieren ins Venue-Showfile. Druckversion: A4-Protokoll (7a, on-light).
14. **Patch-Matrix (6c, Experiment)**: Quelle(Zeilen, pro Lane aufklappbar) x Ziel(Spalten). Zustaende: aktiv/teilweise/moeglich/inkompatibel. Diagonale = 1:1-Mapping; additiv zu 6a. Mischregel: HTP fuer DIM, latest fuer COL/MOV.
15. **Patch-Flow (6d, bevorzugte Darstellung)**: Gleiches Datenmodell wie 6c, aber als Node-Verbindungen statt Matrix. Zwei Spalten (Quelle links, Ziel rechts), jede Zeile = Gruppe + CAPABILITY-Chip (INTENSITY/COLOUR/POSITION/BEAM). Kurven-Verbindungen: durchgezogen = 1:1-Mapping, gestrichelt = Lane-Patch, Labels auf der Linie (z. B. "LANE-PATCH · 4->2 GESPREIZT", Filter-Chip "NUR DIMMER-ANTEIL"). Kernregel: gepatcht wird Capability-auf-Capability - Verbindungen docken nur an gleicher Capability an, Inkompatibles ist gar nicht verbindbar. Mehrere Ausgaenge pro Quelle erlaubt. Qt: QGraphicsScene mit Bezier-Pfaden, Drag von Quell-Port zu Ziel-Port.

## Interactions & Behavior
- Nur aktive Ebene im Buehnenplan editierbar; Ebenenwechsel ueber Subnav.
- Timeline: Bloecke grid-snapped an aktueller Grid-Einstellung; Overlap-Funktion pro Ueberlappung waehlbar.
- Busk (3a): Panel-Eingriff setzt Gruppe auf MANUAL, gelber(Akzent-)Rahmen am zugehoerigen Playback-Fader; RELEASE je Gruppe, RELEASE ALL global.
- 3b: Palette-Touch faedet Selektion ueber eingestellte FADE-Zeit; CLEAR released Programmer zur Show; Colour-Executes sind Mutual-Exclusion (neuester gewinnt).
- DBO: eigener rot umrandeter Button, nie Akzentfarbe.
- 3D-Pane: kollabierbar (Chevron) + Pop-out als eigenes Fenster (2. Monitor), vorhanden in Timeline, Stage, Auto, Live.
- Morph-Ergebnis immer als Kopie; Venue-Check-Ergebnisse (Offsets, Weisspunkt, Limits, Re-Patches) speichern ins Venue-File.

## State Management (Kernmodelle)
Show-File (.lms): Songs -> Parts -> Effekt-Bloecke (Gruppe, Bar-Range, 4 Sub-Lanes mit je n Bloecken) + Grid/Swing je Song.
Rig/Venue: Fixtures (Typ, Gruppe, Ebene, XYZ, Universe/Adresse), Ebenen (Name, Hoehe), Buehnenelemente, Trusse.
Live-State: aktive Cue, laufende Playbacks (Show/Riffs/Busk-Layer), Gruppen-Modi (following/manual), Master, Seiten.
Morph: Mapping Quelle->Ziel pro Gruppe + Lane-Patches (Live-Links) + Skalierungsoptionen; Venue-Check-Resultate.

## Assets (in diesem Paket, produktionsfertig)
- assets/brand/: favicon.svg, icon-16/32/48/64/128/256/512.png (fuer .ico buendeln), social-preview-1280x640.png, readme-banner-1600x400.png
- assets/stageplot/: 30 SVG-Symbole, 48x48 viewBox, fill:none, stroke #8D9299 (ein Token - fuer Selektion/Ebenen-Dimmen/Print einfach ersetzen), stroke-width 2/1.5/1. Buehnenelemente (drum-riser, riser, wedge, amp, cab-4x12, mic-stand, mic-boom, keys, di-box, distro, foh, backdrop, stairs, hazer), Trusse (truss-straight/-tower/-corner/-circle), Fixture-Typen (par, moving-head-spot, moving-wash, moving-head-multi, led-bar, pixel-bar, sunstrip, pixel-matrix, blinder, strobe, scanner, laser). Konvention: Beam-Tick oben = Ausrichtung.
- Fonts: Barlow, Barlow Condensed, IBM Plex Mono (Google Fonts, OFL - mit der App shippen).

## Files
- "Lichtmaschine App North Star.dc.html" - alle App-Screens (Canvas mit Options-IDs, siehe oben)
- "Lichtmaschine Identity.dc.html" - Brand-Boards (Wortmarke, Glyph-Varianten, Farbsystem)
- support.js - Runtime fuer die .dc.html-Dateien (im selben Ordner lassen; Dateien direkt im Browser oeffnen)
- assets/ - siehe oben
