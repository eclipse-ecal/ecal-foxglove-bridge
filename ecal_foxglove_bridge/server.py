# Copyright (c) Continental. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for details.

import typing
from .bridge_types import Topic, Data

class Listener(typing.Protocol):
        
    async def on_subscribe(self, topic: Topic):
        ...

    async def on_unsubscribe(self, topic: Topic):
        ...

    async def on_client_advertise(self, topic: Topic):
        ...

    async def on_client_unadvertise(self, topic: Topic):
        ...

    async def on_client_message(self, data: Data):
        ...
