from fastapi import FastAPI, Body, Form, File, Request, Header, HTTPException, Response
from fastapi.responses import PlainTextResponse
from serpent import loads, dumps
from .LibraryFactory import RemoteLibraryFactory
import inspect
import sys
import uuid
from time import sleep
from typing import List, Dict, Any
from pydantic import BaseModel
from time import sleep
from fastapi.concurrency import run_in_threadpool


class ExampleLibrary:
    """this is nice intro of tested library"""

    def __init__(self):
        """this is test description of library initialization"""
        self.exec_count = 0

    def msg(self, message):
        """this is documentation for msg keyword"""
        self.exec_count += 1
        print(message + str(self.exec_count))
        return message

    def sleeping_cat(self, time):
        print("ill sleep for x seconds")
        sleep(time)

    def failing_cat(self, msg):
        raise ValueError(msg)

    def __del__(self):
        print("deleting library!!!")


def RRemoteServerFactory(library):

    app = FastAPI()

    instances = {}

    class Keyword(BaseModel):
        name: str
        args: List[Any]
        kwargs: Dict[str, Any] = None

    @app.get("/create_instance")
    def create_instance(response: Response):
        instance_id = uuid.uuid4().hex
        instances[instance_id] = RemoteLibraryFactory(library)
        response.headers["X-instance-id"] = instance_id
        print(f"instances: {instances}")
        return {"message": "instance created"}

    @app.delete("/delete_instance")
    def delete_instance(x_instance_id: str = Header(None)):
        library = instances.get(x_instance_id)
        if library is None:
            raise HTTPException(status_code=404, detail="missing instance id")
        del library
        del instances[x_instance_id]
        return {"message": "instance deleted"}

    @app.get("/healthcheck")
    async def healthcheck():
        return {"message": "ok"}

    @app.get("/get_keyword_names")
    def get_keyword_names(x_instance_id: str = Header(None)):
        library = instances.get(x_instance_id)
        if library is None:
            raise HTTPException(status_code=404, detail="missing instance id")
        return library.get_keyword_names()

    @app.get("/get_keyword_documentation")
    def get_keyword_documentation(name: str, x_instance_id: str = Header(None)):
        library = instances.get(x_instance_id)
        if library is None:
            raise HTTPException(status_code=404, detail="missing instance id")
        return library.get_keyword_documentation(name)

    @app.get("/get_keyword_arguments")
    def get_keyword_arguments(name: str, x_instance_id: str = Header(None)):
        library = instances.get(x_instance_id)
        if library is None:
            raise HTTPException(status_code=404, detail="missing instance id")
        return library.get_keyword_arguments(name)

    @app.post("/run_keyword", response_class=PlainTextResponse)
    async def run_keyword(request: Request, x_instance_id: str = Header(None)):
        library = instances.get(x_instance_id)
        if library is None:
            raise HTTPException(status_code=404, detail="missing instance id")
        keyword = Keyword(**loads(await request.body()))
        # thr = await run_in_threadpool(dumps(library.run_keyword(name=keyword.name, args=keyword.args, kwargs=keyword.kwargs)))
        thr = await run_in_threadpool(
            library.run_keyword,
            name=keyword.name,
            args=keyword.args,
            kwargs=keyword.kwargs,
        )
        return dumps(thr)

    return app


app = RRemoteServerFactory(ExampleLibrary)
