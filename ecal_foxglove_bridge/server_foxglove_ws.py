# Copyright (c) Continental. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for details.

import logging
import typing

from .bridge_types import Topic, Data, MessageEncoding
from .server import ServerListener

from foxglove_websocket import run_cancellable
from foxglove_websocket.server import FoxgloveServer, FoxgloveServerListener
from foxglove_websocket.types import ChannelId, ChannelWithoutId, ClientChannel, ClientChannelId

logger = logging.getLogger("FoxgloveServer")


def foxglove_client_channel_to_topic(channel: ClientChannel) -> Topic:
    """
    Convert a Foxglove client channel to a Topic.
    """
    return Topic(
        topic_name=channel.name,
        encoding=channel.encoding,
        schema_name=channel.schema_name,
        schema=channel.schema.encode("utf-8") if channel.schema else b""
    )


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


class Listener(FoxgloveServerListener):
    _mapping: typing.Dict[ChannelId, Topic] = {}
    _client_mapping: typing.Dict[ClientChannelId, Topic] = {}

    _listener: ServerListener

    def register_topic(self, channel: ChannelId, topic: Topic):
        """
        Register a topic with the given channel ID.
        """
        self._mapping[channel] = topic

    async def on_subscribe(self, server: FoxgloveServer, channel_id: ChannelId):
        self._listener.on_subscribe(self._mapping[channel_id])

    async def on_unsubscribe(self, server: FoxgloveServer, channel_id: ChannelId):
        self._listener.on_unsubscribe(self._mapping[channel_id])

    async def on_client_advertise(self, server: FoxgloveServer, channel: ClientChannel):
        self._client_mapping[channel.id] = foxglove_client_channel_to_topic(channel)
        self._listener.on_client_advertise(self._client_mapping[channel.id])

    async def on_client_unadvertise(self, server: FoxgloveServer, channel_id: ClientChannelId):
        removed_channel = self._client_mapping.pop(channel_id)
        self._listener.on_client_unadvertise(removed_channel)

    async def on_client_message(self, server: FoxgloveServer, channel_id: ClientChannelId, payload: bytes):
        self._listener.on_client_message(Data(
            topic=self._client_mapping[channel_id],
            timestamp=0,  # Timestamp is not provided in this context
            msg=payload
        ))