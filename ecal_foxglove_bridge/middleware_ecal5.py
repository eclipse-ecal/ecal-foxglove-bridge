# Copyright (c) Continental. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for details.

import asyncio
import logging
import os
import platform
import time
import typing

import ecal.core.core as ecal_core

from .middleware import MonitoringListener
from .bridge_types import MessageEncoding, Topic, Data

logger = logging.getLogger("FoxgloveServer - eCAL 5")

def is_my_own_topic(topic):
    my_host = platform.node()
    my_pid = os.getpid()
    return my_pid == topic['pid'] and my_host == topic['hname']


def get_message_encoding(ecal_encoding: str) -> MessageEncoding:
    if ecal_encoding == "proto":
        return MessageEncoding.PROTOBUF
    elif ecal_encoding == "base":
        return MessageEncoding.JSON
    else:
        raise ValueError(f"Unsupported eCAL encoding: {ecal_encoding}")


def create_topic_from_info(info: dict) -> Topic | None:
    if info['direction'] == 'subscriber' or is_my_own_topic(info):
        return None  # Skip topics that are not published by this process

    try:
        ecal_encoding, ecal_topic_type = info["ttype"].split(":")
    except Exception:
        ecal_encoding = ""
        ecal_topic_type = ""

    try:
        encoding = get_message_encoding(ecal_encoding)
    except ValueError as e:
        return None  # Skip unsupported encodings

    return Topic(
        topic_name=info["tname"],
        encoding=encoding,
        schema_name=ecal_topic_type,
        schema=info["tdesc"]
    )

class Monitoring(object):
    """ Monitoring class for eCAL 5
    This class monitors the eCAL topics and notifies the listener about new and removed topics.
    It uses the eCAL core monitoring API to get the current topics and their details.   
    """

    topics : set[Topic] # Set of currently active topics

    def __init__(self):
        self.topics = set()

    async def do_monitor(self, listener: MonitoringListener):
        while ecal_core.ok():
            current_topics = await self.get_topics_from_monitoring()
            new_topics = current_topics - self.topics
            removed_topics = self.topics - current_topics

            self.topics = current_topics

            if removed_topics:
                await listener.on_removed_topics(removed_topics)
            if new_topics:
                await listener.on_new_topics(new_topics)

            await asyncio.sleep(1)

    async def get_topics_from_monitoring(self) -> set[Topic]:
        current_topics = set()
        try:
            topics = ecal_core.mon_monitoring()[1]['topics']
        except Exception: # Catch no monitoring information
            logger.warning("Cannot parse monitoring info")
            return current_topics

        for topic in topics:
            current_topic = create_topic_from_info(topic)
            if current_topic is not None:
                # Add the topic to the set
                current_topics.add(current_topic)

        return current_topics

# This class handles each available Topic
# It contains an ecal subscriber, and will forward messages to the server.
class Subscriber(object):
    topic : Topic
    data_callback: typing.Callable[[Data], None]
    subscriber : ecal_core.subscriber

    def __init__(self, topic : Topic, data_callback: typing.Callable[[Data], None]):
        self.topic = topic
        self.data_callback = data_callback
        self.subscriber = None

    @property
    def is_subscribed(self):
        return self.subscriber is not None

    def subscribe(self):
        data_callback = self.data_callback
        topic = self.topic
        event_loop = asyncio.get_event_loop()

        def callback(topic_name, msg, send_time):
            asyncio.run_coroutine_threadsafe(
                data_callback(Data(
                    topic=topic,
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
