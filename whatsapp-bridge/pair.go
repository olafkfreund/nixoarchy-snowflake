package main

import (
	"context"
	"encoding/base64"
	"net/http"
	"strings"
	"time"

	"github.com/skip2/go-qrcode"
	"go.mau.fi/whatsmeow"
)

type pairSession struct {
	cancel  context.CancelFunc
	png     string
	expires time.Time
}

func (b *Bridge) connect() {
	if b.transport == nil {
		return
	}
	if err := b.transport.Connect(); err != nil {
		b.mu.Lock()
		if strings.Contains(strings.ToLower(err.Error()), "405") || strings.Contains(strings.ToLower(err.Error()), "client outdated") {
			b.state = "outdated"
		} else {
			b.state = "error"
		}
		b.mu.Unlock()
	}
}

func (b *Bridge) cancelPair() {
	b.mu.Lock()
	if b.pair != nil {
		b.pair.cancel()
		b.pair = nil
	}
	if b.state == "pairing" {
		b.state = "unpaired"
	}
	b.mu.Unlock()
}

func (b *Bridge) pairReply(w http.ResponseWriter) {
	b.mu.Lock()
	if b.pair == nil {
		if b.transport == nil || b.transport.IsLoggedIn() || (b.client != nil && b.client.Store != nil && !b.client.Store.ID.IsEmpty()) {
			b.mu.Unlock()
			reply(w, 409, map[string]string{"error": "already paired"})
			return
		}
		ctx, cancel := context.WithCancel(context.Background())
		channel, err := b.transport.GetQRChannel(ctx)
		if err != nil {
			cancel()
			b.state = "error"
			b.mu.Unlock()
			reply(w, 503, map[string]string{"error": "pair unavailable"})
			return
		}
		p := &pairSession{cancel: cancel}
		b.pair = p
		b.state = "pairing"
		go b.watchPair(p, channel)
		go b.connect()
	}
	p := b.pair
	b.mu.Unlock()
	deadline := time.NewTimer(5 * time.Second)
	defer deadline.Stop()
	for {
		b.mu.Lock()
		active := b.pair == p
		png, expires := p.png, p.expires
		b.mu.Unlock()
		if png != "" && time.Now().Before(expires) {
			reply(w, 200, map[string]any{"png": png, "expires_at": expires.Format(time.RFC3339)})
			return
		}
		if !active {
			reply(w, 503, map[string]string{"error": "pair ended"})
			return
		}
		select {
		case <-deadline.C:
			reply(w, 503, map[string]string{"error": "pair pending"})
			return
		case <-time.After(20 * time.Millisecond):
		}
	}
}

func (b *Bridge) watchPair(p *pairSession, channel <-chan whatsmeow.QRChannelItem) {
	for item := range channel {
		if item.Event == whatsmeow.QRChannelEventCode {
			png, err := qrcode.Encode(item.Code, qrcode.Medium, 256)
			if err != nil {
				continue
			}
			b.mu.Lock()
			if b.pair == p {
				p.png = "data:image/png;base64," + base64.StdEncoding.EncodeToString(png)
				p.expires = time.Now().Add(item.Timeout)
			}
			b.mu.Unlock()
			continue
		}
		b.mu.Lock()
		if b.pair == p {
			p.cancel()
			b.pair = nil
			switch item.Event {
			case "success":
				b.state = "connecting"
			case "err-client-outdated":
				b.state = "outdated"
			default:
				b.state = "error"
			}
		}
		b.mu.Unlock()
		return
	}
	b.mu.Lock()
	if b.pair == p {
		p.cancel()
		b.pair = nil
		b.state = "error"
	}
	b.mu.Unlock()
}
