# FlameTag Web MVP (QR linked lighters)

This is a simple web app MVP:
- Each lighter has a **token** (engraved/printed next to a QR).
- Scanning the QR opens `/l/<token>`.
- Owners can **claim** a lighter and set:
  - Public message (shown to everyone)
  - Private message (locked behind PIN)
- Anyone can scan and try to unlock the private message with the PIN.

## 1) Run locally

### macOS / Linux
```bash
cd lighterlock_web_mvp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

### Windows (PowerShell)
```powershell
cd lighterlock_web_mvp
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python run.py
```

Open: `http://localhost:5000`

## 2) Add your lighter codes

### Option A: Import existing tokens
1. Set `ADMIN_KEY` in `.env`
2. Run the app
3. Go to `/admin` and paste your tokens (one per line)

### Option B: Generate tokens in the app
- Go to `/admin` and generate tokens (requires `ADMIN_KEY`)

## 3) Make your QR codes point to your domain
When you deploy, your QR links should look like:
`https://YOURDOMAIN/l/AB12CD34`

## Notes
- This MVP uses a single **owner PIN** per lighter (no user accounts yet).
- For production: add rate limiting, stronger auditing, and optional accounts.
