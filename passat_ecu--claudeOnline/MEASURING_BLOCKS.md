# VW Passat B4 (1.8l Mono-Motronic) - Messwertblöcke & Live-Analyse

Dieses Dokument beschreibt die spezifischen Messwertblöcke (Measuring Blocks) des VW Motorsteuergeräts **8A0 907 311 K** (1.8l 90PS, MKB: ABS/ADZ, Mono-Motronic 1.2.3) basierend auf der Kommunikation mit 4800 Baud über das KW1281 Protokoll.

Zudem enthält es Konzepte, wie diese Daten in Zukunft für ein dynamisches Live-Feedback zum Fahrverhalten und zur Motorgesundheit genutzt werden können.

---

## 1. Detaillierte Aufschlüsselung der Messwertblöcke

### Messwertblock 000: Rohdaten (ADC-Werte)
Block 000 liefert keine physikalischen Einheiten (wie °C oder U/min), sondern direkte 8-Bit-Rohwerte (0-255) des Analog-Digital-Wandlers (ADC) im Steuergerät. 

| Feld | Parameter | Bedeutung & Motor-Zusammenhang |
|------|-----------|--------------------------------|
| 1 | Kühlmitteltemperatur | Widerstandswert des NTC-Sensors. Kalt = hoher Wert, Warm = niedriger Wert. |
| 2 | Drosselklappenwinkel | Position des Gaspedals. Sehr wichtig bei der Mono-Motronic, da sie keinen Luftmassenmesser hat. Die Last wird rein aus Drosselklappe + Drehzahl berechnet (Alpha-N-Steuerung). |
| 3 | Motordrehzahl | Rohsignal vom Hallgeber im Zündverteiler. |
| 4 | Ansauglufttemperatur | NTC-Sensor in der Einspritzkappe. Kalte Luft ist dichter (mehr Sauerstoff) -> Steuergerät spritzt mehr Kraftstoff ein. |
| 5 | Lambdasonden-Spannung | Pendelt idealerweise um 128 (entspricht ca. 0,45V). Zeigt den Restsauerstoff im Abgas an. |
| 6 | Lambdaregler-Lernwert | Langzeit-Adaption (Fuel Trim). Wenn das System Falschluft zieht, wandert dieser Wert dauerhaft nach oben, um das Gemisch anzufetten. |
| 7 | Betriebszustand | Rohwert der Bitmaske (siehe Block 001, Feld 4). |
| 8 | Drosselklappensteller | Position des kleinen Elektromotors, der den Leerlauf regelt (verhindert Absterben bei kaltem Motor oder Klima-Zuschaltung). |
| 9 | Batteriespannung | Gemessene Bordspannung am Steuergerät. |
| 10 | Zündwinkel | Berechneter Zündzeitpunkt (Rohwert). |

### Messwertblock 001: Leerlauf & Basisdaten
Dieser Block liefert die wichtigsten umgerechneten Werte für die Grundeinstellung.

| Feld | Parameter | Beispielwert | Bedeutung & Motor-Zusammenhang |
|------|-----------|--------------|--------------------------------|
| 1 | Motordrehzahl | 920 RPM | Aktuelle Umdrehungen pro Minute. (Soll warm: ~800-850 RPM). |
| 2 | Kühlmitteltemperatur| 95.4 °C | Wichtigster Parameter für Kaltstartanreicherung. Ab ca. 80°C gilt der Motor als betriebswarm. |
| 3 | Lambda-Korrektur | 1.02 | Kurzzeit-Einspritzkorrektur (Short Term Fuel Trim). `1.00` ist das Ideal (Lambda 1 = 14,7kg Luft auf 1kg Benzin). `1.02` bedeutet: Das Steuergerät gibt 2% mehr Kraftstoff hinzu, um Lambda 1 zu erreichen. |
| 4 | Operating Status | `01000010` | 8-Bit-Zustandsmaske (Binär). Jede Ziffer ist ein Schalter (1=An, 0=Aus). |

**Aufschlüsselung Operating Status (`01000010`):**
* `Bit 1` (rechts): Fehler im Speicher (0=Nein)
* `Bit 2`: **Leerlaufschalter geschlossen (1=Ja)** -> Fuß ist vom Gaspedal.
* `Bit 3`: Klimaanlage an (0=Nein)
* `Bit 4`: Klimakompressor läuft (0=Nein)
* `Bit 5`: Gang eingelegt / Automatik (0=Nein)
* `Bit 6`: Servolenkung Druckschalter (0=Nein)
* `Bit 7`: **Lambdaregelung aktiv (1=Ja)** -> Closed-Loop-Betrieb. Motor ist warm genug, Sonde arbeitet.
* `Bit 8` (links): Kaltstartanreicherung (0=Nein)

### Messwertblock 002: Einspritzung & Elektrik

| Feld | Parameter | Beispielwert | Bedeutung & Motor-Zusammenhang |
|------|-----------|--------------|--------------------------------|
| 1 | Motordrehzahl | 920 RPM | Siehe Block 001. |
| 2 | Einspritzzeit | 1.2 ms | Öffnungsdauer des zentralen Einspritzventils pro Takt. Ein direkter Indikator für die Motorlast. Im Leerlauf gering (~1.2ms), beim Beschleunigen hoch. |
| 3 | Batteriespannung | 14.0 V | Zeigt, ob die Lichtmaschine arbeitet. Unter 13V bei laufendem Motor deutet auf Generator-Probleme hin. |
| 4 | Ansauglufttemp. | 32.4 °C | Temperatur der angesaugten Luft. Bei Stau im Sommer hoch, bei Fahrtwind niedrig. |

---

## 2. Konzept: Live-Dynamisches Feedback (Zukünftige Versionen)

Mit diesen Daten, die wir mit ca. 1-2 Hz (Updates pro Sekunde) auslesen können, lässt sich das Dashboard von einer reinen "Anzeige" zu einem **intelligenten Fahr-Assistenten** ausbauen.

### A. "Warm-Up Assistant" (Motorschonung)
* **Logik:** Wir überwachen die Kühlmitteltemperatur (Block 001, Feld 2).
* **Feedback:** 
  * Unter 60°C: Das Dashboard leuchtet dezent blau ("Cold Engine"). Eine Warnung erscheint, wenn die Drehzahl über 3000 RPM oder die Einspritzzeit (Last) stark ansteigt.
  * 60°C - 80°C: Gelb ("Warming up").
  * Über 80°C: Grün ("Operating Temp reached - Ready").
* **Nutzen:** Verhindert hohen Verschleiß durch Treten des kalten Motors.

### B. "Eco-Drive Score" (Effizienz-Gamification)
* **Logik:** Wir kombinieren Drosselklappenwinkel (aus Block 000), Drehzahl und Einspritzzeit (Block 002).
* **Feedback:**
  * **Schubabschaltung erkennen:** Wenn Drehzahl > 1500 RPM, Fuß vom Gas (Operating Status Bit 2 = 1) und Einspritzzeit = 0.0 ms. Das Dashboard lobt den Fahrer ("Coasting / Schubabschaltung aktiv - 0.0 L/100km").
  * **Untertouriges Fahren:** Hohe Einspritzzeit bei sehr niedriger Drehzahl (< 1200 RPM). Warnung: "Shift Down!" (Motor quält sich).
  * Ein Live-Score (0-100) bewertet, wie vorausschauend gefahren wird.

### C. "Engine Health Monitor" (Früherkennung von Defekten)
* **Logik:** Wir analysieren die Lambda-Werte und Spannungen im Hintergrund.
* **Feedback:**
  * **Falschluft-Alarm:** Wenn der Lambda-Korrekturfaktor (Block 001, Feld 3) dauerhaft über 1.10 (10% Anreicherung) liegt, zieht der Motor wahrscheinlich Falschluft (z.B. gerissener Vergaserflansch - ein Klassiker beim 1.8l ABS!). Das Dashboard meldet: "Check for vacuum leaks!"
  * **Lichtmaschinen-Warnung:** Fällt die Spannung (Block 002) bei laufendem Motor unter 13.2V, gibt es einen Hinweis auf schwächelnde Kohlebürsten im Generator.
  * **Sensor-Verschleiß:** Wenn das Drosselklappen-Poti (Block 000, Feld 2) beim langsamen Gasgeben Sprünge macht (z.B. 20 -> 25 -> 18 -> 30), erkennt das Skript einen "Dead Spot" im Poti (typisches Ruckeln beim Fahren).

### D. "Performance Mode"
* **Logik:** Erkennung von Volllast (WOT - Wide Open Throttle).
* **Feedback:** Wenn Drosselklappe > 80% und Lambdaregelung schaltet ab (Bit 7 geht auf 0, da bei Volllast das Gemisch stur angefettet wird), wechselt das UI in einen roten "Power Mode" und zeigt die maximale Einspritzzeit als Balkendiagramm an.

---
*Dokument erstellt für das piB4ECU Projekt.*