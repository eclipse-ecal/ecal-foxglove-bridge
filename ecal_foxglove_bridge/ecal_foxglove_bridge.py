# Copyright (c) Continental. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for details.

from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import argparse
import base64
from enum import Enum
import logging
import os
import platform
import sys
import time
import json
import typing

from importlib.metadata import version as importlib_version
from packaging import version as packaging_version

ecal_version = packaging_version.parse(importlib_version("ecal"))

if ecal_version.major == 5:
    from .monitoring_ecal5 import Monitoring
elif ecal_version.major == 6:
    from .monitoring_ecal6 import Monitoring    
else:
    raise ImportError(f"Unsupported eCAL version {ecal_version}. Supported versions are 5.x and 6.x.")

from monitoring import eCALChannel

from typing import NamedTuple

class ServerDatum(NamedTuple):
    id: ChannelId
    timestamp: int
    msg: bytes

from foxglove_websocket import run_cancellable
from foxglove_websocket.server import FoxgloveServer, FoxgloveServerListener
from foxglove_websocket.types import ChannelId, ChannelWithoutId, ClientChannel, ClientChannelId

import ecal.core.core as ecal_core


logger = logging.getLogger("FoxgloveServer")

ecal_foxglove_encoding_mapping = {"proto": "protobuf", "base": "json"}
foxglove_ecal_encoding_mapping = dict(zip(ecal_foxglove_encoding_mapping.values(), ecal_foxglove_encoding_mapping.keys()))


class Blacklist():
    def __init__(self, blacklist: set[str]):
        self.blacklist = blacklist

    def is_blacklisted(self, topic_name: str) -> bool:
        return topic_name in self.blacklist
    
def read_blacklist(filename: str | None) -> Blacklist:
    if not filename:
        logger.info('No blacklist file specified')
        return Blacklist(set())
    try:
        f = open(filename, 'r')
    except FileNotFoundError:
        logger.error(f'{filename} file not found. No blacklist.')
        exit(1)
    try:
        data = json.load(f)
    except json.JSONDecodeError as err:
        logger.error(f'Error decoding json file. {err}')
        exit(2)
    logger.info(f'Blacklist: {data}')
    return Blacklist(set(data))

def get_foxglove_encoding(ecal_encoding : str):
    try:
        return ecal_foxglove_encoding_mapping[ecal_encoding]
    except KeyError:
        return ""

def get_ecal_encoding(foxglove_encoding : str):
    try:
        return foxglove_ecal_encoding_mapping[foxglove_encoding]
    except KeyError:
        return ""
        

class MessageQueue:
    _queue: asyncio.Queue[ServerDatum]
    _messages_dropped: int = 0

    def __init__(self, maxsize: int = 10):
        self._queue = asyncio.Queue(maxsize=maxsize)

    async def submit(self, item: ServerDatum):
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self._messages_dropped += 1
            logger.info("Dropping message of channel with id {}. Total messages dropped: {}".format(item.id, self._messages_dropped))
        except Exception as e:
            print("Caught exception in callback {}".format(e))   

    async def get(self):
        return await self._queue.get()


# This class handles each available Topic
# It contains an ecal subscriber, and will forward messages to the server.
class TopicSubscriber(object):
    channel_id : ChannelId
    info : eCALChannel
    subscriber : ecal_core.subscriber

    def __init__(self, id : ChannelId, info : eCALChannel, data_callback: typing.Callable[[ServerDatum], None]):
        self.id = id
        self.info = info
        self.subscriber = None
        self.data_callback = data_callback

    @property
    def is_subscribed(self):
        return self.subscriber is not None

    def subscribe(self):
        data_callback = self.data_callback
        event_loop = asyncio.get_event_loop()

        def callback(topic_name, msg, send_time):
            asyncio.run_coroutine_threadsafe(
                data_callback(ServerDatum(
                    id=self.id,
                    msg=msg,
                    timestamp=time.time_ns()
                )),
                event_loop
            )

        self.subscriber = ecal_core.subscriber(self.info.topic)
        self.subscriber.set_callback(callback)
        
    def unsubscribe(self):
        self.subscriber.destroy()
        self.subscriber = None


# This class handles all connections.
# It advertises new topics to the server, and removes the ones that are no longer present in the monitoring
class ConnectionHandler(MonitoringListener):
    topic_subscriptions: dict[str, TopicSubscriber]
    id_channel_mapping: dict[ChannelId, str]
    server: FoxgloveServer

    def __init__(self, server: FoxgloveServer, queue: asyncio.Queue[ServerDatum]):
        self.topic_subscriptions = {}
        self.id_channel_mapping = {}
        self.server = server
        self.queue = queue

    def get_subscriber_by_id(self, id: ChannelId):
        return self.topic_subscriptions[self.id_channel_mapping[id]]

    async def on_new_topics(self, new_topics: set[MyChannelWithoutId]):
        for topic in new_topics:
            channel_without_id = ChannelWithoutId(**topic._asdict())
            id = await self.server.add_channel(
                channel_without_id
            )
            self.topic_subscriptions[topic.topic] = TopicSubscriber(id, topic, self.queue)
            self.id_channel_mapping[id] = topic.topic
            logger.info("Added topic {} with id {}".format(topic.topic, id))

    async def on_removed_topics(self, removed_topics: set[MyChannelWithoutId]):
        for topic in removed_topics:
            topic_name = topic.topic
            removed_subscriber = self.topic_subscriptions[topic_name]
            logger.info("Removing topic {} with id {}".format(topic.topic, removed_subscriber.id))
            await self.server.remove_channel(
               removed_subscriber.id
            )
            if removed_subscriber.is_subscribed:
                removed_subscriber.unsubscribe()
            self.topic_subscriptions.pop(topic_name)
            self.id_channel_mapping.pop(removed_subscriber.id)


class PublisherHandler(object):
    publishers: dict[ChannelId, ecal_core.publisher]

    def __init__(self):
        self.publishers = {}

    def add_publisher(self, channel: ClientChannel):
        # ecal_encoding = get_ecal_encoding(foxglove_encoding=channel["encoding"])
        # topic_type = f"{ecal_encoding}:{channel['schemaName']}"
        topic_type = "base:std::string"
        self.publishers[channel["id"]] = ecal_core.publisher(topic_name=channel["topic"], topic_type=topic_type)

    def remove_publisher(self, channel_id: ClientChannelId):
        # atm we're not removing the publishers since we would recreate publishers all the time
        self.publishers[channel_id].destroy()
        del self.publishers[channel_id]
        pass

    def publish(self, channel_id: ClientChannelId, payload: bytes):
        self.publishers[channel_id].send(payload)


class Listener(FoxgloveServerListener):
    publisher_handler: PublisherHandler

    def __init__(self, connection_handler : ConnectionHandler):
        self.connection_handler = connection_handler
        self.publisher_handler = PublisherHandler()

    async def on_subscribe(self, server: FoxgloveServer, channel_id: ChannelId):
        logger.info("Subscribing to {}".format(channel_id));
        self.connection_handler.get_subscriber_by_id(channel_id).subscribe()

    async def on_unsubscribe(self, server: FoxgloveServer, channel_id: ChannelId):
        logger.info("Unsubscribing from {}".format(channel_id));
        self.connection_handler.get_subscriber_by_id(channel_id).unsubscribe()

    async def on_client_advertise(self, server: FoxgloveServer, channel: ClientChannel):
        self.publisher_handler.add_publisher(channel)

    async def on_client_unadvertise(self, server: FoxgloveServer, channel_id: ClientChannelId):
        self.publisher_handler.remove_publisher(channel_id)

    async def on_client_message(self, server: FoxgloveServer, channel_id: ClientChannelId, payload: bytes):
        self.publisher_handler.publish(channel_id, payload)


async def handle_messages(queue: asyncio.Queue[ServerDatum], server: FoxgloveServer):
    while True:
        data = await queue.get()
        await server.send_message(
            data.id,
            data.timestamp,
            data.msg
        )


def main():
    args = parse_arguments()
    run_cancellable(execute(args)) 

async def execute(args):
    ecal_core.initialize("eCAL WS Gateway", ecal_core.INIT_ALL)

    blacklist = readBlacklist(args.blacklist_file)
    
    # sleep 1 second so monitoring info will be available
    await asyncio.sleep(1)

    message_queue = MessageQueue(maxsize=args.queue_size)
    
    async with FoxgloveServer("0.0.0.0", 8765, "example server", logger=logger, capabilities=["clientPublish"], supported_encodings=["json"]) as server:
        connection_handler = ConnectionHandler(server, queue)
        server.set_listener(Listener(connection_handler))

        monitoring = Monitoring(blacklist)
        asyncio.create_task(monitoring.do_monitor(connection_handler))
        
        asyncio.create_task(handle_messages( queue, server))

        while True:
            await asyncio.sleep(0.5)

def version_information():
    return '''ecal-foxglove-bridge {} using ecal: {}'''.format("0.2.0", ecal_core.getversion())

def parse_arguments():
    parser = argparse.ArgumentParser(description="Bridge application to forward data between eCAL network and Foxglove websocket connection")
    parser.add_argument("--queue-size", dest="queue_size", type=int, help="Size of the queue where to keep messages before sending them over the websocket connection. If the queue is full, additional incoming messages will be dropped", default=3)
    parser.add_argument('--version', action='version', version=version_information())
    parser.add_argument('--blacklist', help='Path to the blacklist json file.', type=str, required=False, dest='blacklist_file')
    args = parser.parse_args()     
    return args





if __name__ == "__main__":
    main()
