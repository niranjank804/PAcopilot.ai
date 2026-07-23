# Production Deployment — HTTPS on a self-managed VPS

Prepared ahead of actually provisioning a server, so it's ready to follow
once you have one. Written for a plain Ubuntu 22.04+ VPS (AWS EC2,
DigitalOcean, Azure VM, etc.) — no Docker required, since this repo doesn't
have Dockerfiles today; this uses systemd services + nginx directly, which
is simpler to reason about for a first production deployment.

## 0. Prerequisites

- A VPS with a public IP, SSH access, Ubuntu 22.04+.
- A domain name, with an **A record** pointing at the VPS's IP (e.g.
  `pacopilot.yourdomain.com` → `203.0.113.10`). Let's Encrypt needs this to
  already resolve correctly before it will issue a certificate — set the
  DNS record first and wait for it to propagate (`dig pacopilot.yourdomain.com`
  should return the VPS IP) before running certbot.
- Decide your domain layout. Simplest: one domain serving the frontend,
  with the API reverse-proxied under `/api` on the same domain (avoids
  needing a second subdomain + certificate, and avoids a second CORS
  origin to manage). This guide assumes that shape:
  - `https://pacopilot.yourdomain.com/` → Next.js frontend
  - `https://pacopilot.yourdomain.com/api/` → FastAPI backend

## 1. System packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv postgresql nginx certbot python3-certbot-nginx git

# Node 20+ (via NodeSource)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

If you'd rather not run Postgres on the same VPS, use a managed Postgres
instance (RDS, DigitalOcean Managed DB, etc.) and skip installing
`postgresql` locally — just point `DATABASE_HOST` at it in step 3.

## 2. Get the code onto the server

```bash
sudo mkdir -p /srv/pa-copilot
sudo chown $USER:$USER /srv/pa-copilot
git clone <your-repo-url> /srv/pa-copilot
cd /srv/pa-copilot
```

## 3. Backend setup

```bash
cd /srv/pa-copilot/backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install gunicorn   # production process manager for uvicorn workers
```

Create `/srv/pa-copilot/backend/.env` — **do not commit this file**. Copy
your working local values for the API keys, and update these for
production specifically:

```ini
DEBUG=False

DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=enterprise_ai
DATABASE_USER=<a dedicated prod db role — don't reuse a local dev superuser>
DATABASE_PASSWORD=<a real generated secret>

SECRET_KEY=<generate a new one: python -c "import secrets; print(secrets.token_hex(32))">

# Must match your real domain exactly, scheme included:
CORS_ALLOWED_ORIGINS=["https://pacopilot.yourdomain.com"]
FRONTEND_URL=https://pacopilot.yourdomain.com

TM1_CREDENTIALS_KEY=<generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
ANTHROPIC_API_KEY=<your key>
OPENAI_API_KEY=<your key>
GOOGLE_OAUTH_CLIENT_ID=<same client ID as local — see step 6 for the origin you must add>

# Only if you've set up real SMTP for password reset emails:
SMTP_HOST=...
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM_EMAIL=no-reply@yourdomain.com
```

Run migrations and seed the permission/role tables (same scripts used in
dev):

```bash
python -m alembic upgrade head
python scripts/seed_permissions.py
python scripts/seed_roles.py
```

Create `/etc/systemd/system/pa-copilot-backend.service`:

```ini
[Unit]
Description=PA-Copilot backend (FastAPI)
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/srv/pa-copilot/backend
Environment=PATH=/srv/pa-copilot/backend/.venv/bin
ExecStart=/srv/pa-copilot/backend/.venv/bin/gunicorn src.main:app \
  -k uvicorn.workers.UvicornWorker \
  --workers 4 \
  --bind 127.0.0.1:8004
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /srv/pa-copilot/backend
sudo systemctl daemon-reload
sudo systemctl enable --now pa-copilot-backend
sudo systemctl status pa-copilot-backend   # confirm it's running before continuing
```

## 4. Frontend setup

```bash
cd /srv/pa-copilot/frontend
npm ci
```

Create `/srv/pa-copilot/frontend/.env.local`:

```ini
NEXT_PUBLIC_API_URL=https://pacopilot.yourdomain.com/api
NEXT_PUBLIC_GOOGLE_CLIENT_ID=<same client ID>
```

```bash
npm run build
```

Create `/etc/systemd/system/pa-copilot-frontend.service`:

```ini
[Unit]
Description=PA-Copilot frontend (Next.js)
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/srv/pa-copilot/frontend
ExecStart=/usr/bin/npm run start -- --port 3000
Restart=always
RestartSec=5
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /srv/pa-copilot/frontend
sudo systemctl daemon-reload
sudo systemctl enable --now pa-copilot-frontend
sudo systemctl status pa-copilot-frontend
```

## 5. nginx reverse proxy + Let's Encrypt

Create `/etc/nginx/sites-available/pa-copilot`:

```nginx
server {
    listen 80;
    server_name pacopilot.yourdomain.com;

    location /api/ {
        proxy_pass http://127.0.0.1:8004/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:3000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/pa-copilot /etc/nginx/sites-enabled/
sudo nginx -t   # check the config before reloading
sudo systemctl reload nginx
```

Now get a real certificate — certbot edits the nginx config in place to
add the HTTPS server block, HTTP→HTTPS redirect, and sets up auto-renewal:

```bash
sudo certbot --nginx -d pacopilot.yourdomain.com
sudo systemctl status certbot.timer   # confirm auto-renewal is scheduled
```

Verify: `https://pacopilot.yourdomain.com` should now load the app with a
valid certificate (green padlock), and `https://pacopilot.yourdomain.com/api/health`
should return `{"status":"healthy"}`.

## 6. Update Google OAuth for the production origin

In Google Cloud Console → APIs & Services → Credentials → your OAuth
client → **Authorized JavaScript origins**, add:

```
https://pacopilot.yourdomain.com
```

(Keep `http://localhost:3000` in the list too if you still want local dev
sign-in to keep working.) If your consent screen is still in "Testing"
mode, either publish it or make sure every real user's Google account is
added under **Test users** — otherwise their sign-in will be blocked by
Google before it ever reaches your app.

## 7. Basic hardening (do before exposing this to real users)

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

- Don't expose Postgres (`5432`) externally — leave it bound to `localhost`
  (the default) unless you have a specific reason to reach it remotely, in
  which case restrict it to your own IP via `pg_hba.conf`, not `0.0.0.0`.
- Rotate `SECRET_KEY`, `DATABASE_PASSWORD`, and `TM1_CREDENTIALS_KEY` to
  values generated fresh for production — never reuse the local dev values
  from `backend/.env`.
- `backend/.env` and `frontend/.env.local` on the server should be
  readable only by the `www-data` user (`chmod 600`), and never committed
  to git.

## 8. Redeploying after a code change

```bash
cd /srv/pa-copilot && git pull
cd backend && source .venv/bin/activate && pip install -r requirements.txt && python -m alembic upgrade head
sudo systemctl restart pa-copilot-backend
cd ../frontend && npm ci && npm run build
sudo systemctl restart pa-copilot-frontend
```

## Not covered here (out of scope until needed)

- Zero-downtime deploys / blue-green — fine to accept a few seconds of
  downtime on `systemctl restart` until traffic volume justifies more.
- Horizontal scaling / load balancing across multiple VPS instances.
- Managed secrets storage (Vault, AWS Secrets Manager) — plain `.env`
  files with restricted permissions are adequate for a single-VPS setup.
- CI/CD automation of the redeploy steps in section 8 — worth doing once
  deploys happen often enough to justify it.
