# Copyright (c) Continental. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for details.

import base64
import logging
import typing

from .bridge_types import Topic, Data, MessageEncoding
from .server import ServerListener, ServerArguments

from foxglove_websocket.server import FoxgloveServer, FoxgloveServerListener
from foxglove_websocket.types import ChannelId, ChannelWithoutId, ClientChannel, ClientChannelId

from importlib.metadata import version as importlib_version
SERVER_VERSION = f"foxglove-ws {importlib_version("foxglove_websocket")}"

logger = logging.getLogger("FoxgloveServer")

class EncodingConverter:
    """
    A class to convert between Foxglove and eCAL encodings.
    """
    foxglove_to_server_encoding_mapping = {
        "protobuf": MessageEncoding.PROTOBUF,
        "json": MessageEncoding.JSON
    }

    server_to_foxglove_encoding_mapping = {v: k for k, v in foxglove_to_server_encoding_mapping.items()}

    @staticmethod
    def get_message_encoding_from_foxglove_encoding(foxglove_encoding: str) -> MessageEncoding:
        return EncodingConverter.foxglove_to_server_encoding_mapping.get(foxglove_encoding, MessageEncoding.OTHER)

    @staticmethod
    def get_foxglove_encoding_from_message_encoding(message_encoding: MessageEncoding) -> str:
        try:
            return EncodingConverter.server_to_foxglove_encoding_mapping[message_encoding]
        except KeyError:
            raise ValueError(f"Unsupported message encoding: {message_encoding}")


class TopicConverter:
    @staticmethod
    def topic_to_foxglove_channel(topic: Topic) -> ChannelWithoutId:
        """
        Convert a Topic to a Foxglove ChannelWithoutId.
        """
        return ChannelWithoutId(
            topic=topic.topic_name,
            encoding=EncodingConverter.get_foxglove_encoding_from_message_encoding(topic.encoding),
            schemaName=topic.schema_name,
            schema=base64.b64encode(topic.schema).decode("ascii")
        )

    @staticmethod
    def foxglove_client_channel_to_topic(channel: ClientChannel) -> Topic:
        """
        Convert a Foxglove client channel to a Topic.
        """
        return Topic(
            topic_name=channel["topic"],
            encoding=EncodingConverter.get_message_encoding_from_foxglove_encoding(channel["encoding"]),
            schema_name=channel["schemaName"],
            schema=base64.b64decode(channel.get("schema", "").encode("ascii"))
        )

class Listener(FoxgloveServerListener):
    _subscriber_mapping: typing.Dict[ChannelId, Topic] = {}
    _publisher_mapping: typing.Dict[ClientChannelId, Topic] = {}

    _listener: ServerListener

    def __init__(self, listener: ServerListener):
        self._listener = listener

    def register_channel(self, channel_id: ChannelId, topic: Topic):
        """
        Register a topic with the given channel ID.
        """
        self._subscriber_mapping[channel_id] = topic

    def remove_channel(self, channel_id: ChannelId):
        """
        Remove the topic associated with the given channel ID.
        """
        removed_topic = self._publisher_mapping.pop(channel_id, None) 
        if removed_topic is None:
            logger.warning(f"remove_channel called for unknown channel ID: {channel_id}")

    async def on_subscribe(self, server: FoxgloveServer, channel_id: ChannelId):
        subscriber_topic = self._subscriber_mapping.get(channel_id, None)
        if subscriber_topic is not None:
            await self._listener.on_subscribe(subscriber_topic)
        else:
            logger.warning(f"Received subscribe for unknown channel ID: {channel_id}")

    async def on_unsubscribe(self, server: FoxgloveServer, channel_id: ChannelId):
        subscriber_topic = self._subscriber_mapping.get(channel_id, None)
        if subscriber_topic is not None:
            await self._listener.on_unsubscribe(subscriber_topic)
        else:
            logger.warning(f"Received unsubscribe for unknown channel ID: {channel_id}")

    async def on_client_advertise(self, server: FoxgloveServer, channel: ClientChannel):
        logger.info(f"Advertising Server Publisher channel ID: {channel['id']}")
        self._publisher_mapping[channel["id"]] = TopicConverter.foxglove_client_channel_to_topic(channel)
        await self._listener.on_publisher_advertise(self._publisher_mapping[channel["id"]])

    async def on_client_unadvertise(self, server: FoxgloveServer, channel_id: ClientChannelId):
        logger.info(f"Unadvertising Server Publisher channel ID: {channel_id}")
        removed_topic = self._publisher_mapping.pop(channel_id, None)
        if removed_topic is not None:
            await self._listener.on_publisher_unadvertise(removed_topic)
        else:
            logger.warning(f"Received unadvertise for unknown channel ID: {channel_id}")

    async def on_client_message(self, server: FoxgloveServer, channel_id: ClientChannelId, payload: bytes):
        topic = self._publisher_mapping.get(channel_id, None)
        if topic is not None:
            await self._listener.on_publisher_message(Data(
              topic=self._publisher_mapping[channel_id],
              timestamp=0,  # Timestamp is not provided in this context
              msg=payload
            ))
        else:
            logger.warning(f"Received message for unknown channel ID: {channel_id}")

class Server():
    topic_to_id_mapping : typing.Dict[Topic, ChannelId] = {}
    foxglove_server : FoxgloveServer

    def __init__(self, server_arguments: ServerArguments, server_listener: ServerListener):
        self.foxglove_server = FoxgloveServer(
            host = server_arguments.ip_address,
            port = server_arguments.port,
            name = server_arguments.name,
            capabilities=["clientPublish"],
            supported_encodings=["json"],
            logger=logger
        )
        self.listener = Listener(server_listener)
        self.foxglove_server.set_listener(self.listener)

    async def __aenter__(self) -> "Server":
        await self.foxglove_server.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool | None:
        return await self.foxglove_server.__aexit__(exc_type, exc_val, exc_tb)
    
    async def add_publisher(self, topic: Topic)-> None:
        foxglove_channel = TopicConverter.topic_to_foxglove_channel(topic)
        foxglove_channel_id = await self.foxglove_server.add_channel(foxglove_channel)
        self.topic_to_id_mapping[topic] = foxglove_channel_id
        self.listener.register_channel(foxglove_channel_id, topic)

    async def remove_publisher(self, topic: Topic)-> None:
        foxglove_channel_id = self.topic_to_id_mapping.pop(topic, None)
        if foxglove_channel_id is not None:
            self.listener.remove_channel(foxglove_channel_id)
            await self.foxglove_server.remove_channel(foxglove_channel_id)

    async def publish(self, data: Data) -> None:
        foxglove_channel_id = self.topic_to_id_mapping.get(data.topic, None)
        if foxglove_channel_id is not None:
            await self.foxglove_server.send_message(
                chan_id=foxglove_channel_id, 
                timestamp=data.timestamp, 
                payload=data.msg)
