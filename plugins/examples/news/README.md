# News

Say “news”, “the news”, “what's the news”, “what is the news”, “headlines”, or “the headlines” to see up to five recent stories from your feeds. Nixi reads the first three titles aloud. Opening a story hands its link to your browser.

This plugin needs network access, so Nixi asks before enabling it. Edit its settings in Settings → Plugins to change `feeds` (up to eight `{ "name": "…", "url": "https://…" }` entries). Missing settings use `defaults.json`: BBC News, The Guardian, and Hacker News. Each feed has 1.5 seconds to respond; failed feeds are counted on the card. Changing plugin files asks for consent again; changing settings does not.

Feeds and redirects must use HTTPS public-looking DNS names. DNS results and links opened in your browser are subject to the browser's own handling.
