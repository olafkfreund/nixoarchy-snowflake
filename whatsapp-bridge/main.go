package main

import (
	"flag"
	"log"
	"os"
	"path/filepath"
	"syscall"

	waLog "go.mau.fi/whatsmeow/util/log"
)

// whatsmeow warning arguments can contain message data, so only the level is logged.
type quietLogger struct{}

func (quietLogger) Warnf(string, ...any)      { log.Print("WhatsApp warning") }
func (quietLogger) Errorf(string, ...any)     { log.Print("WhatsApp error") }
func (quietLogger) Infof(string, ...any)      {}
func (quietLogger) Debugf(string, ...any)     {}
func (q quietLogger) Sub(string) waLog.Logger { return q }

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
	store, err := NewMessageStore(filepath.Join(*state, "messages.db"))
	if err != nil {
		log.Fatal("message store unavailable")
	}
	defer store.Close()
	// The socket, token and account connection are installed in Step 3.
}
