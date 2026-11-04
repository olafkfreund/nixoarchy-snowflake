"""The window's token script, in real WebKit (#181): the right port gets the token, another port on 127.0.0.1 doesn't.
Mocks can't check this: WebKit's allow-list ignores ports, which is how the first version handed no token at all.
Needs a Wayland session with WebKit2 4.1; skips otherwise. Run it with the companion's Python and GI_TYPELIB_PATH
(as the window has) to make it count."""
import ast
import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PROBE = textwrap.dedent('''
    import sys, ast, json, threading, http.server, socketserver, gi
    gi.require_version("Gtk", "3.0"); gi.require_version("WebKit2", "4.1")
    from gi.repository import Gtk, GLib, WebKit2
    fn = [n for n in ast.parse(open(sys.argv[1]).read()).body if isinstance(n, ast.FunctionDef) and n.name == "token_script"][0]
    ns = {"json": json}; exec(compile(ast.Module([fn], []), "t", "exec"), ns)
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            b = b"<script>window.webkit.messageHandlers.p.postMessage(String(window.__nixiT))</script>"
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(b)
        def log_message(self, *a): pass
    srvs = [socketserver.TCPServer(("127.0.0.1", 0), H) for _ in range(2)]
    for s in srvs: threading.Thread(target=s.serve_forever, daemon=True).start()
    right, other = (s.server_address[1] for s in srvs)
    out, keep = {}, []
    def run(i):
        if i == 2: print(json.dumps(out)); Gtk.main_quit(); return
        ucm = WebKit2.UserContentManager(); ucm.register_script_message_handler("p")
        def got(_u, res):
            try: v = res.get_js_value().to_string()
            except AttributeError: v = res.to_string()
            out[("right", "other")[i]] = v; GLib.idle_add(run, i + 1)
        ucm.connect("script-message-received::p", got)
        src, allow = ns["token_script"]("TESTTOKEN", right)
        ucm.add_script(WebKit2.UserScript.new(src, WebKit2.UserContentInjectedFrames.TOP_FRAME,
                                              WebKit2.UserScriptInjectionTime.START, allow, None))
        v = WebKit2.WebView.new_with_user_content_manager(ucm); w = Gtk.OffscreenWindow(); w.add(v); w.show_all(); keep.append(w)
        v.load_uri(f"http://127.0.0.1:{(right, other)[i]}/?native=1")
    GLib.idle_add(run, 0); GLib.timeout_add(20000, lambda: (print(json.dumps(out)), Gtk.main_quit())); Gtk.main()
''')


class WebKitTokenScript(unittest.TestCase):
    def test_right_port_only(self):
        if not os.environ.get("WAYLAND_DISPLAY"):
            self.skipTest("no Wayland session")
        env = {**os.environ, "GDK_BACKEND": "wayland", "WEBKIT_DISABLE_DMABUF_RENDERER": "1", "WEBKIT_DISABLE_COMPOSITING_MODE": "1"}
        try:
            r = subprocess.run([sys.executable, "-c", PROBE, str(REPO / "app/window.py")], env=env,
                               capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            self.skipTest("WebKit didn't answer in 60 s")
        env_missing = ("No module named 'gi'", "Namespace", "not available", "cannot open display",
                       "Failed to open display", "GL context", "Gtk couldn't be initialized")
        if not r.stdout.strip() and any(m in r.stderr for m in env_missing):
            self.skipTest("WebKit2 4.1 unavailable to this Python: " + r.stderr.strip().splitlines()[-1][:200])
        self.assertTrue(r.stdout.strip(), "the WebKit probe printed nothing:\n" + r.stderr[-2000:])
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out, {"right": "TESTTOKEN", "other": "undefined"}, r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
