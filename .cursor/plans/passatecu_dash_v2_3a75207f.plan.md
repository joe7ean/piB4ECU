---
name: PassatECU Dash V2
overview: Überarbeite das Smartphone-Dashboard (V2) als deterministische, tabbasierte UI und ergänze optional ABS/weitere ECU-Werte. Fehlerspeicher wird nur manuell (plus seltenes Refresh) geladen.
todos:
  - id: v2-multi-ecu
    content: "`server.py`: Multi-ECU polling (engine + optional ABS), WS-Datenstruktur für Tabs einführen."
    status: pending
  - id: v2-fault-manual
    content: "`server.py` + `dashboard.html`: Faults manuell per Endpoint + Button; seltenes Refresh (Default 10 min)."
    status: pending
  - id: v2-decoder-known-only
    content: "`kw1281.py`: unbekannte Kanäle zuverlässig ausblenden oder als known/unknown flaggen."
    status: pending
  - id: v2-ui-tabs-smartphone
    content: "`dashboard.html`: V2 Smartphone-first, Tabs `Antrieb`/`ABS/Tempomat`/`Fehler`; nur bekannte Widgets rendern."
    status: pending
  - id: v2-docs
    content: Kurze V2-Anleitung ergänzen (was angezeigt wird, wie Faults manuell abgerufen werden, ABS-Tabs optional).
    status: pending
isProject: false
---

## Ziel (V2)

- Smartphone-first Dashboard mit klaren Tabs (z.B. `Antrieb` und `ABS/Tempomat`)
- Nur Werte anzeigen, die wir zuverlässig/decodierbar aus KW1281 herausbekommen (keine „Spekulation“-Widgets)
- Fehlerspeicher-Logik: zuerst manuell (Button), zusätzlich seltenes Refresh (Default: 10 Minuten)
- Optional ABS/zusätzliche ECU anbinden (nur wenn die Dekodierung dafür passt)

## Hintergrund / Datenfluss

```mermaid
flowchart LR
  A[KKL/K-Line Adapter] --> B[KW1281 Backend (server.py)]
  B -->|Live Messwerte| C[WebSocket /ws]
  B -->|Manuelles Fehlerspeicher-Read| C
  C --> D[dashboard.html V2 Tabs + Widgets]

  B -->|Engine ECU (0x01)| C
  B -->|ABS ECU (0x03, optional)| C
```



## Umsetzungsvorhaben

1. Backend-Refactor für mehrere ECUs

- `passat_ecu--claudeOnline/server.py`: zusätzliche ECU-Instanzen verwalten (mind. Motorsteuergerät `ECU_ENGINE=0x01`, plus ABS `ECU_ABS=0x03` wenn sinnvoll)
- pro ECU: `connect(ecu_addr)` und dann `read_measurement_block()` für einen konfigurierbaren Satz Blocknummern (Startwert wie aktuell für Engine; für ABS vorsichtig mit [1,2,3] als erster Ansatz)
- Output-Struktur im WS so ändern, dass UI sauber nach Themen rendern kann (z.B. `data.engine` und `data.abs`)

1. Fehlerspeicher manuell + selten

- `passat_ecu--claudeOnline/server.py`:
  - periodic fault polling entfernen
  - neuen Endpoint einführen, z.B. `POST /api/read-faults?ecu=engine|abs`
  - seltenes Refresh einbauen (Default 600s) optional, aber UI zeigt explizit “aktuell”/“letzter Sync”
- `passat_ecu--claudeOnline/dashboard.html`:
  - Buttons: `Fehler auslesen` (manuell) und `Fehler löschen` (wie bisher)
  - kein automatisches Re-Rendering der Fault-Liste bei jedem Poll, sondern nur wenn neue Fault-Daten kommen

1. Deterministisches UI (nur decodierbare Werte)

- `passat_ecu--claudeOnline/kw1281.py`:
  - sicherstellen, dass die Decoder-Ausgabe als „known“/„unknown“ erkennbar ist (oder unbekannte Kanäle werden schlicht ausgelassen)
  - damit V2 nicht UI-Platzhalter rendert, die im echten Passat nicht vorkommen

1. V2 UI/UX für Smartphone

- `passat_ecu--claudeOnline/dashboard.html`:
  - Tab-Layout (per Anfrage): z.B. `Antrieb` und `ABS/Tempomat`
  - Widgets priorisieren (große Zahlen + optional kleine Sparkline)
  - Platzhalterwerte (z.B. MAP/Leerlaufregelung), die wir noch nicht verlässlich decodieren, werden in V2 nicht angezeigt
  - optional: `Fehler` Tab mit manuellen Buttons

## Meilensteine / Deliverables

- V2 Dashboard im Browser im DEMO-Modus: Layout + Tab-Switch + Manual-Fault-Button funktionieren
- Realbetrieb (im Auto): Anzeige zeigt nur decodierbare Werte; WS aktualisiert zuverlässig
- Fehlerspeicher: manuell abrufbar + seltenes Refresh

## Verifikation (kurz)

- DEMO_MODE=true:
  - WS kommt an, Tabs rendern
  - `Fehler auslesen` liefert die Liste
- DEMO_MODE=false + ECU verbunden:
  - Engine/ABS Werte erscheinen nur wenn vorhanden
  - Manual faults aktualisieren ohne UI-Hänger

