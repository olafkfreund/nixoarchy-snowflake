package main

import (
	"context"
	"strings"
	"time"

	"go.mau.fi/whatsmeow"
	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/types"
	"go.mau.fi/whatsmeow/types/events"
	"google.golang.org/protobuf/reflect/protoreflect"
)

type Bridge struct {
	client *whatsmeow.Client
	store  *MessageStore
	state  string
}

func (b *Bridge) HandleEvent(event any) error {
	switch e := event.(type) {
	case *events.Message:
		return b.handleMessage(e, false, "")
	case *events.Contact:
		if e.Action != nil {
			name := e.Action.GetFullName()
			if name == "" {
				name = e.Action.GetFirstName()
			}
			return b.store.StoreContact(e.JID.String(), name)
		}
	case *events.PushName:
		return b.store.StoreContact(e.JID.String(), e.NewPushName)
	case *events.DeleteForMe:
		return b.store.Tombstone(e.MessageID, e.ChatJID.String())
	case *events.HistorySync:
		if e.Data == nil || b.client == nil {
			return nil
		}
		for _, c := range e.Data.GetConversations() {
			jid, err := types.ParseJID(c.GetID())
			if err != nil {
				continue
			}
			name := c.GetDisplayName()
			if name == "" {
				name = c.GetName()
			}
			for _, h := range c.GetMessages() {
				if h.GetMessage() == nil {
					continue
				}
				msg, err := b.client.ParseWebMessage(jid, h.GetMessage())
				if err != nil {
					continue
				}
				if err = b.handleMessage(msg, true, name); err != nil {
					return err
				}
			}
			if err = b.store.SetUnread(jid.String(), c.GetUnreadCount()); err != nil {
				return err
			}
		}
	case *events.LoggedOut:
		b.state = "relink"
	}
	return nil
}

func (b *Bridge) handleMessage(e *events.Message, history bool, name string) error {
	jid := e.Info.Chat.String()
	p := e.Message
	if protocol := p.GetProtocolMessage(); protocol != nil {
		switch protocol.GetType() {
		case waProto.ProtocolMessage_REVOKE:
			return b.store.Tombstone(protocol.GetKey().GetID(), jid)
		case waProto.ProtocolMessage_MESSAGE_EDIT:
			// whatsmeow unwraps EditedMessage into this protocol message: the key names the original
			edited := protocol.GetEditedMessage()
			text := extractText(edited)
			if text == "" {
				var m Message
				mediaInfo(edited, &m)
				text = m.Caption
			}
			return b.store.Edit(protocol.GetKey().GetID(), jid, text)
		}
		return nil
	}
	m := Message{ID: string(e.Info.ID), ChatJID: jid, SenderJID: e.Info.Sender.String(), SenderName: e.Info.PushName,
		At: e.Info.Timestamp.Unix(), FromMe: e.Info.IsFromMe, History: history, Edited: e.IsEdit,
		Text: extractText(p), MentionsMe: b.mentionsMe(p)}
	if m.At < 0 {
		m.At = time.Now().Unix()
	}
	mediaInfo(p, &m)
	if m.Text == "" && m.Kind == "" {
		return nil
	}
	if name == "" && !e.Info.IsGroup {
		name = e.Info.PushName
		if b.client != nil && b.client.Store != nil {
			contact, err := b.client.Store.Contacts.GetContact(context.Background(), e.Info.Chat)
			if err == nil && contact.FullName != "" {
				name = contact.FullName
			}
		}
	}
	if err := b.store.StoreChat(jid, name, e.Info.IsGroup, e.Info.Timestamp); err != nil {
		return err
	}
	return b.store.StoreMessage(m)
}

func extractText(p *waProto.Message) string {
	if p == nil {
		return ""
	}
	if p.GetConversation() != "" {
		return p.GetConversation()
	}
	return p.GetExtendedTextMessage().GetText()
}

func mediaInfo(p *waProto.Message, m *Message) {
	if p == nil {
		return
	}
	if v := p.GetImageMessage(); v != nil {
		m.Kind = "image"
		m.Caption = v.GetCaption()
		m.DirectPath = v.GetDirectPath()
		m.MediaKey = v.GetMediaKey()
		m.FileSHA256 = v.GetFileSHA256()
		m.FileEncSHA256 = v.GetFileEncSHA256()
		m.Size = int64(v.GetFileLength())
		return
	}
	if v := p.GetVideoMessage(); v != nil {
		m.Kind = "video"
		m.Caption = v.GetCaption()
		m.DirectPath = v.GetDirectPath()
		m.MediaKey = v.GetMediaKey()
		m.FileSHA256 = v.GetFileSHA256()
		m.FileEncSHA256 = v.GetFileEncSHA256()
		m.Size = int64(v.GetFileLength())
		return
	}
	if v := p.GetAudioMessage(); v != nil {
		m.Kind = "audio"
		m.DirectPath = v.GetDirectPath()
		m.MediaKey = v.GetMediaKey()
		m.FileSHA256 = v.GetFileSHA256()
		m.FileEncSHA256 = v.GetFileEncSHA256()
		m.Size = int64(v.GetFileLength())
		return
	}
	if v := p.GetDocumentMessage(); v != nil {
		m.Kind = "document"
		m.Caption = v.GetCaption()
		m.FileName = v.GetFileName()
		m.DirectPath = v.GetDirectPath()
		m.MediaKey = v.GetMediaKey()
		m.FileSHA256 = v.GetFileSHA256()
		m.FileEncSHA256 = v.GetFileEncSHA256()
		m.Size = int64(v.GetFileLength())
	}
}

func (b *Bridge) mentionsMe(p *waProto.Message) bool {
	if p == nil || b.client == nil || b.client.Store == nil {
		return false
	}
	own := map[types.JID]bool{}
	for _, jid := range []types.JID{b.client.Store.GetJID(), b.client.Store.GetLID()} {
		if !jid.IsEmpty() {
			own[jid.ToNonAD()] = true
		}
	}
	mentioned := false
	var walk func(protoreflect.Message)
	walk = func(msg protoreflect.Message) {
		if ctx, ok := msg.Interface().(*waProto.ContextInfo); ok {
			for _, raw := range ctx.GetMentionedJID() {
				jid, err := types.ParseJID(strings.TrimSpace(raw))
				if err != nil {
					continue
				}
				jid = jid.ToNonAD()
				if own[jid] {
					mentioned = true
					return
				}
				alt, err := b.client.Store.GetAltJID(context.Background(), jid)
				if err == nil && own[alt.ToNonAD()] {
					mentioned = true
					return
				}
			}
		}
		msg.Range(func(field protoreflect.FieldDescriptor, value protoreflect.Value) bool {
			if mentioned || field.Kind() != protoreflect.MessageKind {
				return !mentioned
			}
			if field.IsList() {
				list := value.List()
				for i := 0; i < list.Len() && !mentioned; i++ {
					walk(list.Get(i).Message())
				}
			} else if field.IsMap() {
				value.Map().Range(func(_ protoreflect.MapKey, item protoreflect.Value) bool { walk(item.Message()); return !mentioned })
			} else {
				walk(value.Message())
			}
			return !mentioned
		})
	}
	walk(p.ProtoReflect())
	return mentioned
}
