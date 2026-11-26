package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"go.mau.fi/whatsmeow"
	waProto "go.mau.fi/whatsmeow/binary/proto"
	"go.mau.fi/whatsmeow/types"
	"golang.org/x/sys/unix"
	"google.golang.org/protobuf/proto"
)

type WAClient interface {
	Connect() error
	IsConnected() bool
	IsLoggedIn() bool
	GetQRChannel(context.Context) (<-chan whatsmeow.QRChannelItem, error)
	SendMessage(context.Context, types.JID, *waProto.Message, ...whatsmeow.SendRequestExtra) (whatsmeow.SendResponse, error)
	Upload(context.Context, []byte, whatsmeow.MediaType) (whatsmeow.UploadResponse, error)
	DownloadMediaWithPath(context.Context, string, []byte, []byte, []byte, whatsmeow.MediaType, string, bool) ([]byte, error)
	Logout(context.Context) error
}

type sendResult struct {
	Result string `json:"result"`
	ID     string `json:"id,omitempty"`
}

var stagedPattern = regexp.MustCompile(`^[A-Za-z0-9_-]{16,64}$`)
var extPattern = regexp.MustCompile(`^[a-z0-9]{1,8}$`)

func direct(jid types.JID) bool {
	return jid.User != "" && (jid.Server == types.DefaultUserServer || jid.Server == types.HiddenUserServer)
}

func stagedFile(run, name string, max int64) ([]byte, error) {
	if !stagedPattern.MatchString(name) {
		return nil, errors.New("invalid staged name")
	}
	dir, err := unix.Open(filepath.Join(run, "stage"), unix.O_RDONLY|unix.O_DIRECTORY|unix.O_CLOEXEC, 0)
	if err != nil {
		return nil, err
	}
	defer unix.Close(dir)
	fd, err := unix.Openat(dir, name, unix.O_RDONLY|unix.O_NOFOLLOW|unix.O_CLOEXEC, 0)
	if err != nil {
		return nil, err
	}
	f := os.NewFile(uintptr(fd), name)
	defer f.Close()
	var st unix.Stat_t
	if err = unix.Fstat(fd, &st); err != nil {
		return nil, err
	}
	if st.Mode&unix.S_IFMT != unix.S_IFREG || st.Size > max || st.Size < 0 {
		return nil, errors.New("invalid staged file")
	}
	data, err := io.ReadAll(io.LimitReader(f, max+1))
	if err != nil || int64(len(data)) > max {
		return nil, errors.New("staged file changed")
	}
	return data, nil
}

// safeName keeps a display file name for the recipient: the base name, no control characters, at most 128 bytes.
func safeName(name string) string {
	name = filepath.Base(strings.ReplaceAll(name, "\\", "/"))
	name = strings.Map(func(r rune) rune {
		if r < 0x20 || r == 0x7f {
			return -1
		}
		return r
	}, name)
	if name == "." || name == "/" || name == ".." || name == "" {
		return "attachment"
	}
	for len(name) > 128 {
		name = name[:len(name)-1]
	}
	return strings.ToValidUTF8(name, "")
}

func (b *Bridge) send(ctx context.Context, raw, text, staged, caption, fileName string) sendResult {
	no := sendResult{Result: "not_sent"}
	jid, err := types.ParseJID(raw)
	if err != nil || !direct(jid) || b.transport == nil || !b.transport.IsLoggedIn() || !b.transport.IsConnected() {
		return no
	}
	jid = b.normalJID(jid)
	msg := &waProto.Message{}
	if staged == "" {
		if text == "" {
			return no
		}
		msg.Conversation = proto.String(text)
	} else {
		data, err := stagedFile(b.runDir, staged, b.maxFile)
		if err != nil {
			return no
		}
		fileName = safeName(fileName)
		mimeType := mime.TypeByExtension(filepath.Ext(fileName))
		if mimeType == "" {
			mimeType = http.DetectContentType(data)
		}
		upload, err := b.transport.Upload(ctx, data, whatsmeow.MediaDocument)
		if err != nil {
			return no
		}
		msg.DocumentMessage = &waProto.DocumentMessage{URL: proto.String(upload.URL), DirectPath: proto.String(upload.DirectPath), MediaKey: upload.MediaKey, FileSHA256: upload.FileSHA256, FileEncSHA256: upload.FileEncSHA256, FileLength: proto.Uint64(upload.FileLength), Mimetype: proto.String(mimeType), Caption: proto.String(caption), FileName: proto.String(fileName)}
	}
	resp, err := b.transport.SendMessage(ctx, jid, msg)
	if staged != "" {
		_ = os.Remove(filepath.Join(b.runDir, "stage", staged))
	}
	result := sendResult{Result: "unknown"}
	if err == nil {
		result.Result = "sent"
		result.ID = string(resp.ID)
	}
	if result.ID != "" {
		m := Message{ID: result.ID, ChatJID: jid.String(), At: time.Now().Unix(), FromMe: true, Text: text, Caption: caption}
		if staged != "" {
			m.Kind = "document"
			m.FileName = fileName
		}
		_ = b.store.StoreChat(jid.String(), "", false, time.Now())
		_ = b.store.StoreMessage(m)
	}
	return result
}

func downloadExt(mimeType string) string {
	exts, _ := mime.ExtensionsByType(mimeType)
	if len(exts) > 0 {
		ext := strings.TrimPrefix(exts[0], ".")
		if extPattern.MatchString(ext) {
			return ext
		}
	}
	return "bin"
}

func mediaType(kind string) whatsmeow.MediaType {
	switch kind {
	case "image":
		return whatsmeow.MediaImage
	case "video":
		return whatsmeow.MediaVideo
	case "audio":
		return whatsmeow.MediaAudio
	default:
		return whatsmeow.MediaDocument
	}
}

func (b *Bridge) download(ctx context.Context, raw, id string) (any, error) {
	jid, err := types.ParseJID(raw)
	if err != nil || id == "" {
		return nil, errors.New("invalid message")
	}
	var m Message
	err = b.store.db.QueryRow(`SELECT direct_path,media_key,file_sha256,file_enc_sha256,mime_type,kind,file_name,size FROM messages WHERE chat_jid=? AND id=? AND deleted=0`, b.normalJID(jid).String(), id).Scan(&m.DirectPath, &m.MediaKey, &m.FileSHA256, &m.FileEncSHA256, &m.MimeType, &m.Kind, &m.FileName, &m.Size)
	if err != nil || m.DirectPath == "" || b.transport == nil {
		return nil, errors.New("media unavailable")
	}
	if m.Size > b.maxFile {
		return nil, errors.New("media too large")
	}
	data, err := b.transport.DownloadMediaWithPath(ctx, m.DirectPath, m.FileEncSHA256, m.FileSHA256, m.MediaKey, mediaType(m.Kind), "", false)
	if err != nil {
		return nil, err
	}
	if int64(len(data)) > b.maxFile {
		return nil, errors.New("media too large")
	}
	random, err := randomHex(8)
	if err != nil {
		return nil, err
	}
	name := fmt.Sprintf("%d-%s.%s", time.Now().UnixMilli(), random, downloadExt(m.MimeType))
	path := filepath.Join(b.runDir, "dl", name)
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return nil, err
	}
	if _, err = f.Write(data); err == nil {
		err = f.Sync()
	}
	if closeErr := f.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		_ = os.Remove(path)
		return nil, err
	}
	return map[string]string{"file": name, "name": m.FileName}, nil
}
