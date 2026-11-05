# Deploying to a VPS

This guide sets up the app with Docker Compose. Caddy sits in front of it, obtains a free HTTPS certificate on its own, and is the only thing the internet can reach. The app requires the team password. Without one, it refuses to start.

**You need:**
- A VPS running Ubuntu 22.04/24.04 or Debian 12. 1 GB of RAM is enough.
- A domain, e.g. `screening.yourorg.org`.
- SSH access to the VPS.

---

## 1. Point your domain at the VPS

In your domain's DNS settings, add an **A record**:

| Type | Name | Value |
|---|---|---|
| A | `screening` (or `@` for the bare domain) | your VPS IP |

Wait until `ping screening.yourorg.org` shows your VPS IP. This usually takes a few minutes.

## 2. Prepare the VPS (one time)

SSH in, then:

```bash
# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# log out and back in so the docker group applies

# Firewall: allow only SSH + web
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443
sudo ufw enable
```

## 3. Copy the code to the VPS

**On your Windows PC**, in the project folder:

```bash
git archive -o edes-screening.tar.gz HEAD
scp edes-screening.tar.gz user@YOUR_VPS_IP:~
```

**On the VPS:**

```bash
mkdir -p ~/edes-screening && tar -xzf ~/edes-screening.tar.gz -C ~/edes-screening
cd ~/edes-screening
```

(Alternative: push the repo to a **private** GitHub repository and `git clone` it on the VPS.)

## 4. Configure

```bash
cp deploy/.env.production.example .env
openssl rand -base64 48        # copy the output into SECRET_KEY
nano .env
chmod 600 .env
```

Fill in `DOMAIN`, `ORG_NAME`, `APP_PASSWORD` (12+ characters, a passphrase works well), `SECRET_KEY` and `OPENSANCTIONS_API_KEY`.

## 5. Start

```bash
docker compose up -d --build
docker compose logs -f        # Ctrl+C to stop watching
```

Open `https://screening.yourorg.org`. The first visit may take about 30 seconds while the certificate is issued. Sign in with `APP_PASSWORD`.

## Updating

Copy the new code over, as in step 3 (or run `git pull`), then:

```bash
docker compose up -d --build
```

Your data lives in the Docker volume `app_data`. Rebuilding the app keeps it.

## Backups

The database holds beneficiary data, so back it up:

```bash
sh deploy/backup.sh
```

This saves to `backups/` and keeps the last 30 backups. To run it daily at 02:00, add this line with `crontab -e`:

```
0 2 * * * cd /home/USER/edes-screening && sh deploy/backup.sh >> backups/backup.log 2>&1
```

Copy backups somewhere off the VPS from time to time, and keep them encrypted.

## Using the API from scripts

Set `API_TOKEN` in `.env`, restart, then:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" https://screening.yourorg.org/api/batches
```

## Security notes

- Change `APP_PASSWORD` when staff leave. After changing it, run `docker compose up -d`. To also sign everyone out, change `SECRET_KEY`.
- After 5 wrong passwords, the login locks for 15 minutes per IP address.
- Only ports 22, 80 and 443 are open. The app itself is not exposed directly.
- Keep the VPS updated: `sudo apt update && sudo apt upgrade`.
- Delete batches you no longer need. The home page has a Delete button.

## Troubleshooting

| Problem | Fix |
|---|---|
| `REQUIRE_AUTH is on: set APP_PASSWORD` in the logs | Set `APP_PASSWORD` (12+ characters) in `.env` |
| `SECRET_KEY must be set` | Paste the output of `openssl rand -base64 48` into `SECRET_KEY` |
| Certificate errors | Check that DNS points to the VPS and that ports 80/443 are open, then run `docker compose logs caddy` |
| Screening fails with "API key rejected" | Check `OPENSANCTIONS_API_KEY` |
