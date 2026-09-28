"""Install a systemd timer on the VPS that keeps the Render bots awake.

Env: VPS_HOST, VPS_KEY (default ~/.ssh/syntora_vps) or VPS_PASSWORD; VPS_USER defaults to root.
"""

from __future__ import annotations

import os

import paramiko

SERVICE = """[Unit]
Description=Ping Render lead-api so Telegram bots stay awake

[Service]
Type=oneshot
ExecStart=/usr/bin/curl -fsS -m 90 -o /dev/null https://syntora-lead-api-1.onrender.com/health
"""

TIMER = """[Unit]
Description=Every 10 minutes: keep Render bots awake

[Timer]
OnBootSec=1min
OnUnitActiveSec=10min
Unit=render-keepalive.service

[Install]
WantedBy=timers.target
"""


def main() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    key_file = os.environ.get("VPS_KEY", os.path.expanduser("~/.ssh/syntora_vps"))
    auth = {"key_filename": key_file} if os.path.isfile(key_file) else {"password": os.environ["VPS_PASSWORD"]}
    ssh.connect(
        os.environ["VPS_HOST"],
        username=os.environ.get("VPS_USER", "root"),
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
        **auth,
    )
    sftp = ssh.open_sftp()
    for name, body in (("render-keepalive.service", SERVICE), ("render-keepalive.timer", TIMER)):
        with sftp.open(f"/etc/systemd/system/{name}", "w") as fh:
            fh.write(body)
    sftp.close()
    cmd = (
        "systemctl daemon-reload && systemctl enable --now render-keepalive.timer && "
        "systemctl start render-keepalive.service; systemctl is-active render-keepalive.timer; "
        "systemctl show render-keepalive.service -p Result --value"
    )
    _, stdout, stderr = ssh.exec_command(cmd, timeout=150)
    print(stdout.read().decode(), stderr.read().decode())
    ssh.close()


if __name__ == "__main__":
    main()
