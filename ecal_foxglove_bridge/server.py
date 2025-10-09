# Copyright 2025 AUMOVIO and subsidiaries. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for details.

import typing
from .bridge_types import Topic, Data

class ServerListener(typing.Protocol):
        
    async def on_subscribe(self, topic: Topic):
        ...

    async def on_unsubscribe(self, topic: Topic):
        ...

    async def on_publisher_advertise(self, topic: Topic):
        ...

    async def on_publisher_unadvertise(self, topic: Topic):
        ...

    async def on_publisher_message(self, data: Data):
        ...

class ServerArguments(typing.NamedTuple):
    name : str
    ip_address: str
    port: int

class Server(typing.Protocol):
    def __init__(self, server_arguments: ServerArguments):
        ...

    async def __aenter__(self) -> "Server":
        ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool | None:
        ...

    async def add_publisher(self, topic: Topic)-> None:
        ...

    async def remove_publisher(self, topic: Topic)-> None:
        ...

    async def publish(self, data: Data) -> None:
        ...
        