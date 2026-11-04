"""News parsing and URL safety without fetching live feeds."""
import importlib.machinery
import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "app"))
import stages  # noqa: E402

loader = importlib.machinery.SourceFileLoader("news_run", str(REPO / "plugins/examples/news/run"))
spec = importlib.util.spec_from_loader(loader.name, loader)
news = importlib.util.module_from_spec(spec)
loader.exec_module(news)

RSS = b'''<rss version="2.0"><channel><item><title>First &amp; &lt;b&gt;bold&lt;/b&gt;</title>
<link>https://example.com/a?utm_source=rss</link><pubDate>Wed, 04 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Undated</title><link>https://example.com/u</link></item></channel></rss>'''
ATOM = b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Second</title>
<link rel="alternate" href="https://example.com/b"/><updated>2026-11-04T11:00:00Z</updated></entry></feed>'''


class NewsTest(unittest.TestCase):
    def test_rss_and_atom(self):
        rss = news.parse_feed(RSS, "BBC")
        atom = news.parse_feed(ATOM, "Guardian")
        self.assertEqual(rss[0]["title"], "First & bold")
        self.assertEqual(rss[0]["at"], 1793786400)
        self.assertIsNone(rss[1]["at"])
        self.assertEqual((atom[0]["title"], atom[0]["at"], atom[0]["url"]),
                         ("Second", 1793790000, "https://example.com/b"))

    def test_undated_atom_entry_and_future_dates(self):          # Codex review: one undated entry dropped the whole feed
        atom = news.parse_feed(b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>No date</title>
<link href="https://example.com/n"/></entry><entry><title>Later</title><link href="https://example.com/l"/>
<updated>2099-01-01T00:00:00Z</updated></entry></feed>''', "Feed")
        self.assertEqual([(x["title"], x["at"]) for x in atom], [("No date", None), ("Later", None)])
        rss = news.parse_feed(RSS.replace(b"Wed, 04 Nov 2026 10:00:00 GMT", b"Thu, 01 Jan 2099 00:00:00 GMT"), "BBC")
        self.assertIsNone(rss[0]["at"])

    def test_merge_newest_and_dedupes_link_then_title(self):
        old = news.parse_feed(RSS, "BBC")
        new = news.parse_feed(ATOM, "Guardian")
        repeats = [{"title": "Other title", "source": "Other", "at": old[0]["at"] - 1,
                    "url": "https://example.com/a#part"},
                   {"title": " second ", "source": "Other", "at": old[0]["at"] - 2,
                    "url": "https://example.com/c"}]
        self.assertEqual([x["title"] for x in news.merge([old, new, repeats])], ["Second", "First & bold", "Undated"])

    def test_url_rules_match_stage(self):
        urls = ("https://www.bbc.co.uk/news/x", "http://a.com/", "javascript:alert(1)",
                "https://u@a.com/", "https://a.com:8443/", "https://[::1]/", "https://127.0.0.1/",
                "https://2130706433/", "https://0x7f.0.0.1/", "https://localhost/", "https://localhost./",
                "https://box.ts.net./", "https://nas.local/", "https://x.home.arpa/", "https://intranet/",
                "https://a..com/", "https://a.com/" + "x" * 387, "https://a.com/a b", "https://a.com/\x00")
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(news.url_ok(url), stages.news_url_ok(url))

    def test_redirect_refuses_private_target(self):
        request = news.urllib.request.Request("https://example.com/feed")
        with self.assertRaisesRegex(ValueError, "unsafe redirect"):
            news.SafeRedirect().redirect_request(request, None, 302, "Found", {}, "https://192.168.1.1/feed")
        self.assertEqual(news.SafeRedirect().redirect_request(request, None, 302, "Found", {}, "/other").full_url,
                         "https://example.com/other")

    def test_say_line_has_word_boundary(self):
        items = [{"title": "A long headline " * 15, "source": "BBC"}] * 3
        line = news.say_line(items)
        self.assertLessEqual(len(line), 200)
        self.assertFalse(line.endswith("headli"))
        self.assertTrue(line.startswith("Top stories: "))

    def test_fetch_caps_body_and_never_parses_oversize(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, n):
                self.self_len.append(n)
                return b"x" * n
            self_len = []
        response = Response()
        with mock.patch.object(news.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = response
            result = [None]
            news.fetch("https://example.com/feed", "BBC", result, 0)
        self.assertIsNone(result[0])
        self.assertEqual(response.self_len, [2 * 1024 * 1024 + 1])

    def test_invalid_feeds_make_one_facts_card_without_network(self):
        config = {"config": {"feeds": [{"name": "Private", "url": "https://127.0.0.1/a"},
                                       {"name": "Local", "url": "https://nas.local/b"}]}}
        output = io.StringIO()
        with mock.patch.object(news.sys, "stdin", io.StringIO(json.dumps(config))), \
             mock.patch.object(news.urllib.request, "build_opener", side_effect=AssertionError("network called")), \
             redirect_stdout(output):
            news.main()
        card = json.loads(output.getvalue())
        self.assertEqual((card["kind"], card["points"]), ("facts", ["No news feeds could be reached."]))
        self.assertIn("2 couldn't be reached", card["source"])


if __name__ == "__main__":
    unittest.main()
