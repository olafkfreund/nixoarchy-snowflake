import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
BLOCK = '<<stage>>{"v":1,"kind":"commands","items":[{"label":"Install","cmd":"nix profile install nixpkgs#firefox"}]}'


class StageStreamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_env = os.environ.copy()
        cls.tmp = tempfile.mkdtemp(prefix="nixi-stage-test-")
        for k, d in (("HOME", ""), ("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
            os.environ[k] = os.path.join(cls.tmp, d)
            os.makedirs(os.environ[k], exist_ok=True)
        sys.path.insert(0, str(REPO_ROOT / "app"))
        import server
        cls.server = server

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls._orig_env)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def ask(self, deltas, bridged=True):
        """Run Handler.ask against a fake bridge turn; -> (events the page got, history record)."""
        s = self.server

        def fake_bridge(prompt, emit, *_):
            for d in deltas:
                emit(t="delta", text=d)
            emit(t="result", text="", is_error=False)
            return "done"

        h = s.Handler.__new__(s.Handler)
        h.wfile = io.BytesIO()
        h.send_response, h.send_header, h.end_headers = mock.Mock(), mock.Mock(), mock.Mock()
        h._body = lambda: json.dumps({"prompt": "how do I install firefox?"}).encode()
        recs = []
        with mock.patch.object(s, "BRIDGED", bridged), mock.patch.object(s, "run_bridge", fake_bridge), mock.patch.object(s, "run_claude", fake_bridge), \
                mock.patch.object(s, "hist_add", recs.append), mock.patch.object(s, "pick_auto", return_value=None), \
                mock.patch.object(s, "auto_compact"), mock.patch.object(s.recall, "add"), mock.patch.dict(s.CFG, {"auto_compact": False}):
            h.ask()
        evs = [json.loads(x[6:]) for x in h.wfile.getvalue().decode().split("\n\n") if x.startswith("data: ")]
        return evs, recs[0]

    def test_block_cut_split_over_deltas_and_stage_sent_before_result(self):
        evs, rec = self.ask(["Here you go.\n<<st", "age>>{\"v\":1,\"kind\":\"comm", BLOCK[BLOCK.index('ands'):]])
        self.assertNotIn("<<stage", json.dumps(evs))
        self.assertEqual("".join(e["text"] for e in evs if e["t"] == "delta"), "Here you go.\n")
        self.assertEqual(rec["him"], "Here you go.")
        kinds = [e["t"] for e in evs]
        self.assertEqual(kinds.count("stage"), 1)
        self.assertLess(kinds.index("stage"), kinds.index("result"))
        st = next(e for e in evs if e["t"] == "stage")
        self.assertEqual(st["kind"], "commands")
        self.assertEqual(self.server.STAGES.get(st["items"][0]["token"])[1]["cmd"], "nix profile install nixpkgs#firefox")

    def test_invalid_block_is_dropped_caption_stays(self):
        evs, rec = self.ask(['Sure.\n<<stage>>{"v":1,"kind":"commands","items":[{"label":"a","cmd":"x\\ny"}]}'])
        self.assertNotIn("stage", [e["t"] for e in evs])
        self.assertNotIn("<<stage", json.dumps(evs))
        self.assertEqual(rec["him"], "Sure.")

    def test_setting_off_or_not_bridged_leaves_text_alone(self):
        with mock.patch.dict(self.server.CFG, {"answer_stages": False}):
            evs, _ = self.ask(["hi " + BLOCK])
        self.assertNotIn("stage", [e["t"] for e in evs])
        evs, _ = self.ask(["hi " + BLOCK], bridged=False)
        self.assertNotIn("stage", [e["t"] for e in evs])

    def test_partial_marker_flushed_as_text(self):
        evs, rec = self.ask(["a <<st"])
        self.assertEqual(rec["him"], "a <<st")


if __name__ == "__main__":
    unittest.main()
