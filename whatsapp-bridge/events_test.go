package main

import (
	"testing"

	"go.mau.fi/whatsmeow"
	waProto "go.mau.fi/whatsmeow/binary/proto"
	waStore "go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
)

func TestRevokeAndDeleteForMe(t *testing.T) {
	s := testStore(t)
	b := Bridge{store: s, state: "ready"}
	jid := types.JID{User: "123", Server: "s.whatsapp.net"}
	put(t, s, "one", jid.String(), 1, false)
	id := "one"
	revoke := &events.Message{Info: types.MessageInfo{MessageSource: types.MessageSource{Chat: jid}},
		Message: &waProto.Message{ProtocolMessage: &waProto.ProtocolMessage{Type: waProto.ProtocolMessage_REVOKE.Enum(), Key: &waProto.MessageKey{ID: &id}}}}
	if err := b.HandleEvent(revoke); err != nil {
		t.Fatal(err)
	}
	if err := b.HandleEvent(&events.DeleteForMe{ChatJID: jid, MessageID: "two"}); err != nil {
		t.Fatal(err)
	}
	put(t, s, "one", jid.String(), 2, true)
	put(t, s, "two", jid.String(), 3, true)
	rows, err := s.Thread(jid.String(), 50, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 2 || !rows[0].Deleted || !rows[1].Deleted || rows[0].Text != "" || rows[1].Text != "" {
		t.Fatalf("revoke replay: %+v", rows)
	}
	if err := b.HandleEvent(&events.LoggedOut{}); err != nil {
		t.Fatal(err)
	}
	if b.state != "relink" {
		t.Fatalf("state: %q", b.state)
	}
}

func TestEditUpdatesOriginalKey(t *testing.T) {
	s := testStore(t)
	b := Bridge{store: s}
	jid := types.JID{User: "123", Server: "s.whatsapp.net"}
	put(t, s, "one", jid.String(), 1, false)
	text, orig := "changed", "one"
	// the shape whatsmeow delivers after unwrapping EditedMessage: a MESSAGE_EDIT protocol message keyed to the original
	e := &events.Message{Info: types.MessageInfo{MessageSource: types.MessageSource{Chat: jid}, ID: "edit-event-id"}, IsEdit: true,
		Message: &waProto.Message{ProtocolMessage: &waProto.ProtocolMessage{Type: waProto.ProtocolMessage_MESSAGE_EDIT.Enum(),
			Key: &waProto.MessageKey{ID: &orig}, EditedMessage: &waProto.Message{Conversation: &text}}}}
	if err := b.HandleEvent(e); err != nil {
		t.Fatal(err)
	}
	rows, err := s.Thread(jid.String(), 50, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 1 || rows[0].Text != text || !rows[0].Edited || rows[0].Seq != 1 {
		t.Fatalf("edit: %+v", rows)
	}
	if err := s.Tombstone("one", jid.String()); err != nil {
		t.Fatal(err)
	}
	if err := b.HandleEvent(e); err != nil { // an edit after a revoke must not bring text back
		t.Fatal(err)
	}
	if rows, _ := s.Thread(jid.String(), 50, 0); len(rows) != 1 || rows[0].Text != "" || !rows[0].Deleted {
		t.Fatalf("edit after revoke: %+v", rows)
	}
}

func TestMentionsMeAcrossOwnAddresses(t *testing.T) {
	pn := types.JID{User: "123", Server: "s.whatsapp.net"}
	lid := types.JID{User: "456", Server: "lid"}
	b := Bridge{client: &whatsmeow.Client{Store: &waStore.Device{ID: &pn, LID: lid}}}
	for _, mentioned := range []string{pn.String(), lid.String()} {
		p := &waProto.Message{ImageMessage: &waProto.ImageMessage{ContextInfo: &waProto.ContextInfo{MentionedJID: []string{mentioned}}}}
		if !b.mentionsMe(p) {
			t.Fatalf("missed mention of own address")
		}
	}
}
