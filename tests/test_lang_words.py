import sys
import time
import unittest
import json
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import plugins
import stages
from test_speakable import _ServerEnv


class WordsTest(unittest.TestCase):
    stage = {"kind": "headlines", "items": [0] * 5, "clips": [0] * 5}

    def test_active_language_controls_shortcuts_even_when_requested_differs(self):
        import lang
        old = lang.active
        try:
            lang.active = "pl"
            self.assertEqual(stages.fast_path("otwórz pierwszy", self.stage), ("open", 0))
            lang.active = "en"
            self.assertIsNone(stages.fast_path("otwórz pierwszy", self.stage))
        finally:
            lang.active = old

    def test_broken_language_table_keeps_english_shortcuts(self):
        import lang
        stages._words.cache_clear()
        with mock.patch.object(lang, "load", return_value={}):
            self.assertEqual(stages.fast_path("open the first", self.stage, "pl"), ("open", 0))
        stages._words.cache_clear()

    def test_normalization(self):
        self.assertEqual(plugins.norm("Hei Nixi, ÅPNE æøå ąęłśżźćńó!"), "åpne æøå ąęłśżźćńó")
        self.assertEqual(plugins.norm("Hej Nixi, OPEN_the first?"), "open the first")
        self.assertEqual(plugins.norm("Cześć Nixi, play the first video, please"), "play the first video")

    def test_language_shortcuts_and_english_fallback(self):
        cases = {
            "nb": {"kjør første": ("run", 0), "kopier andre": ("copy", 1), "åpne nummer to": ("open", 1),
                   "spill av tredje video": ("play", 2), "spill fjerde klipp": ("play", 3),
                   "lukk": ("close", None), "gå tilbake": ("back", None), "vis den": ("show", None),
                   "vis det": ("show", None)},
            "pl": {"uruchom pierwszy": ("run", 0), "skopiuj go": ("ask", None),
                   "kopiuj drugą": ("copy", 1), "otwórz drugi": ("open", 1),
                   "otwórz drugi artykuł": ("open", 1), "otwórz drugiego": ("open", 1),
                   "odtwórz trzeci film": ("play", 2), "puść czwarty klip": ("play", 3),
                   "zamknij": ("close", None), "wróć": ("back", None),
                   "pokaż": ("show", None), "pokaż to": ("show", None),
                   "skopiuj tę": ("ask", None), "skopiuj tą": ("ask", None)}
        }
        for lang, phrases in cases.items():
            for phrase, result in phrases.items():
                with self.subTest(lang=lang, phrase=phrase):
                    stage = {"items": [0] * 5} if result[0] in ("copy", "ask") else self.stage
                    self.assertEqual(stages.fast_path(phrase, stage, lang), result)
            self.assertEqual(stages.fast_path("open the first one", self.stage, lang), ("open", 0))

    def test_reserved_all_languages(self):
        for phrase in ("åpne andre", "spill av første video", "otwórz drugi artykuł", "pokaż to", "run the first one"):
            with self.subTest(phrase=phrase):
                self.assertTrue(plugins.reserved(phrase))

    def test_every_table_word(self):
        stage = {"items": [0] * 5}
        for lang in ("nb", "pl"):
            words = json.loads((Path(__file__).resolve().parent.parent / "app" / "lang" / f"{lang}.json").read_text())["words"]
            for verb, action in words["verbs"].items():
                self.assertEqual(stages.fast_path(f"{verb} pierwszy" if lang == "pl" else f"{verb} første", stage, lang), (action, 0))
            for word, index in {**words["ordinals"], **words["cardinals"]}.items():
                verb = "otwórz" if lang == "pl" else "åpne"
                self.assertEqual(stages.fast_path(f"{verb} {word}", stage, lang), ("open", index))
            for word in words["fillers"]:
                verb, first = ("otwórz", "pierwszy") if lang == "pl" else ("åpne", "første")
                self.assertEqual(stages.fast_path(f"{verb} {word} {first}", stage, lang), ("open", 0))
            for word in words["it"]:
                verb = "otwórz" if lang == "pl" else "åpne"
                self.assertEqual(stages.fast_path(f"{verb} {word}", stage, lang), ("ask", None))
            for phrase, action in words["plain"].items():
                self.assertEqual(stages.fast_path(phrase, None, lang), (action, None))


class WakeWordsTest(_ServerEnv):
    def test_wake_greetings(self):
        for greeting in ("hei", "hej", "cześć"):
            self.assertIsNotNone(self.server.WAKE_RE.match(f"{greeting} Nixi, otwórz drugi"))
        self.assertIsNotNone(self.server.WAKE_RE.match("hallo niksi, hello"))

    def test_stop_before_wake_while_speaking(self):
        s = self.server
        for lang, phrase in (("en", "stop"), ("nb", "hei nixi stopp"), ("nb", "vær stille"),
                             ("pl", "hej nixi cicho"), ("pl", "cicho"), ("pl", "hallo nixi cicho"), ("pl", "cześć nixi stop")):
            with self.subTest(lang=lang, phrase=phrase), mock.patch.object(s.stages, "lang_active", return_value=lang), \
                 mock.patch.object(s.FLOOR, "floor_overlaps", return_value=False), \
                 mock.patch.object(s.Wake, "speaking", return_value=True), \
                 mock.patch.object(s, "speech_seconds", return_value=1), \
                 mock.patch.object(s, "media_playing", return_value=False), \
                 mock.patch.object(s, "transcribe_pcm", return_value=phrase), \
                 mock.patch.object(s.BUS, "pub") as pub, mock.patch.object(s.Wake, "hush"):
                s.Wake.check(b"\0" * 64000, time.monotonic())
                pub.assert_called_once_with(t="barge", listen=False, text="", path="barge", media="off")
