"""Load API keys from a local .env file (never committed: it's in .gitignore).

Each line looks like  NAME=value . Variables already set in the terminal win over the file.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path=os.path.join(HERE, ".env")):
    if not os.path.exists(path):
        return []
    loaded = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip().removeprefix("export ").strip()
            v = v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v
                loaded.append(k)
    return loaded
