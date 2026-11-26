package main

import (
	"path/filepath"
	"testing"
	"time"
)

func testStore(t *testing.T) *MessageStore {
	t.Helper()
	s, err := NewMessageStore(filepath.Join(t.TempDir(), "messages.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.Close() })
	return s
}

func put(t *testing.T, s *MessageStore, id, jid string, at int64, history bool) {
	t.Helper()
	if err := s.StoreMessage(Message{ID: id, ChatJID: jid, At: at, Text: id, History: history}); err != nil {
		t.Fatal(err)
	}
}

func TestTombstoneSurvivesEditAndHistory(t *testing.T) {
	s := testStore(t)
	jid := "123@s.whatsapp.net"
	put(t, s, "one", jid, 1, false)
	if err := s.Tombstone("one", jid); err != nil {
		t.Fatal(err)
	}
	if err := s.StoreMessage(Message{ID: "one", ChatJID: jid, At: 2, Text: "edited", Edited: true}); err != nil {
		t.Fatal(err)
	}
	put(t, s, "one", jid, 3, true)
	rows, err := s.Thread(jid, 50, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 1 || !rows[0].Deleted || rows[0].Text != "" || rows[0].Seq != 1 {
		t.Fatalf("tombstone changed: %+v", rows)
	}
}

func TestCursorAndReadQueries(t *testing.T) {
	s := testStore(t)
	a := "1@s.whatsapp.net"
	b := "2@s.whatsapp.net"
	if err := s.StoreChat(a, "Alice", false, time.Unix(1, 0)); err != nil {
		t.Fatal(err)
	}
	if err := s.StoreChat(b, "Bob", false, time.Unix(2, 0)); err != nil {
		t.Fatal(err)
	}
	if err := s.StoreContact("3@s.whatsapp.net", "Carol"); err != nil {
		t.Fatal(err)
	}
	if err := s.StoreContact("4@g.us", "Group"); err != nil {
		t.Fatal(err)
	}
	put(t, s, "one", a, 1, false)
	put(t, s, "old", a, 2, true)
	put(t, s, "two", a, 3, false)
	put(t, s, "three", b, 4, false)
	chats, err := s.Chats("", 1)
	if err != nil {
		t.Fatal(err)
	}
	if len(chats) != 1 || chats[0].JID != b {
		t.Fatalf("chat sort/limit: %+v", chats)
	}
	chats, err = s.Chats("alice", 20)
	if err != nil {
		t.Fatal(err)
	}
	if len(chats) != 1 || chats[0].JID != a {
		t.Fatalf("chat search: %+v", chats)
	}
	contacts, err := s.Contacts("car")
	if err != nil {
		t.Fatal(err)
	}
	if len(contacts) != 1 || contacts[0].Name != "Carol" {
		t.Fatalf("contacts: %+v", contacts)
	}
	thread, err := s.Thread(a, 2, 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(thread) != 2 || thread[0].ID != "two" || thread[1].ID != "old" {
		t.Fatalf("thread limit/order: %+v", thread)
	}
	thread, err = s.Thread(a, 10, thread[1].Seq)
	if err != nil {
		t.Fatal(err)
	}
	if len(thread) != 1 || thread[0].ID != "one" {
		t.Fatalf("thread before: %+v", thread)
	}
	newer, err := s.NewAfter(0)
	if err != nil {
		t.Fatal(err)
	}
	if len(newer) != 3 || newer[0].Seq >= newer[1].Seq || newer[1].Seq >= newer[2].Seq {
		t.Fatalf("cursor/history: %+v", newer)
	}
	newer, err = s.NewAfter(newer[0].Seq)
	if err != nil {
		t.Fatal(err)
	}
	if len(newer) != 2 || newer[0].ID != "two" {
		t.Fatalf("cursor after: %+v", newer)
	}
}
