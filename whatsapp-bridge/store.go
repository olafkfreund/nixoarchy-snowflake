package main

import (
	"database/sql"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

type MessageStore struct{ db *sql.DB }

type Message struct {
	Seq           int64  `json:"seq"`
	ID            string `json:"id"`
	ChatJID       string `json:"jid"`
	SenderJID     string `json:"sender_jid"`
	SenderName    string `json:"sender_name"`
	At            int64  `json:"at"`
	FromMe        bool   `json:"from_me"`
	Text          string `json:"text"`
	Kind          string `json:"kind"`
	Caption       string `json:"caption"`
	FileName      string `json:"file_name"`
	Size          int64  `json:"size"`
	Edited        bool   `json:"edited"`
	Deleted       bool   `json:"deleted"`
	History       bool   `json:"-"`
	MentionsMe    bool   `json:"mentions_me"`
	DirectPath    string `json:"-"`
	MediaKey      []byte `json:"-"`
	FileSHA256    []byte `json:"-"`
	FileEncSHA256 []byte `json:"-"`
}

func NewMessageStore(path string) (*MessageStore, error) {
	db, err := sql.Open("sqlite3", path)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	_, err = db.Exec(`PRAGMA journal_mode=WAL;
 PRAGMA busy_timeout=5000;
 CREATE TABLE IF NOT EXISTS chats (
  jid TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', is_group INTEGER NOT NULL DEFAULT 0,
  last_at INTEGER NOT NULL DEFAULT 0, unread INTEGER NOT NULL DEFAULT 0
 );
 CREATE TABLE IF NOT EXISTS contacts (jid TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '');
 CREATE TABLE IF NOT EXISTS messages (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL, chat_jid TEXT NOT NULL,
  sender_jid TEXT NOT NULL DEFAULT '', sender_name TEXT NOT NULL DEFAULT '',
  timestamp INTEGER NOT NULL DEFAULT 0, from_me INTEGER NOT NULL DEFAULT 0,
  text TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT '', caption TEXT NOT NULL DEFAULT '',
  file_name TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0,
  direct_path TEXT NOT NULL DEFAULT '', media_key BLOB, file_sha256 BLOB, file_enc_sha256 BLOB,
  history INTEGER NOT NULL DEFAULT 0, deleted INTEGER NOT NULL DEFAULT 0,
  edited INTEGER NOT NULL DEFAULT 0, mentions_me INTEGER NOT NULL DEFAULT 0,
  UNIQUE(id, chat_jid)
 );
 CREATE INDEX IF NOT EXISTS messages_chat_timestamp ON messages(chat_jid, timestamp);`)
	if err != nil {
		db.Close()
		return nil, err
	}
	return &MessageStore{db}, nil
}

func (s *MessageStore) Close() error { return s.db.Close() }

func (s *MessageStore) StoreChat(jid, name string, isGroup bool, at time.Time) error {
	_, err := s.db.Exec(`INSERT INTO chats(jid,name,is_group,last_at) VALUES(?,?,?,?)
 ON CONFLICT(jid) DO UPDATE SET name=CASE WHEN excluded.name != '' THEN excluded.name ELSE chats.name END,
 last_at=max(chats.last_at,excluded.last_at)`, jid, name, isGroup, at.Unix())
	return err
}

func (s *MessageStore) StoreContact(jid, name string) error {
	_, err := s.db.Exec(`INSERT INTO contacts(jid,name) VALUES(?,?) ON CONFLICT(jid) DO UPDATE SET name=excluded.name`, jid, name)
	return err
}

func (s *MessageStore) SetUnread(jid string, unread uint32) error {
	_, err := s.db.Exec(`UPDATE chats SET unread=? WHERE jid=?`, unread, jid)
	return err
}

func (s *MessageStore) StoreMessage(m Message) error {
	if m.ID == "" || m.ChatJID == "" {
		return nil
	}
	_, err := s.db.Exec(`INSERT INTO messages
 (id,chat_jid,sender_jid,sender_name,timestamp,from_me,text,kind,caption,file_name,size,direct_path,media_key,file_sha256,file_enc_sha256,history,deleted,edited,mentions_me)
 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
 ON CONFLICT(id,chat_jid) DO UPDATE SET
 sender_jid=excluded.sender_jid,sender_name=excluded.sender_name,
 timestamp=excluded.timestamp,from_me=excluded.from_me,
 text=CASE WHEN messages.edited=1 AND excluded.edited=0 THEN messages.text ELSE excluded.text END,
 kind=excluded.kind,caption=excluded.caption,file_name=excluded.file_name,size=excluded.size,
 direct_path=excluded.direct_path,media_key=excluded.media_key,file_sha256=excluded.file_sha256,file_enc_sha256=excluded.file_enc_sha256,
 history=messages.history AND excluded.history,edited=messages.edited OR excluded.edited,
 mentions_me=messages.mentions_me OR excluded.mentions_me
 WHERE deleted = 0`, m.ID, m.ChatJID, m.SenderJID, m.SenderName, m.At, m.FromMe, m.Text, m.Kind, m.Caption, m.FileName, m.Size, m.DirectPath, m.MediaKey, m.FileSHA256, m.FileEncSHA256, m.History, m.Deleted, m.Edited, m.MentionsMe)
	return err
}

// Edit changes a stored message's text (or caption). An unknown original or a tombstone is left alone.
func (s *MessageStore) Edit(id, jid, text string) error {
	if id == "" || jid == "" {
		return nil
	}
	_, err := s.db.Exec(`UPDATE messages SET text=CASE WHEN kind IN ('image','video','document') THEN text ELSE ? END,
 caption=CASE WHEN kind IN ('image','video','document') THEN ? ELSE caption END, edited=1
 WHERE id=? AND chat_jid=? AND deleted=0`, text, text, id, jid)
	return err
}

func (s *MessageStore) Tombstone(id, jid string) error {
	if id == "" || jid == "" {
		return nil
	}
	_, err := s.db.Exec(`INSERT INTO messages(id,chat_jid,deleted) VALUES(?,?,1)
 ON CONFLICT(id,chat_jid) DO UPDATE SET text='',kind='',caption='',file_name='',size=0,
 direct_path='',media_key=NULL,file_sha256=NULL,file_enc_sha256=NULL,deleted=1
 WHERE deleted = 0`, id, jid)
	return err
}
