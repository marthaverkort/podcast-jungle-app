# Jungle Shorts

Lokale app die van een podcastvideo automatisch shorts maakt:

1. **Transcriberen**: faster-whisper, met woord-timestamps. Het transcript wordt naast de video bewaard, dus de tweede keer gaat het direct.
2. **Highlights kiezen**: Claude kiest de fragmenten met de sterkste hook en een afgeronde gedachte (15–90 sec) en legt begin en eind op zinsgrenzen.
3. **Renderen**: ffmpeg knipt, cropt naar 9:16, 1:1 of 16:9 en brandt ondertitels in, met het actieve woord in groen.

## Installeren (Windows)

1. Installeer [Python 3.10+](https://www.python.org/downloads/) en [ffmpeg](https://www.gyan.dev/ffmpeg/builds/). Zet ffmpeg in je PATH.
2. Zet je Claude API-key: `setx ANTHROPIC_API_KEY "sk-ant-..."` (daarna een nieuw venster openen).
3. Dubbelklik op `start.bat`. De eerste keer installeert hij alles; daarna opent de app op http://localhost:5055.

## Gebruik

- Kies een video (pad plakken of Bladeren), of plak een YouTube- of Drive-link bij **Via link**.
- Kies het aantal shorts en **Snel** of **Grondig**, en druk op **Highlights zoeken**.
- Vink de clips aan die je wilt, pas eventueel begin en eind aan, kies het formaat en druk op **Maak shorts**.
- De shorts staan in `werkmap/shorts/<videonaam>/`.

## Bekende beperking

De crop zit nu vast in het midden van het beeld. Bij een opname met twee sprekers naast elkaar valt er dan soms iemand half buiten beeld. De volgende stap is de crop laten volgen wie er praat, met de camera-matching uit de bestaande Podcast Jungle-motor (`camera_matcher.py` / `split_frame.py`).
