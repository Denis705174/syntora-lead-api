"""Quick VPS status check over the SSH key."""

import os
import sys
from pathlib import Path

import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ.get("VPS_HOST", "194.226.123.243"), username="root",
          key_filename=str(Path.home() / ".ssh" / "syntora_vps"), timeout=30,
          allow_agent=False, look_for_keys=False)
cmd = " ".join(sys.argv[1:]) or (
    "systemctl is-active syntora-lead-api; curl -sS -m 5 http://127.0.0.1:8080/health; echo; "
    "journalctl -u syntora-lead-api -n 15 --no-pager | cut -c1-220; "
    "grep -n 'listen\\|ssl_certificate ' /etc/nginx/sites-available/syntora-api; ls /etc/letsencrypt/live 2>&1"
)
_, out, err = c.exec_command(cmd, timeout=120)
print((out.read() + err.read()).decode(errors="replace"))
c.close()
