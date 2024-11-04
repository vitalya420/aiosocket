import json
from dataclasses import dataclass
from typing import Dict


@dataclass
class HTTPResponse:
    http_version: str
    status_code: int
    status_phrase: str
    headers: Dict[str, str]
    body: bytes

    def json(self):
        return json.loads(self.body)
