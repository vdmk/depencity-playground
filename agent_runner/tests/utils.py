import json
from pathlib import Path


FIXTURES = Path(__file__).parent / 'fixtures'
DOCKER = FIXTURES / 'mcp/depencity/docker'
PROJECT = Path(__file__).resolve().parents[2]


def read_json(path):
    return json.loads(path.read_text())
