"""The renewal hook must never reload nginx when config validation fails."""
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("config_status", [0, 1])
def test_certbot_reload_requires_valid_config(tmp_path, config_status):
    log = tmp_path / "calls"
    commands = {
        "nginx": '#!/bin/sh\necho "nginx $*" >> "$HOOK_LOG"\nexit "$CONFIG_STATUS"\n',
        "systemctl": '#!/bin/sh\necho "systemctl $*" >> "$HOOK_LOG"\n',
    }
    for name, content in commands.items():
        executable = tmp_path / name
        executable.write_text(content)
        executable.chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}",
               HOOK_LOG=str(log), CONFIG_STATUS=str(config_status))
    hook = Path(__file__).resolve().parents[1] / "deploy/certbot-reload-nginx.sh"
    result = subprocess.run(["/bin/sh", str(hook)], env=env, check=False)
    assert result.returncode == config_status
    assert log.read_text().splitlines() == (
        ["nginx -t", "systemctl reload nginx"] if config_status == 0 else ["nginx -t"]
    )
