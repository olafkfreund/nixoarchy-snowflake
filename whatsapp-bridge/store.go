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
	MimeType      string `json:"-"`
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
  file_name TEXT NOT NULL DEFAULT '', mime_type TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL DEFAULT 0,
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
	rows, err := db.Query(`PRAGMA table_info(messages)`)
	if err != nil {
		db.Close()
		return nil, err
	}
	hasMime := false
	for rows.Next() {
		var cid, notNull, primary int
		var name, kind string
		var defaultValue any
		if err = rows.Scan(&cid, &name, &kind, &notNull, &defaultValue, &primary); err != nil {
			break
		}
		if name == "mime_type" {
			hasMime = true
		}
	}
	if err == nil {
		err = rows.Err()
	}
	rows.Close()
	if err == nil && !hasMime {
		_, err = db.Exec(`ALTER TABLE messages ADD COLUMN mime_type TEXT NOT NULL DEFAULT ''`)
	}
	if err != nil {
		db.Close()
		return nil, err
	}
	return &MessageStore{db}, nil
}

func (s *MessageStore) Close() error { return s.db.Close() }

func (s *MessageStore) DirectLIDs() ([]string, error) {
	rows, err := s.db.Query(`SELECT DISTINCT jid FROM (SELECT jid FROM chats UNION ALL SELECT jid FROM contacts UNION ALL SELECT chat_jid AS jid FROM messages) WHERE jid LIKE '%@lid'`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var jid string
		if err = rows.Scan(&jid); err != nil {
			return nil, err
		}
		out = append(out, jid)
	}
	return out, rows.Err()
}

// MergeDirect moves rows saved before a LID-to-phone mapping became available.
func (s *MessageStore) MergeDirect(lid, phone string) error {
	if lid == phone {
		return nil
	}
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()
	for _, query := range []string{
		`INSERT INTO chats(jid,name,is_group,last_at,unread) SELECT ?,name,0,last_at,unread FROM chats WHERE jid=? ON CONFLICT(jid) DO UPDATE SET name=CASE WHEN chats.name='' THEN excluded.name ELSE chats.name END,last_at=max(chats.last_at,excluded.last_at),unread=max(chats.unread,excluded.unread)`,
		`INSERT INTO contacts(jid,name) SELECT ?,name FROM contacts WHERE jid=? ON CONFLICT(jid) DO UPDATE SET name=CASE WHEN contacts.name='' THEN excluded.name ELSE contacts.name END`,
	} {
		if _, err = tx.Exec(query, phone, lid); err != nil {
			return err
		}
	}
	if _, err = tx.Exec(`UPDATE messages SET text='',kind='',caption='',file_name='',mime_type='',size=0,direct_path='',media_key=NULL,file_sha256=NULL,file_enc_sha256=NULL,deleted=1 WHERE chat_jid=? AND id IN (SELECT id FROM messages WHERE chat_jid=? AND deleted=1)`, phone, lid); err != nil {
		return err
	}
	if _, err = tx.Exec(`UPDATE OR IGNORE messages SET chat_jid=? WHERE chat_jid=?`, phone, lid); err != nil {
		return err
	}
	for _, table := range []string{"messages", "chats", "contacts"} {
		if _, err = tx.Exec(`DELETE FROM `+table+` WHERE `+map[string]string{"messages": "chat_jid", "chats": "jid", "contacts": "jid"}[table]+`=?`, lid); err != nil {
			return err
		}
	}
	return tx.Commit()
}

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
 (id,chat_jid,sender_jid,sender_name,timestamp,from_me,text,kind,caption,file_name,mime_type,size,direct_path,media_key,file_sha256,file_enc_sha256,history,deleted,edited,mentions_me)
 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
 ON CONFLICT(id,chat_jid) DO UPDATE SET
 sender_jid=excluded.sender_jid,sender_name=excluded.sender_name,
 timestamp=excluded.timestamp,from_me=excluded.from_me,
 text=CASE WHEN messages.edited=1 AND excluded.edited=0 THEN messages.text ELSE excluded.text END,
 kind=excluded.kind,caption=excluded.caption,file_name=excluded.file_name,mime_type=excluded.mime_type,size=excluded.size,
 direct_path=excluded.direct_path,media_key=excluded.media_key,file_sha256=excluded.file_sha256,file_enc_sha256=excluded.file_enc_sha256,
 history=messages.history AND excluded.history,edited=messages.edited OR excluded.edited,
 mentions_me=messages.mentions_me OR excluded.mentions_me
 WHERE deleted = 0`, m.ID, m.ChatJID, m.SenderJID, m.SenderName, m.At, m.FromMe, m.Text, m.Kind, m.Caption, m.FileName, m.MimeType, m.Size, m.DirectPath, m.MediaKey, m.FileSHA256, m.FileEncSHA256, m.History, m.Deleted, m.Edited, m.MentionsMe)
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
 ON CONFLICT(id,chat_jid) DO UPDATE SET text='',kind='',caption='',file_name='',mime_type='',size=0,
 direct_path='',media_key=NULL,file_sha256=NULL,file_enc_sha256=NULL,deleted=1
 WHERE deleted = 0`, id, jid)
	return err
}
