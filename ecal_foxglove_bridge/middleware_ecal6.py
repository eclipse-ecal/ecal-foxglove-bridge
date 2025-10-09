# Copyright (c) Continental. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for details.

import asyncio
import logging
import os
import platform
import typing
import time

import ecal.nanobind_core as ecal_core

from .middleware import MonitoringListener
from .bridge_types import MessageEncoding, Topic, Data

logger = logging.getLogger("FoxgloveServer - eCAL 6")

MIDDLEWARE_VERSION = f"eCAL {ecal_core.get_version_string()}"

class TopicHelper:
    """ Helper class to check if a topic belongs to the current process. """
    def __init__(self):
        self._host = platform.node()
        self._pid = os.getpid()

    def is_my_own_topic(self, topic : ecal_core.TopicId) -> bool:
        return topic.topic_id.process_id == self._pid and topic.topic_id.host_name == self._host

    def get_message_encoding(self, ecal_encoding: str) -> MessageEncoding:
        if ecal_encoding == "proto":
            return MessageEncoding.PROTOBUF
        elif ecal_encoding == "base":
            return MessageEncoding.JSON
        else:
            raise ValueError(f"Unsupported eCAL encoding: {ecal_encoding}")

    def create_topic(self, topic: ecal_core.TopicId, topic_info: ecal_core.DataTypeInformation) -> Topic | None:
        if self.is_my_own_topic(topic):
            return None  # Skip topics that are not published by this process
   
        try:
            encoding = self.get_message_encoding(topic_info.encoding)
        except ValueError as e:
            return None  # Skip unsupported encodings
    
        return Topic(
            topic_name=topic.topic_name,
            encoding=encoding,
            schema_name=topic_info.name,
            schema=topic_info.descriptor
        )


class MiddlewareContext():
    """ Context manager for eCAL initialization and finalization. """
    def __init__(self, message: str):
        self.message = message

    def __enter__(self, ) -> "MiddlewareContext":
        ecal_core.initialize(self.message, ecal_core.init.ALL)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        ecal_core.finalize()


class Monitoring(object):
    topics : set[Topic] = set()
    topic_helper = TopicHelper()


    async def do_monitor(self, listener: MonitoringListener):
        while ecal_core.ok():
            #logger.info("Monitoring...")
            current_topics = await self.get_topics_from_registration()
            new_topics = current_topics - self.topics
            removed_topics = self.topics - current_topics

            self.topics = current_topics

            if removed_topics:
                for removed_topic in removed_topics:
                    await listener.on_removed_topic(removed_topic)
            if new_topics:
                for new_topic in new_topics:
                    await listener.on_new_topic(new_topic)

            await asyncio.sleep(1)

    async def get_topics_from_registration(self) -> set[Topic]:
        topics = set()
        pub_ids = ecal_core.registration.get_publisher_ids()

        if pub_ids is None: 
            logger.warning("Cannot get publisher ids from registration")
            return set()
        
        for pub_id in pub_ids:
            info = ecal_core.registration.get_publisher_info(pub_id)
            if info is None:
                logger.warning(f"Cannot get publisher info for {pub_id}")
                continue

            topic = self.topic_helper.create_topic(pub_id, info)
            if topic is not None:
                topics.add(topic)

        return topics
    

# This class handles each available Topic
# It contains an ecal subscriber, and will forward messages to the server.
class Subscriber(object):
    topic : Topic
    data_callback: typing.Callable[[Data], None]
    subscriber : ecal_core.Subscriber | None = None
    topic_helper = TopicHelper()

    def __init__(self, topic : Topic, data_callback: typing.Callable[[Data], None]):
        event_loop = asyncio.get_event_loop()

        def callback(publisher_id : ecal_core.TopicId, datatype_info : ecal_core.DataTypeInformation, data : ecal_core.ReceiveCallbackData):
            # We should assert that the topic_id matches the topic we subscribed to, but we'll skip it for now
            asyncio.run_coroutine_threadsafe(
                data_callback(Data(
                    topic=topic,
                    msg=data.buffer,
                    timestamp=time.time_ns()
                )),
                event_loop
            )

        self.subscriber = ecal_core.Subscriber(topic.topic_name)
        self.subscriber.set_receive_callback(callback)

    def close(self):
        self.subscriber.remove_receive_callback()
        del self.subscriber
        self.subscriber = None

class Publisher(object):
    publisher : ecal_core.Publisher

    def __init__(self, info : Topic):
        datatype_info = ecal_core.DataTypeInformation(
            name=info.schema_name,
            encoding=info.encoding.value,
            descriptor=info.schema
        )
        self.publisher = ecal_core.Publisher(info.topic_name, datatype_info)

    def publish(self, message: bytes):
        self.publisher.send(message)

    def close(self):
        del self.publisher
        self.publisher = None