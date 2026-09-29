#!/usr/bin/env python3
"""TCP entry point for the pygls JSGF language server."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from lsp.server import server


def main() -> None:
    parser = argparse.ArgumentParser(description='JSGF language server (TCP)')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', '-p', type=int, default=8989)
    args = parser.parse_args()

    server.start_tcp(args.host, args.port)


if __name__ == '__main__':
    main()
