package main

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"flag"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"syscall"

	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/store/sqlstore"
	waLog "go.mau.fi/whatsmeow/util/log"
)

// whatsmeow warning arguments can contain message data, so only the level is logged.
type quietLogger struct{}

func (quietLogger) Warnf(string, ...any)      { log.Print("WhatsApp warning") }
func (quietLogger) Errorf(string, ...any)     { log.Print("WhatsApp error") }
func (quietLogger) Infof(string, ...any)      {}
func (quietLogger) Debugf(string, ...any)     {}
func (q quietLogger) Sub(string) waLog.Logger { return q }

func randomHex(n int) (string, error) {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

func writeToken(run string) (string, error) {
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	token := base64.RawURLEncoding.EncodeToString(raw)
	tmp := filepath.Join(run, "token.tmp")
	if err := os.Remove(tmp); err != nil && !os.IsNotExist(err) {
		return "", err
	}
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return "", err
	}
	defer os.Remove(tmp)
	if _, err = f.WriteString(token); err == nil {
		err = f.Sync()
	}
	if closeErr := f.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		return "", err
	}
	if err = os.Rename(tmp, filepath.Join(run, "token")); err != nil {
		return "", err
	}
	d, err := os.Open(run)
	if err != nil {
		return "", err
	}
	err = d.Sync()
	d.Close()
	return token, err
}

func clearDir(path string) error {
	if err := os.RemoveAll(path); err != nil {
		return err
	}
	return os.Mkdir(path, 0700)
}

func socket(run string) (net.Listener, error) {
	path := filepath.Join(run, "sock")
	if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
		return nil, err
	}
	l, err := net.Listen("unix", path)
	if err != nil {
		return nil, err
	}
	if err = os.Chmod(path, 0600); err != nil {
		l.Close()
		return nil, err
	}
	return l, nil
}

func main() {
	state := flag.String("state", "", "persistent state directory")
	run := flag.String("run", "", "runtime directory")
	maxFileMB := flag.Int("max-file-mb", 100, "maximum file size in MiB")
	flag.Parse()
	syscall.Umask(0077)
	if *state == "" || *run == "" || *maxFileMB < 1 {
		log.Fatal("invalid bridge configuration")
	}
	if err := os.MkdirAll(*state, 0700); err != nil {
		log.Fatal("state directory unavailable")
	}
	if err := os.MkdirAll(*run, 0700); err != nil {
		log.Fatal("runtime directory unavailable")
	}
	for _, name := range []string{"stage", "dl"} {
		if err := clearDir(filepath.Join(*run, name)); err != nil {
			log.Fatal("runtime directory unavailable")
		}
	}
	accountDB, err := sql.Open("sqlite3", filepath.Join(*state, "whatsapp.db"))
	if err != nil {
		log.Fatal("account store unavailable")
	}
	accountDB.SetMaxOpenConns(1)
	if _, err = accountDB.Exec("PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000"); err != nil {
		log.Fatal("account store unavailable")
	}
	accounts := sqlstore.NewWithDB(accountDB, "sqlite3", quietLogger{})
	if err = accounts.Upgrade(context.Background()); err != nil {
		log.Fatal("account store unavailable")
	}
	defer accounts.Close()
	device, err := accounts.GetFirstDevice(context.Background())
	if err != nil {
		log.Fatal("account store unavailable")
	}
	if device == nil {
		device = accounts.NewDevice()
	}
	store, err := NewMessageStore(filepath.Join(*state, "messages.db"))
	if err != nil {
		log.Fatal("message store unavailable")
	}
	defer store.Close()
	token, err := writeToken(*run)
	if err != nil {
		log.Fatal("token unavailable")
	}
	boot, err := randomHex(16)
	if err != nil {
		log.Fatal("boot id unavailable")
	}
	client := whatsmeow.NewClient(device, quietLogger{})
	client.InitialAutoReconnect = true
	client.EnableAutoReconnect = true
	b := &Bridge{client: client, transport: client, store: store, state: "unpaired", token: token, boot: boot, stateDir: *state, runDir: *run, maxFile: int64(*maxFileMB) << 20}
	b.closeAccount = accounts.Close
	client.AddEventHandler(func(e any) {
		if err := b.HandleEvent(e); err != nil {
			log.Print("message store error")
		}
	})
	l, err := socket(*run)
	if err != nil {
		log.Fatal("socket unavailable")
	}
	defer l.Close()
	server := &http.Server{Handler: b}
	b.stop = func() { server.Close() }
	if !device.ID.IsEmpty() {
		b.state = "connecting"
		go b.connect()
	}
	if err = server.Serve(l); err != nil && err != http.ErrServerClosed {
		log.Fatal("socket failed")
	}
}
