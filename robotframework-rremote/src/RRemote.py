from robot.api.deco import library
from robot.errors import RemoteError
from requests import Session
from serpent import dumps, loads
from dataclasses import dataclass
from typing import Optional
import sys


@dataclass
class RemoteResult(object):
    status: str
    output: Optional[str] = ""
    return_: Optional[str] = None
    error: Optional[str] = None
    traceback: Optional[str] = None
    fatal: Optional[bool] = False
    continuable: Optional[bool] = False


@library
class RRemote:

    ROBOT_LIBRARY_SCOPE = "SUITE"

    def __init__(self, url):
        self.s = Session()
        self.url = url
        response = self.s.get(f"{self.url}/create_instance")
        self.s.headers = {"x-instance-id": response.headers["x-instance-id"]}

    def get_keyword_names(self):
        response = self.s.get(f"{self.url}/get_keyword_names")
        return response.json()

    def run_keyword(self, name, args, kwargs):
        response = self.s.post(
            f"{self.url}/run_keyword",
            data=dumps({"name": name, "args": args, "kwargs": kwargs}),
            headers={"Content-Type": "application/octet-stream"},
        )
        result = RemoteResult(**loads(response.content))
        sys.stdout.write(result.output)
        if result.status != "PASS":
            raise RemoteError(
                result.error, result.traceback, result.fatal, result.continuable
            )
        return result.return_

    def get_keyword_arguments(self, name):
        response = self.s.get(f"{self.url}/get_keyword_arguments/?name={name}")
        return response.json()

    def get_keyword_documentation(self, name):
        response = self.s.get(f"{self.url}/get_keyword_documentation/?name={name}")

        return response.text

    def __del__(self):
        response = self.s.delete(f"{self.url}/delete_instance")
