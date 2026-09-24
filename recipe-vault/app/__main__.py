"""`python -m app` starts Recipe Vault on http://127.0.0.1:8000."""

import argparse

import uvicorn

from .main import DEFAULT_DB, create_app

parser = argparse.ArgumentParser(description="Run Recipe Vault")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--db", default=DEFAULT_DB, help="path to the SQLite database file")
args = parser.parse_args()

uvicorn.run(create_app(args.db), host=args.host, port=args.port)
