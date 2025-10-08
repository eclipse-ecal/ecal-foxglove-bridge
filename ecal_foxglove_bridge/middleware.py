# Copyright (c) Continental. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for details.

import typing

from .bridge_types import MessageEncoding, Topic, Data

class MiddlewareContext(typing.ContextManager["MiddlewareContext"], typing.Protocol):
    """ Context manager for middleware initialization and finalization. """

    def __init__(self, message: str) -> None:
        """
        Initialize the middleware context with an optional message.
        """
        ...
        
    ...

class MonitoringListener(typing.Protocol):
    async def on_new_topic(self, new_topic : Topic):
        """
        Called when there are new topics in the monitoring
        """
        ...

    async def on_removed_topic(self, removed_topic : Topic):
        """
        Called when topics are no longer present in the monitoring
        """
        ...

class Monitoring(typing.Protocol):
    async def do_monitor(self, listener: MonitoringListener):
        """
        Perform monitoring and call methods of the listener when topics are added or removed.
        """
        ...


class Publisher(typing.Protocol):
    def __init__(self, info : Topic):
        """
        Initialize the publisher with topic information.
        """
        ...

    async def publish(self, message: bytes):
        """
        Publish data to the topic.
        """
        ...
 

class Subscriber(typing.Protocol):
    def __init__(self, info : Topic, data_callback: typing.Callable[[Data], None]):
        """
        Initialize the subscriber with topic information and a callback for data.
        """
        ...

    @property
    def is_subscribed(self):
        """
        Check if the subscriber is currently subscribed to the topic.
        """
        ...

    async def subscribe(self):
        """
        Subscribe to a topic and call the callback with the data received.
        """
        ...
    
    async def unsubscribe(self):
        """
        Unsubscribe from a topic.
        """
        ...