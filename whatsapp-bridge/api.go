package main

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"go.mau.fi/whatsmeow/types"
)

func reply(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func decode(r *http.Request, v any) bool {
	r.Body = http.MaxBytesReader(nil, r.Body, 1<<20)
	return json.NewDecoder(r.Body).Decode(v) == nil
}

func number(raw string) int64 { n, _ := strconv.ParseInt(raw, 10, 64); return n }

func (b *Bridge) status() (string, string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	state := b.state
	if state == "relink" || state == "outdated" {
		return state, ""
	}
	if b.transport != nil && b.transport.IsLoggedIn() && b.transport.IsConnected() {
		me := ""
		if b.client != nil && b.client.Store != nil {
			me = b.client.Store.GetJID().String()
		}
		return "ready", me
	}
	return state, ""
}

func (b *Bridge) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("X-Boot", b.boot)
	auth := r.Header.Get("Authorization")
	if !strings.HasPrefix(auth, "Bearer ") || subtle.ConstantTimeCompare([]byte(strings.TrimPrefix(auth, "Bearer ")), []byte(b.token)) != 1 {
		reply(w, http.StatusUnauthorized, map[string]string{"error": "unauthorized"})
		return
	}
	b.mu.Lock()
	forgetting := b.forgetting
	b.mu.Unlock()
	if forgetting {
		reply(w, http.StatusServiceUnavailable, map[string]string{"error": "stopping"})
		return
	}
	if (r.URL.Path == "/send" || r.URL.Path == "/send-file" || r.URL.Path == "/forget") && r.Method == http.MethodPost && r.Header.Get("If-Boot") != b.boot {
		if r.URL.Path == "/forget" {
			reply(w, http.StatusConflict, map[string]string{"error": "stale boot"})
		} else {
			reply(w, http.StatusOK, map[string]string{"result": "not_sent"})
		}
		return
	}
	if (r.Method == "GET" && (r.URL.Path == "/chats" || r.URL.Path == "/contacts" || r.URL.Path == "/thread" || r.URL.Path == "/new")) || (r.Method == "POST" && r.URL.Path == "/download") {
		if err := b.normalizeStored(); err != nil {
			b.readReply(w, nil, err)
			return
		}
	}
	switch {
	case r.Method == "GET" && r.URL.Path == "/status":
		state, me := b.status()
		reply(w, 200, map[string]string{"boot": b.boot, "state": state, "me": me})
	case r.Method == "POST" && r.URL.Path == "/pair":
		b.pairReply(w)
	case r.Method == "POST" && r.URL.Path == "/pair/cancel":
		b.cancelPair()
		reply(w, 200, map[string]bool{"ok": true})
	case r.Method == "POST" && r.URL.Path == "/forget":
		b.forget(w)
	case r.Method == "GET" && r.URL.Path == "/chats":
		v, err := b.store.Chats(r.URL.Query().Get("q"), int(number(r.URL.Query().Get("limit"))))
		b.readReply(w, v, err)
	case r.Method == "GET" && r.URL.Path == "/contacts":
		v, err := b.store.Contacts(r.URL.Query().Get("q"))
		b.readReply(w, v, err)
	case r.Method == "GET" && r.URL.Path == "/thread":
		jid, err := types.ParseJID(r.URL.Query().Get("jid"))
		if err != nil {
			reply(w, 400, map[string]string{"error": "invalid jid"})
			return
		}
		v, err := b.store.Thread(b.normalJID(jid).String(), int(number(r.URL.Query().Get("limit"))), number(r.URL.Query().Get("before")))
		b.readReply(w, v, err)
	case r.Method == "GET" && r.URL.Path == "/new":
		if r.URL.Query().Get("latest") == "1" {
			seq, err := b.store.LatestSeq()
			b.readReply(w, map[string]int64{"seq": seq}, err)
			return
		}
		v, err := b.store.NewAfter(number(r.URL.Query().Get("after")))
		if err != nil {
			b.readReply(w, nil, err)
			return
		}
		out := make([]any, 0, len(v))
		for _, m := range v {
			if strings.HasSuffix(m.ChatJID, "@broadcast") || strings.HasSuffix(m.ChatJID, "@newsletter") {
				continue
			}
			out = append(out, map[string]any{"seq": m.Seq, "jid": m.ChatJID, "id": m.ID, "at": m.At, "is_group": !strings.HasSuffix(m.ChatJID, "@s.whatsapp.net") && !strings.HasSuffix(m.ChatJID, "@lid"), "mentions_me": m.MentionsMe, "sender_jid": m.SenderJID, "sender_name": b.store.SenderName(m.SenderJID)})
		}
		reply(w, 200, out)
	case r.Method == "POST" && (r.URL.Path == "/send" || r.URL.Path == "/send-file"):
		var req struct {
			JID      string `json:"jid"`
			Text     string `json:"text"`
			Staged   string `json:"staged"`
			Caption  string `json:"caption"`
			FileName string `json:"file_name"`
		}
		if !decode(r, &req) {
			reply(w, 400, map[string]string{"error": "invalid request"})
			return
		}
		if r.URL.Path == "/send" {
			reply(w, 200, b.send(r.Context(), req.JID, req.Text, "", "", ""))
		} else {
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
			defer cancel()
			reply(w, 200, b.send(ctx, req.JID, "", req.Staged, req.Caption, req.FileName))
		}
	case r.Method == "POST" && r.URL.Path == "/download":
		var req struct {
			JID string `json:"jid"`
			ID  string `json:"id"`
		}
		if !decode(r, &req) {
			reply(w, 400, map[string]string{"error": "invalid request"})
			return
		}
		v, err := b.download(r.Context(), req.JID, req.ID)
		b.readReply(w, v, err)
	default:
		reply(w, 404, map[string]string{"error": "not found"})
	}
}

func (b *Bridge) readReply(w http.ResponseWriter, v any, err error) {
	if err != nil {
		reply(w, 500, map[string]string{"error": "operation failed"})
	} else {
		reply(w, 200, v)
	}
}

func (b *Bridge) normalJID(jid types.JID) types.JID {
	jid = jid.ToNonAD()
	if jid.Server == types.HiddenUserServer && b.client != nil && b.client.Store != nil {
		alt, err := b.client.Store.GetAltJID(context.Background(), jid)
		if err == nil && !alt.IsEmpty() && alt.Server == types.DefaultUserServer {
			if b.store != nil {
				_ = b.store.MergeDirect(jid.String(), alt.ToNonAD().String())
			}
			return alt.ToNonAD()
		}
	}
	return jid
}

func (b *Bridge) normalizeStored() error {
	if b.client == nil || b.client.Store == nil {
		return nil
	}
	lids, err := b.store.DirectLIDs()
	if err != nil {
		return err
	}
	for _, raw := range lids {
		jid, err := types.ParseJID(raw)
		if err != nil {
			continue
		}
		alt, err := b.client.Store.GetAltJID(context.Background(), jid)
		if err == nil && !alt.IsEmpty() && alt.Server == types.DefaultUserServer {
			if err = b.store.MergeDirect(raw, alt.ToNonAD().String()); err != nil {
				return err
			}
		}
	}
	return nil
}

func (b *Bridge) forget(w http.ResponseWriter) {
	b.mu.Lock()
	b.state = "unpaired"
	b.forgetting = true
	b.mu.Unlock()
	b.cancelPair()
	if b.transport != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		_ = b.transport.Logout(ctx)
		cancel()
	}
	_ = b.store.Close()
	if b.closeAccount != nil {
		_ = b.closeAccount()
	}
	for _, name := range []string{"whatsapp.db", "messages.db"} {
		for _, suffix := range []string{"", "-wal", "-shm"} {
			_ = os.Remove(filepath.Join(b.stateDir, name+suffix))
		}
	}
	for _, name := range []string{"stage", "dl"} {
		_ = os.RemoveAll(filepath.Join(b.runDir, name))
	}
	reply(w, 200, map[string]bool{"ok": true})
	if f, ok := w.(http.Flusher); ok {
		f.Flush()
	}
	if b.stop != nil {
		go b.stop()
	}
}
