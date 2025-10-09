# Copyright (c) 2023 - 2025 Continental. All rights reserved.
# Copyright 2025 AUMOVIO and subsidiaries. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for details.

from __future__ import annotations

import asyncio
import argparse
import logging
import json

from .bridge_types import Topic, Data, Command, Action
from .middleware_implementation import *
from .server_implementation import *

logger = logging.getLogger("FoxgloveServer")

# We don't want any foxglove imports here. This is an exception, but we will provide a similar function in the future
from foxglove_websocket import run_cancellable

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
    

class MessageQueue:
    _queue: asyncio.Queue[Data]
    _messages_dropped: int = 0

    def __init__(self, maxsize: int = 10):
        self._queue = asyncio.Queue(maxsize=maxsize)

    async def submit(self, item: Data):
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self._messages_dropped += 1
            logger.info("Dropping message of channel with id {}. Total messages dropped: {}".format(item.id, self._messages_dropped))
        except Exception as e:
            print("Caught exception in callback {}".format(e))   

    async def get(self):
        return await self._queue.get()

class CommandQueue:
    _queue: asyncio.Queue[Command]

    def __init__(self, maxsize: int = 1000):
        self._queue = asyncio.Queue(maxsize=maxsize)

    async def submit(self, command: Command):
        await self._queue.put(command)

    async def get(self) -> Command:
        return await self._queue.get()

class ConnectionHandler(MonitoringListener, ServerListener):
    def __init__(self, message_queue: MessageQueue, command_queue: CommandQueue, blacklist: Blacklist):
        self.message_queue = message_queue
        self.command_queue = command_queue
        self.blacklist = blacklist
        self.subscriber_handler = SubscriberHandler(self.on_message)
        self.publisher_handler = PublisherHandler()

    async def on_message(self, data: Data):
        await self.message_queue.submit(data)

    #functions from MonitoringListener
    async def on_new_topic(self, new_topic : Topic):
        if (not self.blacklist.is_blacklisted(new_topic.topic_name)):
            await self.command_queue.submit(Command(Action.SUBSCRIBE, new_topic))
        else:
            logger.info(f"Topic {new_topic.topic_name} is blacklisted, not subscribing.")

    async def on_removed_topic(self, removed_topic : Topic):
        if (not self.blacklist.is_blacklisted(removed_topic.topic_name)):
            await self.command_queue.submit(Command(Action.UNSUBSCRIBE, removed_topic))

    # functions from ServerListener
    async def on_subscribe(self, topic: Topic):
        self.subscriber_handler.add_subscriber(topic)

    async def on_unsubscribe(self, topic: Topic):
        self.subscriber_handler.remove_subscriber(topic)

    async def on_publisher_advertise(self, topic: Topic):
        self.publisher_handler.add_publisher(topic)

    async def on_publisher_unadvertise(self, topic: Topic):
        self.publisher_handler.remove_publisher(topic)

    async def on_publisher_message(self, data: Data):
        self.publisher_handler.publish(data)


class SubscriberHandler(object):
    subscribers: dict[Topic, Subscriber] = {}

    def __init__(self, data_callback):
        self.data_callback = data_callback

    def add_subscriber(self, topic: Topic):
        self.subscribers[topic] = Subscriber(topic, self.data_callback)

    def remove_subscriber(self, topic: Topic):
        removed_subscriber = self.subscribers.pop(topic, None)
        if removed_subscriber is not None:
            removed_subscriber.close()


class PublisherHandler(object):
    publishers: dict[Topic, Publisher] = {}

    def add_publisher(self, topic: Topic):
        self.publishers[topic] = Publisher(topic)

    def remove_publisher(self, topic: Topic):
        removed_publisher = self.publishers.pop(topic, None)
        if removed_publisher is not None:
            removed_publisher.close()

    def publish(self, data: Data):
        publisher = self.publishers.get(data.topic, None)
        if publisher is not None:
            publisher.publish(data.msg)


async def forward_messages(queue: asyncio.Queue[Data], server: Server):
    while True:
        data = await queue.get()
        await server.publish(data)  

async def forward_commands(command_queue: CommandQueue, server: Server):
    while True:
        command = await command_queue.get()
        if command.action == Action.SUBSCRIBE:
            await server.add_publisher(command.topic)
        elif command.action == Action.UNSUBSCRIBE:
            await server.remove_publisher(command.topic)        

def main():
    args = parse_arguments()
    run_cancellable(execute(args)) 

async def execute(args):
    with MiddlewareContext("eCAL Foxglove Bridge"):

        # sleep 1 second so monitoring info will be available
        await asyncio.sleep(2)

        blacklist = read_blacklist(args.blacklist_file)
        message_queue = MessageQueue(maxsize=args.queue_size)
        command_queue = CommandQueue()
    
        connection_handler = ConnectionHandler(message_queue, command_queue, blacklist)

        server_arguments = ServerArguments(
            ip_address="0.0.0.0",
            port=args.port,
            name="example server"
        )

        async with Server(server_arguments, connection_handler) as server:
            monitoring = Monitoring()
            asyncio.create_task(monitoring.do_monitor(connection_handler))       
            asyncio.create_task(forward_messages(message_queue, server))
            asyncio.create_task(forward_commands(command_queue, server))

            while True:
                await asyncio.sleep(0.5)


def version_information():
    return '''ecal-foxglove-bridge {} using {} and {}'''.format("0.3.0", MIDDLEWARE_VERSION, SERVER_VERSION)

def parse_arguments():
    parser = argparse.ArgumentParser(description="Bridge application to forward data between eCAL network and Foxglove websocket connection")
    parser.add_argument("--port", dest="port", type=int, help="Port to run the server on", default=8765)
    parser.add_argument("--queue-size", dest="queue_size", type=int, help="Size of the queue where to keep messages before sending them over the websocket connection. If the queue is full, additional incoming messages will be dropped", default=3)
    parser.add_argument('--version', action='version', version=version_information())
    parser.add_argument('--blacklist', help='Path to the blacklist json file, that lists topics which should not be advertised to the server.', type=str, required=False, dest='blacklist_file')
    args = parser.parse_args()     
    return args

