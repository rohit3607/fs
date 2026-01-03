#Codeflix_Botz
#rohit_1888 on Tg

import motor, asyncio
import motor.motor_asyncio
import time
import pymongo, os
from config import DB_URI, DB_NAME
import logging
from datetime import datetime, timedelta

dbclient = pymongo.MongoClient(DB_URI)
database = dbclient[DB_NAME]

logging.basicConfig(level=logging.INFO)


class Rohit:

    def __init__(self, DB_URI, DB_NAME):
        self.dbclient = motor.motor_asyncio.AsyncIOMotorClient(DB_URI)
        self.database = self.dbclient[DB_NAME]

        self.user_data = self.database['users']
        # Channels where bot is allowed to post (added by admins)
        self.channels = self.database['channels']
        # Posts metadata for reaction tracking
        self.posts = self.database['posts']

    # USER DATA
    async def present_user(self, user_id: int):
        found = await self.user_data.find_one({'_id': user_id})
        return bool(found)

    async def add_user(self, user_id: int):
        await self.user_data.insert_one({'_id': user_id})
        return

    async def full_userbase(self):
        user_docs = await self.user_data.find().to_list(length=None)
        user_ids = [doc['_id'] for doc in user_docs]
        return user_ids

    async def del_user(self, user_id: int):
        await self.user_data.delete_one({'_id': user_id})
        return

    # CHANNELS & POSTS
    async def add_channel(self, channel_id: int, added_by: int):
        await self.channels.update_one({'_id': channel_id}, {'$set': {'added_by': added_by}}, upsert=True)
        return

    async def remove_channel(self, channel_id: int):
        await self.channels.delete_one({'_id': channel_id})
        return

    async def list_channels(self):
        docs = await self.channels.find().to_list(length=None)
        return docs

    async def save_post(self, channel_id: int, message_id: int, emoji_order: list = None):
        emoji_order = emoji_order or []
        doc = {
            'channel_id': channel_id,
            'message_id': message_id,
            'reactions': {},
            'emoji_order': emoji_order
        }
        await self.posts.insert_one(doc)
        return

    async def get_post(self, channel_id: int, message_id: int):
        return await self.posts.find_one({'channel_id': channel_id, 'message_id': message_id})

    async def increment_reaction(self, channel_id: int, message_id: int, emoji: str):
        # Atomically increment reaction count and return the new value
        result = await self.posts.find_one_and_update(
            {'channel_id': channel_id, 'message_id': message_id},
            {'$inc': {f'reactions.{emoji}': 1}},
            return_document=True
        )
        if result:
            return result.get('reactions', {}).get(emoji, 0)
        return 0



db = Rohit(DB_URI, DB_NAME)
