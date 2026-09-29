#!/usr/bin/env python3
from __future__ import annotations

import json
import socket
from pathlib import Path


class DaemonClient:
    def __init__(self, socket_path: str = '.devin/tmp/nlu_dev_agent.sock'):
        self.socket_path = Path(socket_path)

    def call(self, cmd: dict, timeout: float = 60.0) -> dict:
        if not self.socket_path.exists():
            raise FileNotFoundError(f'Daemon socket not found: {self.socket_path}')

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(self.socket_path))
            s.sendall((json.dumps(cmd) + '\n').encode('utf-8'))
            raw = b''
            while not raw.endswith(b'\n'):
                chunk = s.recv(4096)
                if not chunk:
                    break
                raw += chunk

        if not raw:
            raise ConnectionError('No response from daemon')
        return json.loads(raw.decode('utf-8'))
