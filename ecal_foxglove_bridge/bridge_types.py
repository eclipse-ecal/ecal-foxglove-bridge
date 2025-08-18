# Copyright (c) Continental. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for details.

from enum import Enum
from typing import NamedTuple

class MessageEncoding(Enum):
    PROTOBUF = "protobuf"
    JSON = "json"
    OTHER = "other"

class Topic(NamedTuple):
    topic_name: str
    encoding: MessageEncoding
    schema_name: str
    schema: bytes

class Data(NamedTuple):
    topic: Topic
    timestamp: int
    msg: bytes