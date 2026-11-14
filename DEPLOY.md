# Soorty App: AWS EC2 deployment (Docker + GitHub Actions + PostgreSQL)

**Target:** EC2 `web-server`, `13.233.73.99`, ap-south-1 (Mumbai), Ubuntu 24.04, t3.micro.

The server runs two containers:

| Container | Image | Role |
|---|---|---|
| `soorty-db` | `postgres:16-alpine` | Database. Data lives in the `soorty_pgdata` volume. |
| `soorty-app` | ECR `wastage-management-system` | Django + gunicorn, on host port **8090**. |

Each workflow run works without any stored secret:
1. GitHub Actions gets temporary AWS credentials through **OIDC** by assuming the IAM role `github-actions-wastage-deploy`.
2. It builds the image and pushes it to **Amazon ECR** (`545908811041.dkr.ecr.ap-south-1.amazonaws.com/wastage-management-system`). ECR keeps the last 10 images.
3. It deploys through **AWS SSM Run Command** on the EC2. The server downloads `docker-compose.prod.yml` and `postgres/*.sql` for that commit, pulls the image with its own instance role (`soorty-ec2-ssm`), and restarts the containers.

## 1. One-time server setup

```bash
ssh -i web-server-key.pem ubuntu@13.233.73.99

# Docker (skip this if `docker --version` already works)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu && exit        # log in again after this

sudo mkdir -p /opt/soorty && sudo chown ubuntu:ubuntu /opt/soorty
cd /opt/soorty
nano .env        # paste .env.example and fill in the real values
chmod 600 .env
```

`.env` must contain:
- `SECRET_KEY`. Generate one with `python3 -c "import secrets;print(secrets.token_urlsafe(50))"`.
- `DB_PASSWORD`, a strong password. The DB container creates the user and database with it on its **first** start.
- `ALLOWED_HOSTS=127.0.0.1,localhost,13.233.73.99` (add the domain later).
- `CSRF_TRUSTED_ORIGINS=http://13.233.73.99:8090`.

The workflow also creates a 2 GB swap file if one does not exist yet. A t3.micro has only 1 GB of RAM.

## 2. AWS / GitHub wiring (already done)
No GitHub secrets are needed.

| Item | Value |
|---|---|
| OIDC provider | `token.actions.githubusercontent.com` |
| Deploy role | `arn:aws:iam::545908811041:role/github-actions-wastage-deploy`. Only this repo can assume it. It may push to that ECR repo and run SSM commands on `web-server` only. |
| Instance role | `soorty-ec2-ssm`: `AmazonSSMManagedInstanceCore` plus ECR pull on the repo |
| ECR repo | `wastage-management-system` (scan on push, keeps the last 10 images) |

## 3. Network
- EC2 security group `web-server-sg` has inbound **TCP 8090** open. Later, route port 80/443 through a reverse proxy instead.
- Deploys do not use SSH. Port 22 is only for your own logins.
- PostgreSQL is bound to `127.0.0.1:5432` on the server only and is never exposed. For pgAdmin or DBeaver, use an SSH tunnel:
  `ssh -i web-server-key.pem -L 5432:127.0.0.1:5432 ubuntu@13.233.73.99`

## 4. Deploy
Go to Actions → *Build & Deploy to EC2* → **Run workflow**. To deploy on every push, uncomment `push:` in `.github/workflows/deploy.yml`.

On every start, the app container runs `migrate`, `sync_rbac_pages` and `seed_baseline_roles`. All three are safe to repeat.

First login:
```bash
docker exec -it soorty-app python manage.py createsuperuser
docker exec -it soorty-app python scripts/check_db.py
```
Then edit the new user in User Management and set its division, or set `division` in Django admin.

## 5. Database
- The schema is `postgres/01_schema.sql` and the seed data (finance chart of accounts, settings, voucher types, posting rules) is `postgres/02_seed.sql`. Both run automatically, **only when the DB volume is empty** on first start.
- **Datatex logins:** `act_id_user_vw` is a plain table now (`id_`, `first_`, `pwd_`). Add central users there to use the mapped-login feature. Local Django users work without it.
- **Backup:**
  `docker exec soorty-db pg_dump -U soorty -Fc soorty > soorty_$(date +%F).dump`
- **Restore:**
  `docker exec -i soorty-db pg_restore -U soorty -d soorty --clean < file.dump`
- **Fresh start (deletes ALL data):**
  `docker compose -f docker-compose.prod.yml down -v` and then redeploy.

## Notes
- `core/db.py` is the single PostgreSQL access layer for all raw SQL. It keeps the `:1`/`:name` bind style and the Oracle-style error codes the code already used, so existing error handling still works.
- The old Oracle DDL and scripts are in `scripts/oracle_legacy/`, kept for reference only.
- Local run: put `DB_HOST=localhost` and the DB values in `.env`, load both SQL files with `psql`, then run `python manage.py migrate` and `python manage.py runserver`.
