"""#210: hear a summary of an email, and reply to it with a click.

gog's JSON fields, read from real output on p620 (values in fixtures/mail are made up):

- `gog --readonly --json -a <addr> gmail messages search ...`:
  `messages[].{id, threadId, date, internalDateIso, from, subject, labels}`
- `gog --readonly --json -a <addr> gmail get <id>`:
  `headers.{bcc, cc, date, from, in_reply_to, message_id, references, reply_to, subject, to}`, `body` (decoded text),
  `message.{id, threadId, historyId, internalDate, labelIds, snippet, sizeEstimate,
  payload.{mimeType, headers[], parts[].{partId, mimeType, headers[], body.{data, size}}}}`
- `gog auth list --json`: `accounts[].{email, subject, client, auth, scopes, services, created_at}`;
  an account can read mail when "gmail" is in `services`.

Mail code reads only these fields. hostile.json holds the spec's hostile cases, keyed by name, each shaped like `get`.
"""
