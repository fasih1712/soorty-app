# Soorty App: AWS EC2 deployment (Docker + GitHub Actions)

Each push to `main` builds the image, pushes it to `ghcr.io/fasih1712/soorty-app`, then pulls it and restarts it on EC2.

## 1. One-time setup on the EC2 server

```bash
sudo mkdir -p /opt/soorty && sudo chown $USER:$USER /opt/soorty
cd /opt/soorty
nano .env        # paste the contents of .env.example and fill in the real values
chmod 600 .env
```

Required `.env` values:
- `SECRET_KEY`: generate one with `python3 -c "import secrets;print(secrets.token_urlsafe(50))"`
- `ALLOWED_HOSTS`: `127.0.0.1,localhost,<EC2-IP>,<domain>`
- `CSRF_TRUSTED_ORIGINS`: `http://<EC2-IP>:8090`, plus the https domain later
- `DB_SERVICE=<new-db-host>:1521/<SERVICE>`: Django uses only this value
- `DB_HOST`, `DB_PORT`, `DB_SERVICE_NAME`, `DB_USER`, `DB_PASSWORD`: raw queries use these
- `ORACLE_CLIENT_LIB`: leave this empty

The app listens on host port **8090**. To change it, add `APP_PORT=xxxx` to `.env`.

## 2. GitHub secrets (repo → Settings → Secrets and variables → Actions)

| Secret | Value |
|---|---|
| `EC2_HOST` | EC2 public IP |
| `EC2_USER` | `ubuntu` / `ec2-user` |
| `EC2_SSH_KEY` | private key contents (whole file) |
| `GHCR_PAT` | GitHub PAT with `read:packages` |

## 3. Network
- EC2 security group: open inbound **8090**, or 80/443 if it sits behind nginx.
- Oracle DB: allow inbound 1521 **from the EC2 instance**. Use an RDS security group rule, an on-prem firewall whitelist, or a VPN.

## 4. First deploy
Push to `main`, or use Actions → *Build & Deploy to EC2* → **Run workflow**.

Test the DB connection from inside the container:
```bash
docker exec -it soorty-app python test_connection.py
```

Django tables (`accounts` app migrations). Run this **only on a new/empty DB**, after checking `showmigrations`:
```bash
docker exec -it soorty-app python manage.py showmigrations
docker exec -it soorty-app python manage.py migrate
docker exec -it soorty-app python manage.py createsuperuser
```
Run the Oracle schema scripts in `Tables/*.sql` on the new DB yourself (SQL Developer / sqlplus).

## Notes
- Thin mode needs Oracle DB **12.1 or newer**. An older DB (11g) needs Oracle Instant Client in the image (thick mode).
- Uploaded files live in the `soorty_media` volume and logs in `soorty_logs`. Both survive redeploys.
- Local Windows run still works: put `ORACLE_CLIENT_LIB=D:\client19c\product\client_1\bin` in your local `.env`.
