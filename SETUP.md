# Google account setup (Gmail, read-only)

Jarvis uses the **installed-app OAuth flow**. Google has no API that lists every
account signed into a browser, so each account is authorized separately: click
**Connect Google account** once per account in the new **Accounts** panel.

## 1. Create a Google Cloud project

1. Go to <https://console.cloud.google.com/> and create (or select) a project.
2. Enable **Gmail API**: *APIs & Services → Library → Gmail API → Enable*.

## 2. Configure the OAuth consent screen

1. *APIs & Services → OAuth consent screen*.
2. User Type: **External** (or Internal if this is a Google Workspace org).
3. Fill in the app name, user support email and developer email.
4. Scopes: add
   - `openid`
   - `https://www.googleapis.com/auth/userinfo.email`
   - `https://www.googleapis.com/auth/userinfo.profile`
   - `https://www.googleapis.com/auth/gmail.readonly`
5. **Test users**: add every Google account you want Jarvis to read. While the
   app is in "Testing", only these accounts can authorize.
6. Save and continue. Publishing is not required for personal use.

## 3. Create the OAuth client

1. *APIs & Services → Credentials → Create credentials → OAuth client ID*.
2. Application type: **Desktop app**.
3. Name it (e.g. `Jarvis Desktop`).
4. Download the JSON and save it as:

   ```
   ~/MyProjects/Ultron/config/credentials.json
   ```

   You can override the location with `GOOGLE_CREDENTIALS_PATH` (`.env`) or
   `google_credentials_path` in `config/api_keys.json`.

## 4. Connect accounts

1. Start Jarvis and open the **Accounts** button in the sidebar.
2. Click **Connect Google account**. Your system browser opens Google's consent
   page; the redirect is caught on `http://localhost:<random-port>`.
3. Approve access. The account appears in the list.
4. Repeat for each additional account — one OAuth run = one account.

## Storage and privacy

- Refresh tokens go to the OS keyring (`keyring`). If unavailable, an encrypted
  local file `config/google_tokens.enc` is used instead.
- Only non-secret metadata (email, name, avatar URL, dates, sync state) is kept
  in `memory/google_accounts.json`.
- Emails are cached locally in `memory/gmail.db` (SQLite + FTS5). Nothing is
  uploaded anywhere.
- `credentials.json`, token files and the DB are gitignored.

## Sync behaviour

- First sync imports the last **30 days** (configurable: `gmail_sync_days` in
  `config/api_keys.json`).
- Later syncs use Gmail `historyId` for incremental updates.
- 429/5xx responses are retried with exponential backoff.
- If a refresh token is revoked, the account is marked **needs re-auth** in the
  panel — click **Connect Google account** again for that account.

## Jarvis tools

The LLM can call `search_emails`, `get_email`, `list_recent_emails` and
`summarize_unread`. All are **read-only**. Sending and deleting mail are
intentionally not implemented and would require explicit confirmation.
