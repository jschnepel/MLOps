"""Create synthetic records and private demo tokens; never commit runtime/ to Git."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import secrets
from operations_copilot.store import Store
from operations_copilot.synthetic import SyntheticOperations

parser = argparse.ArgumentParser()
parser.add_argument("--data-dir", default="runtime")
args = parser.parse_args()
data = Path(args.data_dir); data.mkdir(parents=True, exist_ok=True)
Store(data / "app.sqlite3").seed_actors()
SyntheticOperations(data / "destination.sqlite3").seed()
if not (data / "auth.json").exists():
    credentials = {who: secrets.token_urlsafe(32) for who in ["alex", "sam", "lee", "riley", "jordan"]}
    for filename, value in [("auth.json", {hashlib.sha256(token.encode()).hexdigest(): actor for actor, token in credentials.items()}), ("demo_credentials.json", credentials)]:
        path = data / filename
        with path.open("w") as f:
            json.dump(value, f, indent=2)
        os.chmod(path, 0o600)
print(f"Initialized {data}. Local demo credentials: {data / 'demo_credentials.json'}")
print("Use alex for requests; sam for approval. Do not publish these tokens or expose the demo publicly.")
