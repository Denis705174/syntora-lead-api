"""Upload lead-api to the REG.Cloud VPS and install nginx + systemd.

Secrets come from env:
  VPS_HOST, VPS_USER, VPS_KEY (default ~/.ssh/syntora_vps) or VPS_PASSWORD
  RENDER_API_KEY (to copy production secrets)
"""

from __future__ import annotations

import io
import json
import os
import posixpath
import sys
import time
from pathlib import Path

import httpx
import paramiko

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", "data", ".pytest_cache"}
SKIP_FILES = {".env", "stress_results.json"}
SKIP_SUFFIXES = {".pyc", ".db"}


def ssh_connect() -> paramiko.SSHClient:
    host = os.environ["VPS_HOST"]
    user = os.environ.get("VPS_USER", "root")
    key_file = os.environ.get("VPS_KEY", str(Path.home() / ".ssh" / "syntora_vps"))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if Path(key_file).is_file():
        client.connect(host, username=user, key_filename=key_file, timeout=30,
                       allow_agent=False, look_for_keys=False)
    else:
        client.connect(host, username=user, password=os.environ["VPS_PASSWORD"], timeout=30,
                       allow_agent=False, look_for_keys=False)
    return client


def run(client: paramiko.SSHClient, command: str, timeout: int = 180) -> str:
    print(f"$ {command}", flush=True)
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out[-2000:], flush=True)
    if code != 0:
        raise RuntimeError(f"exit {code}: {command}\n{err[-2000:]}")
    return out


def fetch_render_env() -> dict[str, str]:
    key = os.environ["RENDER_API_KEY"]
    sid = "srv-dachh72jnfac73cje1kg"
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    with httpx.Client(timeout=60.0, headers=headers) as http:
        items = http.get(
            f"https://api.render.com/v1/services/{sid}/env-vars",
            params={"limit": 50},
        )
        items.raise_for_status()
        env: dict[str, str] = {}
        for item in items.json():
            row = item.get("envVar", item)
            env[str(row.get("key"))] = str(row.get("value") or "")
    return env


def iter_local_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.name in SKIP_FILES or path.suffix in SKIP_SUFFIXES:
            continue
        files.append(path)
    return files


def upload_tree(sftp: paramiko.SFTPClient) -> None:
    remote_root = "/opt/syntora/lead-api"
    for path in iter_local_files():
        rel = path.relative_to(ROOT).as_posix()
        remote = posixpath.join(remote_root, rel)
        parent = posixpath.dirname(remote)
        run_mkdir = parent
        parts = []
        for piece in run_mkdir.split("/"):
            if not piece:
                continue
            parts.append(piece)
            current = "/" + "/".join(parts)
            try:
                sftp.stat(current)
            except FileNotFoundError:
                sftp.mkdir(current)
        sftp.put(str(path), remote)
        print(f"put {rel}", flush=True)


def quote_env(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def build_env_file(render: dict[str, str]) -> str:
    values = {
        "BOT_TOKEN": render.get("BOT_TOKEN", ""),
        "CHAT_ID": render.get("CHAT_ID", "815564766"),
        "ALLOWED_ORIGINS": "https://syntora.space,https://www.syntora.space",
        "DB_PATH": "/var/lib/syntora/leads.db",
        "BOT_DB_PATH": "/var/lib/syntora/bot_leads.db",
        # Keep empty: this REG.Cloud DC cannot reach api.telegram.org, so bots stay on Render.
        "WEBHOOK_BASE_URL": "",
        "TELEGRAM_NOTIFY": "false",
        "LEAD_RELAY_URL": "https://syntora-lead-api-1.onrender.com/internal/lead-notify",
        "LEAD_RELAY_SECRET": render.get("LEAD_RELAY_SECRET", ""),
        "KITCHEN_BOT_TOKEN": render.get("KITCHEN_BOT_TOKEN", ""),
        "KITCHEN_MESSAGE_LIMIT": render.get("KITCHEN_MESSAGE_LIMIT", "20"),
        "OPENAI_API_KEY": render.get("OPENAI_API_KEY", ""),
        "OPENAI_BASE_URL": render.get(
            "OPENAI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ),
        "OPENAI_MODEL": render.get("OPENAI_MODEL", "gemini-3.6-flash"),
        "OPENAI_MODEL_FALLBACK": render.get("OPENAI_MODEL_FALLBACK", "gemini-3.1-flash-lite"),
        "SPREADSHEET_ID": render.get("SPREADSHEET_ID", ""),
        "GOOGLE_CREDS_JSON": render.get("GOOGLE_CREDS_JSON", ""),
        "YOUGILE_API_KEY": render.get("YOUGILE_API_KEY", ""),
        "YOUGILE_COLUMN_ID": render.get("YOUGILE_COLUMN_ID", ""),
        "YOUGILE_ASSIGNEE_ID": render.get("YOUGILE_ASSIGNEE_ID", ""),
        "YOUGILE_API_BASE": render.get("YOUGILE_API_BASE", "https://ru.yougile.com/api-v2"),
    }
    required = {"BOT_TOKEN", "KITCHEN_BOT_TOKEN", "OPENAI_API_KEY", "LEAD_RELAY_SECRET"}
    missing = [k for k, v in values.items() if not v and k in required]
    if missing:
        raise RuntimeError(f"missing secrets from Render: {missing}")
    return "\n".join(f"{key}={quote_env(val)}" for key, val in values.items()) + "\n"


NGINX = """
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name api.syntora.space 194.226.123.243;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        client_max_body_size 2m;
    }
}
"""

UNIT = """
[Unit]
Description=Syntora lead API and Telegram bots
After=network.target

[Service]
Type=simple
User=syntora
Group=syntora
WorkingDirectory=/opt/syntora/lead-api
EnvironmentFile=/opt/syntora/lead-api/.env
ExecStart=/opt/syntora/lead-api/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8080 --workers 1
Restart=always
RestartSec=3
LimitNOFILE=4096

[Install]
WantedBy=multi-user.target
"""


def put_text(sftp: paramiko.SFTPClient, remote: str, text: str, mode: int = 0o644) -> None:
    with sftp.file(remote, "w") as handle:
        handle.write(text)
    sftp.chmod(remote, mode)


def main() -> int:
    print("fetching Render env...", flush=True)
    render = fetch_render_env()
    print("render keys:", ", ".join(sorted(render)), flush=True)
    env_text = build_env_file(render)

    client = ssh_connect()
    try:
        run(client, "mkdir -p /opt/syntora/lead-api /var/lib/syntora /etc/nginx/sites-available")
        sftp = client.open_sftp()
        try:
            upload_tree(sftp)
            put_text(sftp, "/opt/syntora/lead-api/.env", env_text, 0o600)
            put_text(sftp, "/etc/nginx/sites-available/syntora-api", NGINX.strip() + "\n")
            put_text(sftp, "/etc/systemd/system/syntora-lead-api.service", UNIT.strip() + "\n")
        finally:
            sftp.close()

        bootstrap = r"""
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if ! swapon --show | grep -q .; then
  if [ ! -f /swapfile ]; then
    fallocate -l 1G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=1024
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile || true
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
apt-get update -y
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx ufw
id syntora >/dev/null 2>&1 || useradd --system --home /opt/syntora --shell /usr/sbin/nologin syntora
chown -R syntora:syntora /opt/syntora /var/lib/syntora
chmod 700 /var/lib/syntora
chmod 600 /opt/syntora/lead-api/.env
python3 -m venv /opt/syntora/lead-api/.venv
/opt/syntora/lead-api/.venv/bin/pip install --upgrade pip
/opt/syntora/lead-api/.venv/bin/pip install -r /opt/syntora/lead-api/requirements.txt
rm -f /etc/nginx/sites-enabled/default
ln -sfn /etc/nginx/sites-available/syntora-api /etc/nginx/sites-enabled/syntora-api
nginx -t
systemctl daemon-reload
systemctl enable --now syntora-lead-api
systemctl enable --now nginx
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
systemctl restart syntora-lead-api nginx
sleep 2
curl -fsS http://127.0.0.1:8080/health
echo
systemctl is-active syntora-lead-api nginx
"""
        # Write bootstrap remotely to avoid quoting hell
        sftp = client.open_sftp()
        try:
            put_text(sftp, "/tmp/syntora-bootstrap.sh", bootstrap, 0o700)
        finally:
            sftp.close()
        run(client, "bash /tmp/syntora-bootstrap.sh", timeout=600)
        run(client, "curl -fsS -H 'Host: api.syntora.space' http://127.0.0.1/health")
    finally:
        client.close()
    print("VPS install finished", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
