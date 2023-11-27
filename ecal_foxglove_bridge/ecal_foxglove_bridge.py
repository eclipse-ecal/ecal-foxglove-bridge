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
from typing import TYPE_CHECKING, Type, NamedTuple

from foxglove_websocket import run_cancellable
from foxglove_websocket.server import FoxgloveServer, FoxgloveServerListener
from foxglove_websocket.types import ChannelId, ChannelWithoutId, ClientChannel, ClientChannelId

import ecal.core.core as ecal_core

logger = logging.getLogger("FoxgloveServer")

ecal_foxglove_encoding_mapping = {"proto": "protobuf", "base": "json"}
foxglove_ecal_encoding_mapping = dict(zip(ecal_foxglove_encoding_mapping.values(), ecal_foxglove_encoding_mapping.keys()))

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

def is_my_own_topic(topic):
    my_host = platform.node()
    my_pid = os.getpid()
    return my_pid == topic['pid'] and my_host == topic['hname']


class MyChannelWithoutId(NamedTuple):
    topic: str
    encoding: str
    schemaName: str
    schema: str

class ServerDatum(NamedTuple):
    id: ChannelId
    timestamp: int
    msg: bytes

class MonitoringListener(ABC):
    @abstractmethod
    async def on_new_topics(self, new_topics : set[ChannelWithoutId]):
        """
        Called when there are new topics in the monitoring
        """
        ...

    @abstractmethod
    async def on_removed_topics(self, removed_topics : set[MyChannelWithoutId]):
        """
        Called when topics are no longer present in the monitoring
        """
        ...




# This class is handling the ecal monitoring. 
# It evaluates the messages cyclicly and notifies on added / removed topics
class Monitoring(object):
    topics : set[MyChannelWithoutId]

    def __init__(self):
        self.listener = None
        self.topics = set()

    def set_listener(self, listener : MonitoringListener):
        self.listener = listener

    async def monitoring(self):
        while ecal_core.ok():
            #logger.info("Monitoring...")
            current_topics = await self.get_topics_from_monitoring()
            new_topics = current_topics - self.topics
            removed_topics = self.topics - current_topics

            self.topics = current_topics

            if self.listener:
                if removed_topics:
                    await self.listener.on_removed_topics(removed_topics)
                if new_topics:
                    await self.listener.on_new_topics(new_topics)

            await asyncio.sleep(1)

    async def get_topics_from_monitoring(self):
        current_topics = set()
        try:
            topics = ecal_core.mon_monitoring()[1]['topics']
        except Exception: # Catch no monitoring information
            logger.warning("Cannot parse monitoring info")
            return current_topics

        for topic in topics:
            # only filter topics which are publishers, published by a different proces
            if topic['direction'] == 'publisher' and not is_my_own_topic(topic):
                current_topic = {}
                current_topic["topic"] = topic["tname"]
                try:
                    encoding, topic_type = topic["ttype"].split(":")
                except Exception:
                    encoding = ""
                    topic_type = ""
                current_topic["encoding"] = get_foxglove_encoding(ecal_encoding=encoding)
                current_topic["schemaName"] = topic_type
                current_topic["schema"] = base64.b64encode(topic["tdesc"]).decode("ascii")
                current_topics.add(MyChannelWithoutId(**current_topic))

        return current_topics
        
class TimeSource(Enum):
    SEND_TIMESTAMP = 1
    LOCAL_TIME = 2


messages_dropped = 0


async def submit_to_queue(queue, id, topic_name, msg, send_time):
   try:
       timestamp = time.time_ns()
       
       datum = ServerDatum(id=id, timestamp = timestamp, msg = msg)
       queue.put_nowait(datum)
   except asyncio.QueueFull:
       global messages_dropped
       global logger
       messages_dropped = messages_dropped + 1
       logger.info("Dropping message of channel {}. Total messages dropped: {}".format(topic_name, messages_dropped))        
   except Exception as e:
       print("Caught exception in callback {}".format(e))   
    

# This class handles each available Topic
# It contains an ecal subscriber, and will forward messages to the server.
class TopicSubscriber(object):
    channel_id : ChannelId
    info : MyChannelWithoutId
    subscriber : ecal_core.subscriber
    server : FoxgloveServer
    
    def __init__(self, id : ChannelId, info : MyChannelWithoutId, queue: asyncio.Queue[ServerDatum],  time_source : TimeSource = TimeSource.LOCAL_TIME):
        self.id = id
        self.info = info
        self.subscriber = None
        self.event_loop = asyncio.get_event_loop()
        self.queue = queue
        self.time_source = time_source

    @property
    def is_subscribed(self):
        return self.subscriber is not None

    def callback(self, topic_name, msg, send_time):
        coroutine = submit_to_queue(self.queue, self.id, topic_name, msg, send_time)
        # Submit the coroutine to a given loop
        future = asyncio.run_coroutine_threadsafe(coroutine, self.event_loop)
    
    def subscribe(self):
        self.subscriber = ecal_core.subscriber(self.info.topic)
        self.subscriber.set_callback(self.callback)
        
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
    ecal_core.initialize(sys.argv, "eCAL WS Gateway")
    ecal_core.mon_initialize()
    
    # sleep 1 second so monitoring info will be available
    await asyncio.sleep(1)

    queue: asyncio.Queue[ServerDatum] = asyncio.Queue(maxsize = 10)
    
    async with FoxgloveServer("0.0.0.0", 8765, "example server", logger=logger, capabilities=["clientPublish"], supported_encodings=["json"]) as server:
        connection_handler = ConnectionHandler(server, queue)
        server.set_listener(Listener(connection_handler))

        monitoring = Monitoring()
        monitoring.set_listener(connection_handler)
        asyncio.create_task(monitoring.monitoring())
        
        asyncio.create_task(handle_messages( queue, server))

        while True:
            await asyncio.sleep(0.5)

def version_information():
    return '''ecal-foxglove-bridge {} using ecal: {}'''.format("0.2.0", ecal_core.getversion())

def parse_arguments():
    parser = argparse.ArgumentParser(description="Bridge application to forward data between eCAL network and Foxglove websocket connection")
    parser.add_argument("--queue-size", dest="queue_size", type=int, help="Size of the queue where to keep messages before sending them over the websocket connection. If the queue is full, additional incoming messages will be dropped", default=3)
    parser.add_argument('--version', action='version', version=version_information())
    args = parser.parse_args()     
    return args

if __name__ == "__main__":
    main()
