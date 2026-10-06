# Jungle Shorts

Lokale app die van een podcastvideo automatisch shorts maakt:

1. **Transcriberen**: faster-whisper, met woord-timestamps. Het transcript wordt naast de video bewaard, dus de tweede keer gaat het direct.
2. **Highlights kiezen**: Claude kiest de fragmenten met de sterkste hook en een afgeronde gedachte (15–90 sec) en legt begin en eind op zinsgrenzen.
3. **Graphics plannen**: per short kiest Claude ook de motion graphics: een hook-titel in de eerste seconden, een getal-kaart als er een cijfer valt, een lijstpunt bij een opsomming (max 3, nooit tegelijk).
4. **Renderen**: ffmpeg knipt en cropt op het gezicht van de spreker. De grafische laag (ondertitels met actief woord in een accentblok, plus de graphics) wordt als HTML gerenderd en frame-exact over de video gelegd. Daarna volgt een eindkaart met logo en tagline.

## Huisstijlen

Per klant stel je in de app kleuren, lettertype, logo en tagline in, met een live voorbeeld. Ze staan in `huisstijlen/<naam>/`.
Het ontwerp van de graphics zelf staat in Claude Design (canvas "Jungle Shorts templates") en in `jungle_shorts/overlay.html`. Pas je het ontwerp op het canvas aan, laat Claude dan `overlay.html` bijwerken.

## Installeren (Windows)

1. Installeer [Python 3.10+](https://www.python.org/downloads/) en [ffmpeg](https://www.gyan.dev/ffmpeg/builds/). Zet ffmpeg in je PATH.
2. Zet je Claude API-key: `setx ANTHROPIC_API_KEY "sk-ant-..."` (daarna een nieuw venster openen).
3. Dubbelklik op `start.bat`. De eerste keer installeert hij alles (ook een Chromium voor het renderen van de graphics); daarna opent de app op http://localhost:5055.

## Gebruik

- Kies een video (pad plakken of Bladeren), of plak een YouTube- of Drive-link bij **Via link**.
- Kies het aantal shorts en **Snel** of **Grondig**, en druk op **Highlights zoeken**.
- Vink de clips aan die je wilt, pas eventueel begin en eind aan, kies formaat en huisstijl en druk op **Maak shorts**.

Zonder de app, in één keer: `python maak_shorts.py "<map of video>" --aantal 10 --huisstijl podcast-jungle`. Geef je een map, dan pakt hij de grootste video. Er komt ook een `captions.json` met captions en hashtags bij.
- De shorts staan in `werkmap/shorts/<videonaam>/`.

## Bekende beperkingen

- De uitsnede volgt het gezicht per clip (één vaste positie). Wisselt het beeld tussen twee sprekers in één shot, dan staat de tweede spreker soms half in beeld. Volgende stap: per zin wisselen met `camera_matcher.py` uit de bestaande motor.
- B-roll (cutaways naar stockbeelden) zit er nog niet in.
