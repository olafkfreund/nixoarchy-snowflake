package main

import (
	"database/sql"
	"strings"
)

type Chat struct {
	JID         string `json:"jid"`
	Name        string `json:"name"`
	IsGroup     bool   `json:"is_group"`
	LastAt      int64  `json:"last_at"`
	Unread      int    `json:"unread"`
	LastPreview string `json:"last_preview"`
}

type Contact struct {
	JID  string `json:"jid"`
	Name string `json:"name"`
}

func boundedLimit(n, fallback int) int {
	if n <= 0 {
		return fallback
	}
	if n > 100 {
		return 100
	}
	return n
}

func (s *MessageStore) Chats(q string, limit int) ([]Chat, error) {
	pattern := "%" + strings.ToLower(q) + "%"
	rows, err := s.db.Query(`SELECT c.jid,c.name,c.is_group,c.last_at,c.unread,
 COALESCE((SELECT CASE WHEN deleted=1 THEN 'Deleted message' WHEN kind!='' THEN kind ELSE text END
 FROM messages WHERE chat_jid=c.jid ORDER BY timestamp DESC,seq DESC LIMIT 1),'')
 FROM chats c WHERE lower(c.name) LIKE ? OR lower(c.jid) LIKE ?
 ORDER BY c.last_at DESC,c.jid LIMIT ?`, pattern, pattern, boundedLimit(limit, 20))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Chat{}
	for rows.Next() {
		var c Chat
		if err = rows.Scan(&c.JID, &c.Name, &c.IsGroup, &c.LastAt, &c.Unread, &c.LastPreview); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

func (s *MessageStore) Contacts(q string) ([]Contact, error) {
	pattern := "%" + strings.ToLower(q) + "%"
	rows, err := s.db.Query(`SELECT jid,max(name) FROM (
 SELECT jid,name FROM contacts WHERE jid LIKE '%@s.whatsapp.net' OR jid LIKE '%@lid'
 UNION ALL SELECT jid,name FROM chats WHERE is_group=0 AND (jid LIKE '%@s.whatsapp.net' OR jid LIKE '%@lid'))
 WHERE lower(name) LIKE ? OR lower(jid) LIKE ? GROUP BY jid ORDER BY name,jid LIMIT 100`, pattern, pattern)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Contact{}
	for rows.Next() {
		var c Contact
		if err = rows.Scan(&c.JID, &c.Name); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

func scanMessage(rows *sql.Rows) (Message, error) {
	var m Message
	err := rows.Scan(&m.Seq, &m.ID, &m.ChatJID, &m.SenderJID, &m.SenderName, &m.At, &m.FromMe, &m.Text, &m.Kind, &m.Caption, &m.FileName, &m.Size, &m.Edited, &m.Deleted, &m.History, &m.MentionsMe)
	return m, err
}

const messageColumns = `seq,id,chat_jid,sender_jid,sender_name,timestamp,from_me,text,kind,caption,file_name,size,edited,deleted,history,mentions_me`

func (s *MessageStore) Thread(jid string, limit int, before int64) ([]Message, error) {
	rows, err := s.db.Query(`SELECT `+messageColumns+` FROM messages WHERE chat_jid=? AND (?=0 OR seq<?)
 ORDER BY seq DESC LIMIT ?`, jid, before, before, boundedLimit(limit, 50))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Message{}
	for rows.Next() {
		m, e := scanMessage(rows)
		if e != nil {
			return nil, e
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

func (s *MessageStore) NewAfter(seq int64) ([]Message, error) {
	rows, err := s.db.Query(`SELECT `+messageColumns+` FROM messages
 WHERE seq>? AND history=0 AND from_me=0 AND deleted=0 AND chat_jid NOT LIKE '%@broadcast' AND chat_jid NOT LIKE '%@newsletter' ORDER BY seq LIMIT 100`, seq)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Message{}
	for rows.Next() {
		m, e := scanMessage(rows)
		if e != nil {
			return nil, e
		}
		m.Text = ""
		m.Caption = ""
		m.SenderName = ""
		m.FileName = ""
		out = append(out, m)
	}
	return out, rows.Err()
}

func (s *MessageStore) LatestSeq() (int64, error) {
	var seq int64
	err := s.db.QueryRow(`SELECT COALESCE(MAX(seq), 0) FROM messages WHERE history=0 AND from_me=0 AND deleted=0`).Scan(&seq)
	return seq, err
}

func (s *MessageStore) SenderName(jid string) string {
	var name string
	_ = s.db.QueryRow(`SELECT COALESCE(NULLIF(contacts.name,''), chats.name, '') FROM (SELECT ? AS jid) AS sender LEFT JOIN contacts ON contacts.jid=sender.jid LEFT JOIN chats ON chats.jid=sender.jid`, jid).Scan(&name)
	return name
}
