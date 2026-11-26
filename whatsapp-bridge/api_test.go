package main

import (
	"context"
	"errors"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"go.mau.fi/whatsmeow"
	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

type fakeWA struct {
	logged, connected              bool
	sendErr, logoutErr, connectErr error
	sends, connects, qrCalls       int
	qr                             chan whatsmeow.QRChannelItem
	data                           []byte
}

func (f *fakeWA) Connect() error    { f.connects++; return f.connectErr }
func (f *fakeWA) IsConnected() bool { return f.connected }
func (f *fakeWA) IsLoggedIn() bool  { return f.logged }
func (f *fakeWA) GetQRChannel(context.Context) (<-chan whatsmeow.QRChannelItem, error) {
	f.qrCalls++
	return f.qr, nil
}
func (f *fakeWA) SendMessage(context.Context, types.JID, *waProto.Message, ...whatsmeow.SendRequestExtra) (whatsmeow.SendResponse, error) {
	f.sends++
	return whatsmeow.SendResponse{ID: "sent-id"}, f.sendErr
}
func (f *fakeWA) Upload(context.Context, []byte, whatsmeow.MediaType) (whatsmeow.UploadResponse, error) {
	return whatsmeow.UploadResponse{}, nil
}
func (f *fakeWA) DownloadMediaWithPath(context.Context, string, []byte, []byte, []byte, whatsmeow.MediaType, string, bool) ([]byte, error) {
	return f.data, nil
}
func (f *fakeWA) Logout(context.Context) error { return f.logoutErr }

func testBridge(t *testing.T) (*Bridge, *fakeWA) {
	t.Helper()
	root := t.TempDir()
	run := filepath.Join(root, "run")
	state := filepath.Join(root, "state")
	for _, p := range []string{run, state, filepath.Join(run, "stage"), filepath.Join(run, "dl")} {
		if err := os.MkdirAll(p, 0700); err != nil {
			t.Fatal(err)
		}
	}
	s, err := NewMessageStore(filepath.Join(state, "messages.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	f := &fakeWA{logged: true, connected: true, qr: make(chan whatsmeow.QRChannelItem, 2)}
	return &Bridge{store: s, transport: f, state: "unpaired", boot: "boot", token: "secret", runDir: run, stateDir: state, maxFile: 8}, f
}
func call(b *Bridge, method, path, body, boot string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	r.Header.Set("Authorization", "Bearer secret")
	if boot != "" {
		r.Header.Set("If-Boot", boot)
	}
	w := httptest.NewRecorder()
	b.ServeHTTP(w, r)
	return w
}
func TestTokenAndSocket(t *testing.T) {
	run := t.TempDir()
	if err := os.WriteFile(filepath.Join(run, "token"), []byte("old"), 0600); err != nil {
		t.Fatal(err)
	}
	token, err := writeToken(run)
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(filepath.Join(run, "token"))
	if err != nil || string(b) != token || len(token) != 32 {
		t.Fatalf("token: %q %v", b, err)
	}
	if _, err := os.Stat(filepath.Join(run, "token.tmp")); !os.IsNotExist(err) {
		t.Fatal("temporary token remains")
	}
	info, _ := os.Stat(filepath.Join(run, "token"))
	if info.Mode().Perm() != 0600 {
		t.Fatal(info.Mode())
	}
	l, err := socket(run)
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	if l.Addr().Network() != "unix" {
		t.Fatal(l.Addr())
	}
	info, _ = os.Stat(filepath.Join(run, "sock"))
	if info.Mode().Perm() != 0600 {
		t.Fatal(info.Mode())
	}
}
func TestAuthAndBoot(t *testing.T) {
	b, f := testBridge(t)
	r := httptest.NewRequest("GET", "/status", nil)
	w := httptest.NewRecorder()
	b.ServeHTTP(w, r)
	if w.Code != 401 || w.Header().Get("X-Boot") != "boot" {
		t.Fatal(w.Code, w.Header())
	}
	w = call(b, "POST", "/send", `{"jid":"123@s.whatsapp.net","text":"hello"}`, "stale")
	if !strings.Contains(w.Body.String(), "not_sent") || f.sends != 0 {
		t.Fatal(w.Body.String(), f.sends)
	}
	w = call(b, "POST", "/forget", `{}`, "stale")
	if w.Code != 409 {
		t.Fatal(w.Code)
	}
}
func TestSendAndStage(t *testing.T) {
	b, f := testBridge(t)
	ctx := context.Background()
	for _, jid := range []string{"123@g.us", "status@broadcast", "123@newsletter"} {
		if r := b.send(ctx, jid, "hello", "", "", "report.pdf"); r.Result != "not_sent" {
			t.Fatal(jid, r)
		}
	}
	if f.sends != 0 {
		t.Fatal(f.sends)
	}
	name := "abcdefghijklmnop"
	path := filepath.Join(b.runDir, "stage", name)
	if _, err := stagedFile(b.runDir, "../bad", 8); err == nil {
		t.Fatal("accepted invalid name")
	}
	if err := os.Symlink("/etc/passwd", path); err != nil {
		t.Fatal(err)
	}
	if _, err := stagedFile(b.runDir, name, 8); err == nil {
		t.Fatal("accepted symlink")
	}
	os.Remove(path)
	os.Mkdir(path, 0700)
	if _, err := stagedFile(b.runDir, name, 8); err == nil {
		t.Fatal("accepted directory")
	}
	os.Remove(path)
	os.WriteFile(path, []byte("123456789"), 0600)
	if _, err := stagedFile(b.runDir, name, 8); err == nil {
		t.Fatal("accepted oversize")
	}
	os.WriteFile(path, []byte("small"), 0600)
	f.connected = false
	if r := b.send(ctx, "123@s.whatsapp.net", "", name, "", "report.pdf"); r.Result != "not_sent" {
		t.Fatal(r)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatal("not_sent deleted staged file")
	}
	f.connected = true
	f.sendErr = errors.New("uncertain")
	if r := b.send(ctx, "123@s.whatsapp.net", "", name, "", "report.pdf"); r.Result != "unknown" {
		t.Fatal(r)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("sent attempt kept staged file")
	}
	f.sendErr = nil
	if r := b.send(ctx, "123@s.whatsapp.net", "hello", "", "", "report.pdf"); r.Result != "sent" || r.ID != "sent-id" {
		t.Fatal(r)
	}
	f.logged = false
	if r := b.send(ctx, "123@s.whatsapp.net", "hello", "", "", "report.pdf"); r.Result != "not_sent" {
		t.Fatal(r)
	}
	if f.sends != 2 {
		t.Fatal(f.sends)
	}
}
func TestDownloadAndExt(t *testing.T) {
	b, f := testBridge(t)
	f.data = []byte("abc")
	for _, v := range []struct{ mime, want string }{{"image/png", "png"}, {"application/x-unknown-custom", "bin"}} {
		if got := downloadExt(v.mime); got != v.want {
			t.Fatal(got, v.want)
		}
	}
	m := Message{ID: "m", ChatJID: "123@s.whatsapp.net", DirectPath: "/path", MediaKey: []byte{1}, MimeType: "image/png", Kind: "image", Size: 3}
	if err := b.store.StoreMessage(m); err != nil {
		t.Fatal(err)
	}
	v, err := b.download(context.Background(), m.ChatJID, m.ID)
	if err != nil {
		t.Fatal(err)
	}
	name := v.(map[string]string)["file"]
	if !strings.HasSuffix(name, ".png") || strings.Contains(name, "/") {
		t.Fatal(name)
	}
	data, err := os.ReadFile(filepath.Join(b.runDir, "dl", name))
	if err != nil || string(data) != "abc" {
		t.Fatal(err, string(data))
	}
}

func TestDirectMergeKeepsOneThreadAndTombstone(t *testing.T) {
	b, _ := testBridge(t)
	lid, phone := "111@lid", "222@s.whatsapp.net"
	if err := b.store.StoreChat(lid, "Friend", false, time.Now()); err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"old", "deleted"} {
		if err := b.store.StoreMessage(Message{ID: id, ChatJID: lid, Text: "before"}); err != nil {
			t.Fatal(err)
		}
	}
	if err := b.store.StoreMessage(Message{ID: "deleted", ChatJID: phone, Text: "other copy"}); err != nil {
		t.Fatal(err)
	}
	if err := b.store.Tombstone("deleted", lid); err != nil {
		t.Fatal(err)
	}
	if err := b.store.MergeDirect(lid, phone); err != nil {
		t.Fatal(err)
	}
	chats, err := b.store.Chats("", 20)
	if err != nil || len(chats) != 1 || chats[0].JID != phone {
		t.Fatal(chats, err)
	}
	thread, err := b.store.Thread(phone, 50, 0)
	if err != nil || len(thread) != 2 {
		t.Fatal(thread, err)
	}
	for _, m := range thread {
		if m.ID == "deleted" && (!m.Deleted || m.Text != "") {
			t.Fatal(m)
		}
	}
}
func TestPairStatesAndForget(t *testing.T) {
	b, f := testBridge(t)
	f.logged = false
	f.connected = false
	f.qr <- whatsmeow.QRChannelItem{Event: "code", Code: "test-code", Timeout: time.Minute}
	w := call(b, "POST", "/pair", "", "")
	if w.Code != 200 || !strings.Contains(w.Body.String(), "data:image/png;base64,") {
		t.Fatal(w.Code, w.Body.String())
	}
	call(b, "POST", "/pair", "", "")
	if f.qrCalls != 1 || f.connects != 1 {
		t.Fatal(f.qrCalls, f.connects)
	}
	f.qr <- whatsmeow.QRChannelTimeout
	for i := 0; i < 100; i++ {
		b.mu.Lock()
		done := b.pair == nil
		b.mu.Unlock()
		if done {
			break
		}
		time.Sleep(time.Millisecond)
	}
	b.mu.Lock()
	if b.pair != nil || b.state != "error" {
		t.Fatal(b.state)
	}
	b.mu.Unlock()
	b.HandleEvent(&events.LoggedOut{})
	state, _ := b.status()
	if state != "relink" {
		t.Fatal(state)
	}
	b.mu.Lock()
	b.state = "connecting"
	b.mu.Unlock()
	f.connectErr = errors.New("client outdated: 405")
	b.connect()
	state, _ = b.status()
	if state != "outdated" {
		t.Fatal(state)
	}
	f.logoutErr = errors.New("offline")
	os.WriteFile(filepath.Join(b.stateDir, "whatsapp.db"), []byte("x"), 0600)
	for _, name := range []string{"whatsapp.db-wal", "whatsapp.db-shm", "messages.db-wal", "messages.db-shm"} {
		os.WriteFile(filepath.Join(b.stateDir, name), []byte("x"), 0600)
	}
	w = call(b, "POST", "/forget", "", "boot")
	if w.Code != 200 {
		t.Fatal(w.Code)
	}
	for _, name := range []string{"whatsapp.db", "whatsapp.db-wal", "whatsapp.db-shm", "messages.db", "messages.db-wal", "messages.db-shm"} {
		if _, err := os.Stat(filepath.Join(b.stateDir, name)); !os.IsNotExist(err) {
			t.Fatal(name, err)
		}
	}
	for _, name := range []string{"stage", "dl"} {
		if _, err := os.Stat(filepath.Join(b.runDir, name)); !os.IsNotExist(err) {
			t.Fatal(name, err)
		}
	}
}

func TestSafeName(t *testing.T) {
	for in, want := range map[string]string{"../../etc/passwd": "passwd", "a\x00b.pdf": "ab.pdf", "": "attachment", "..": "attachment", "dir\\x.txt": "x.txt"} {
		if got := safeName(in); got != want {
			t.Fatalf("safeName(%q) = %q, want %q", in, got, want)
		}
	}
}
