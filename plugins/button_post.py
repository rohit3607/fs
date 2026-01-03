from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import asyncio
import re
from config import START_MSG, START_PIC, HELP_TXT, ABOUT_TXT, is_admin
from database.database import db

# ephemeral drafts keyed by user_id
DRAFTS = {}


def build_start_kb():
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Create Post", callback_data="create_post")],
            [InlineKeyboardButton("About", callback_data="about"), InlineKeyboardButton("Help", callback_data="help")],
            [InlineKeyboardButton("Close", callback_data="close")]
        ]
    )
    return kb


def parse_url_buttons(text: str):
    rows = []
    for line in text.strip().splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        row = []
        for p in parts:
            if "-" not in p:
                continue
            label, url = p.split("-", 1)
            label = label.strip()
            url = url.strip()
            row.append(InlineKeyboardButton(label, url=url))
        if row:
            rows.append(row)
    return rows


def parse_reactions(text: str):
    emojis = [t for t in re.split(r"\s+|,|\\n", text.strip()) if t]
    return emojis


@Client.on_message(filters.private & filters.command("start"))
async def start_cmd(client, message):
    mention = message.from_user.mention if message.from_user else "user"
    try:
        await message.reply_photo(photo=START_PIC, caption=START_MSG.format(mention=mention), reply_markup=build_start_kb())
    except Exception:
        await message.reply_text(START_MSG.format(mention=mention), reply_markup=build_start_kb())


@Client.on_callback_query()
async def cb_handler(client, cb):
    data = cb.data
    uid = cb.from_user.id

    if data == "about":
        await cb.answer()
        await cb.message.edit_text(ABOUT_TXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_start")]]))
        return

    if data == "help":
        await cb.answer()
        await cb.message.edit_text(HELP_TXT, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_start")]]))
        return

    if data == "close":
        await cb.answer("Closed")
        try:
            await cb.message.delete()
        except: pass
        return

    if data == "back_start":
        await cb.answer()
        try:
            await cb.message.edit_caption(caption=cb.message.caption or "", reply_markup=build_start_kb())
        except Exception:
            await cb.message.edit_text(cb.message.text or "", reply_markup=build_start_kb())
        return

    if data == "create_post":
        await cb.answer()
        if not is_admin(uid):
            await cb.message.answer_text("Only bot owner or admins can create posts.")
            return
        DRAFTS[uid] = {'messages': [], 'url_buttons': [], 'reactions': [], 'target': None}
        await cb.message.answer_text("Send me the message (text, media or album) you want to post. Send /cancel to abort.")
        try:
            msg = await client.listen(cb.message.chat.id, timeout=300)
        except asyncio.TimeoutError:
            DRAFTS.pop(uid, None)
            await cb.message.answer_text("Timed out. Please start creating the post again.")
            return

        if msg.text and msg.text.lower() == "/cancel":
            DRAFTS.pop(uid, None)
            await msg.reply_text("Cancelled.")
            return

        messages = [msg]
        mgid = getattr(msg, 'media_group_id', None)
        if mgid:
            while True:
                try:
                    more = await client.listen(cb.message.chat.id, timeout=1)
                    if getattr(more, 'media_group_id', None) == mgid:
                        messages.append(more)
                    else:
                        break
                except asyncio.TimeoutError:
                    break
        DRAFTS[uid]['messages'] = messages

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Add URL Buttons", callback_data="add_url")],
            [InlineKeyboardButton("Add Reaction Buttons", callback_data="add_react")],
            [InlineKeyboardButton("Preview", callback_data="preview"), InlineKeyboardButton("Post", callback_data="post_now")],
            [InlineKeyboardButton("Cancel", callback_data="cancel_post")]
        ])
        await msg.reply_text("Message saved. Choose next action:", reply_markup=kb)
        return

    if data == "cancel_post":
        DRAFTS.pop(uid, None)
        await cb.answer("Cancelled")
        await cb.message.edit_text("Draft cancelled.")
        return

    if data == "add_url":
        await cb.answer()
        if uid not in DRAFTS:
            await cb.message.reply_text("No active draft. Start with Create Post.")
            return
        await cb.message.reply_text("Send me a list of URL buttons for the message. Use this format:\nButton text 1 - http://example.com | Button text 2 - http://...\nYou can use '|' to put buttons in same row. Send /done when finished or /cancel to abort.")
        try:
            msg = await client.listen(cb.message.chat.id, timeout=300)
        except asyncio.TimeoutError:
            await cb.message.answer_text("Timed out. Returning to menu.")
            return
        if msg.text and msg.text.lower() == "/cancel":
            await msg.reply_text("Cancelled adding buttons.")
            return
        rows = parse_url_buttons(msg.text)
        if not rows:
            await msg.reply_text("Could not parse any buttons. Make sure format is: Label - URL | Label2 - URL2\nTry again.")
            return
        DRAFTS[uid]['url_buttons'] = rows
        await msg.reply_text("URL buttons saved.")
        return

    if data == "add_react":
        await cb.answer()
        if uid not in DRAFTS:
            await cb.message.reply_text("No active draft. Start with Create Post.")
            return
        await cb.message.reply_text("Send emojis (space separated or in one message). Each emoji will become a reaction button. Send /done when finished or /cancel to abort.")
        try:
            msg = await client.listen(cb.message.chat.id, timeout=300)
        except asyncio.TimeoutError:
            await cb.message.answer_text("Timed out. Returning to menu.")
            return
        if msg.text and msg.text.lower() == "/cancel":
            await msg.reply_text("Cancelled adding reactions.")
            return
        emojis = parse_reactions(msg.text)
        if not emojis:
            await msg.reply_text("No emojis detected. Try again.")
            return
        DRAFTS[uid]['reactions'] = emojis
        await msg.reply_text(f"Added {len(emojis)} reaction(s): {' '.join(emojis)}")
        return

    if data == "preview":
        await cb.answer()
        if uid not in DRAFTS:
            await cb.message.reply_text("No active draft.")
            return
        draft = DRAFTS[uid]
        keyboard = []
        if draft['url_buttons']:
            keyboard.extend(draft['url_buttons'])
        if draft['reactions']:
            row = []
            for e in draft['reactions']:
                row.append(InlineKeyboardButton(f"{e}", callback_data="noop"))
            keyboard.append(row)
        kb = InlineKeyboardMarkup(keyboard) if keyboard else None

        for i, m in enumerate(draft['messages']):
            if i == 0:
                try:
                    await m.reply_text("Preview:")
                    await client.copy_message(chat_id=cb.message.chat.id, from_chat_id=m.chat.id, message_id=m.message_id, reply_markup=kb)
                except Exception:
                    await m.reply_text("Unable to preview message content.")
            else:
                try:
                    await client.copy_message(chat_id=cb.message.chat.id, from_chat_id=m.chat.id, message_id=m.message_id)
                except Exception:
                    pass
        await cb.message.reply_text("This is a preview. Use Post to publish or add more buttons.")
        return

    if data == "post_now":
        await cb.answer()
        if uid not in DRAFTS:
            await cb.message.reply_text("No active draft.")
            return
        await cb.message.reply_text("Send the channel username (eg @channelusername) or channel ID (eg -10012345) where I should post. I must be admin in that channel.")
        try:
            ch = await client.listen(cb.message.chat.id, timeout=300)
        except asyncio.TimeoutError:
            await cb.message.answer_text("Timed out. Post aborted.")
            return
        if ch.text and ch.text.lower() == "/cancel":
            await ch.reply_text("Cancelled.")
            return
        channel = ch.text.strip()
        try:
            target = await client.get_chat(channel)
        except Exception:
            await ch.reply_text("Could not find that channel. Make sure I am in the channel and provided the correct username or ID.")
            return
        try:
            member = await client.get_chat_member(target.id, (await client.get_me()).id)
            if member.status not in ("administrator", "creator"):
                await ch.reply_text("I am not an admin in that channel. Please make me admin (with right to post/edit) and try again.")
                return
        except Exception:
            pass

        draft = DRAFTS[uid]
        keyboard = []
        if draft['url_buttons']:
            keyboard.extend(draft['url_buttons'])
        kb = InlineKeyboardMarkup(keyboard) if keyboard else None

        posted_msg_id = None
        first = True
        for m in draft['messages']:
            try:
                if first:
                    sent = await client.copy_message(chat_id=target.id, from_chat_id=m.chat.id, message_id=m.message_id, reply_markup=kb)
                    posted_msg_id = sent.message_id
                    first = False
                else:
                    await client.copy_message(chat_id=target.id, from_chat_id=m.chat.id, message_id=m.message_id)
            except Exception as e:
                await ch.reply_text(f"Failed to post message: {e}")
                return

        if draft['reactions'] and posted_msg_id:
            try:
                current_kb = []
                if draft['url_buttons']:
                    current_kb.extend(draft['url_buttons'])
                row = []
                for e in draft['reactions']:
                    b = e.encode('utf-8').hex()
                    cbdata = f"react|{target.id}|{posted_msg_id}|{b}"
                    row.append(InlineKeyboardButton(f"{e} 0", callback_data=cbdata))
                current_kb.append(row)
                await client.edit_message_reply_markup(target.id, posted_msg_id, reply_markup=InlineKeyboardMarkup(current_kb))
            except Exception:
                pass


@Client.on_message(filters.private & filters.command("cmds"))
async def cmds_handler(client, message):
    txt = (
        "Available commands:\n"
        "/create_post - Start the create-post flow\n"
        "/add_channel - Add a channel where bot can post (usage: /add_channel @channel or send command then send channel)\n"
        "/remove_channel - Remove a channel\n"
        "/list_channels - List configured channels\n"
        "/cmds - Show this message\n"
    )
    await message.reply_text(txt)


@Client.on_message(filters.private & filters.command("add_channel"))
async def add_channel_handler(client, message):
    uid = message.from_user.id
    if not is_admin(uid):
        await message.reply_text("Only owner or admins can add channels.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        channel = args[1].strip()
    else:
        await message.reply_text("Send the channel username or ID to add.")
        try:
            reply = await client.listen(message.chat.id, timeout=60)
            channel = reply.text.strip()
        except asyncio.TimeoutError:
            await message.reply_text("Timed out.")
            return
    try:
        ch = await client.get_chat(channel)
        await db.add_channel(ch.id, uid)
        await message.reply_text(f"Added channel: {ch.title or ch.username} ({ch.id})")
    except Exception as e:
        await message.reply_text(f"Failed to add channel: {e}")


@Client.on_message(filters.private & filters.command("remove_channel"))
async def remove_channel_handler(client, message):
    uid = message.from_user.id
    if not is_admin(uid):
        await message.reply_text("Only owner or admins can remove channels.")
        return
    args = message.text.split(maxsplit=1)
    if len(args) > 1:
        channel = args[1].strip()
    else:
        await message.reply_text("Send the channel username or ID to remove.")
        try:
            reply = await client.listen(message.chat.id, timeout=60)
            channel = reply.text.strip()
        except asyncio.TimeoutError:
            await message.reply_text("Timed out.")
            return
    try:
        ch = await client.get_chat(channel)
        await db.remove_channel(ch.id)
        await message.reply_text(f"Removed channel: {ch.title or ch.username} ({ch.id})")
    except Exception as e:
        await message.reply_text(f"Failed to remove channel: {e}")


@Client.on_message(filters.private & filters.command("list_channels"))
async def list_channels_handler(client, message):
    uid = message.from_user.id
    if not is_admin(uid):
        await message.reply_text("Only owner or admins can list channels.")
        return
    channels = await db.list_channels()
    if not channels:
        await message.reply_text("No channels configured.")
        return
    text = "Configured channels:\n"
    for c in channels:
        text += f"- {c.get('added_by')} -> {c.get('_id')}\n"
    await message.reply_text(text)


@Client.on_message(filters.private & filters.command("create_post"))
async def create_post_cmd(client, message):
    uid = message.from_user.id
    if not is_admin(uid):
        await message.reply_text("Only owner or admins can create posts.")
        return
    DRAFTS[uid] = {
        'messages': [],
        'url_buttons': [],
        'reactions': [],
        'target': None
    }
    await message.reply_text("Send me the message (text, media or album) you want to post. Send /cancel to abort.")
    try:
        msg = await client.listen(message.chat.id, timeout=300)
    except asyncio.TimeoutError:
        DRAFTS.pop(uid, None)
        await message.reply_text("Timed out. Please start creating the post again.")
        return

    if msg.text and msg.text.lower() == "/cancel":
        DRAFTS.pop(uid, None)
        await msg.reply_text("Cancelled.")
        return

    messages = [msg]
    mgid = getattr(msg, 'media_group_id', None)
    if mgid:
        while True:
            try:
                more = await client.listen(message.chat.id, timeout=1)
                if getattr(more, 'media_group_id', None) == mgid:
                    messages.append(more)
                else:
                    break
            except asyncio.TimeoutError:
                break
    DRAFTS[uid]['messages'] = messages

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Add URL Buttons", callback_data="add_url")],
        [InlineKeyboardButton("Add Reaction Buttons", callback_data="add_react")],
        [InlineKeyboardButton("Preview", callback_data="preview") , InlineKeyboardButton("Post", callback_data="post_now")],
        [InlineKeyboardButton("Cancel", callback_data="cancel_post")]
    ])

