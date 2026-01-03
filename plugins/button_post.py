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


async def send_draft_menu(client, chat_id: int, uid: int):
    """Send or update an interactive draft menu to the admin with edit/remove options."""
    draft = DRAFTS.get(uid)
    if not draft:
        await client.send_message(chat_id, "No active draft.")
        return

    # Build control keyboard
    ctrl_kb = []
    # URL controls
    ctrl_kb.append([
        InlineKeyboardButton("Edit URL Buttons", callback_data=f"edit_url|{uid}"),
        InlineKeyboardButton("Remove URL Buttons", callback_data=f"remove_url|{uid}")
    ])
    # Reaction controls
    ctrl_kb.append([
        InlineKeyboardButton("Edit Reactions", callback_data=f"edit_react|{uid}"),
        InlineKeyboardButton("Remove Reactions", callback_data=f"remove_react|{uid}")
    ])
    # Preview / Post
    ctrl_kb.append([
        InlineKeyboardButton("Preview", callback_data=f"preview_draft|{uid}"),
        InlineKeyboardButton("Post (Choose Channel)", callback_data=f"choose_channel|{uid}")
    ])
    ctrl_kb.append([InlineKeyboardButton("Cancel", callback_data=f"cancel_post|{uid}")])

    kb = InlineKeyboardMarkup(ctrl_kb)

    # send a preview copy of the first draft message (if exists)
    if draft['messages']:
        first = draft['messages'][0]
        try:
            await client.copy_message(chat_id=chat_id, from_chat_id=first.chat.id, message_id=first.message_id, reply_markup=kb)
        except Exception:
            # fallback: send a short summary
            text = "Draft saved. Use the buttons below to edit or post."
            if draft.get('url_buttons'):
                text += f"\nURL buttons: {sum(len(r) for r in draft['url_buttons'])}"
            if draft.get('reactions'):
                text += f"\nReactions: {' '.join(draft['reactions'])}"
            await client.send_message(chat_id, text, reply_markup=kb)
    else:
        await client.send_message(chat_id, "Draft saved. Use the buttons below to edit or post.", reply_markup=kb)


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
            await cb.message.reply_text("Only bot owner or admins can create posts.")
            return
        DRAFTS[uid] = {'messages': [], 'url_buttons': [], 'reactions': [], 'target': None}
        await cb.message.reply_text("Send me the message (text, media or album) you want to post. Send /cancel to abort.")
        try:
            msg = await client.listen(cb.message.chat.id, timeout=300)
        except asyncio.TimeoutError:
            DRAFTS.pop(uid, None)
            await cb.message.reply_text("Timed out. Please start creating the post again.")
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
        # support cancel coming from menu with |uid suffix
        if "|" in data:
            # example 'cancel_post|<uid>'
            DRAFTS.pop(uid, None)
            await cb.answer("Cancelled")
            await cb.message.edit_text("Draft cancelled.")
            return
        DRAFTS.pop(uid, None)
        await cb.answer("Cancelled")
        await cb.message.edit_text("Draft cancelled.")
        return

    if data == "add_url":
        await cb.answer()
        # support callback that may include uid suffix
        if "|" in data:
            _, _uid = data.split("|", 1)
            uid = int(_uid)
        if uid not in DRAFTS:
            await cb.message.reply_text("No active draft. Start with Create Post.")
            return
        await cb.message.reply_text("Send me a list of URL buttons for the message. Use this format:\nButton text 1 - http://example.com | Button text 2 - http://...\nYou can use '|' to put buttons in same row. Send /done when finished or /cancel to abort.")
        try:
            msg = await client.listen(cb.message.chat.id, timeout=300)
        except asyncio.TimeoutError:
            await cb.message.reply_text("Timed out. Returning to menu.")
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
        await send_draft_menu(client, cb.message.chat.id, uid)
        return

    if data == "add_react":
        await cb.answer()
        # support callback with uid suffix
        if "|" in data:
            _, _uid = data.split("|", 1)
            uid = int(_uid)
        if uid not in DRAFTS:
            await cb.message.reply_text("No active draft. Start with Create Post.")
            return
        await cb.message.reply_text("Send emojis (space separated or in one message). Each emoji will become a reaction button. Send /done when finished or /cancel to abort.")
        try:
            msg = await client.listen(cb.message.chat.id, timeout=300)
        except asyncio.TimeoutError:
            await cb.message.reply_text("Timed out. Returning to menu.")
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
        await send_draft_menu(client, cb.message.chat.id, uid)
        return

    if data == "preview" or data.startswith("preview_draft"):
        await cb.answer()
        # allow callback with |uid suffix
        if "|" in data:
            _, _uid = data.split("|", 1)
            uid = int(_uid)
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

    async def post_draft_to_target(client, uid, target_id, reply_chat_id):
        """Helper to post a draft to a target channel id and notify the requester."""
        if uid not in DRAFTS:
            await client.send_message(reply_chat_id, "No active draft.")
            return
        draft = DRAFTS[uid]
        keyboard = []
        if draft.get('url_buttons'):
            keyboard.extend(draft['url_buttons'])
        kb = InlineKeyboardMarkup(keyboard) if keyboard else None

        posted_msg_id = None
        first = True
        for m in draft['messages']:
            try:
                if first:
                    sent = await client.copy_message(chat_id=target_id, from_chat_id=m.chat.id, message_id=m.message_id, reply_markup=kb)
                    posted_msg_id = sent.message_id
                    first = False
                else:
                    await client.copy_message(chat_id=target_id, from_chat_id=m.chat.id, message_id=m.message_id)
            except Exception as e:
                await client.send_message(reply_chat_id, f"Failed to post message: {e}")
                return

        if draft.get('reactions') and posted_msg_id:
            try:
                current_kb = []
                if draft.get('url_buttons'):
                    current_kb.extend(draft['url_buttons'])
                row = []
                for e in draft['reactions']:
                    b = e.encode('utf-8').hex()
                    cbdata = f"react|{target_id}|{posted_msg_id}|{b}"
                    row.append(InlineKeyboardButton(f"{e} 0", callback_data=cbdata))
                current_kb.append(row)
                await client.edit_message_reply_markup(target_id, posted_msg_id, reply_markup=InlineKeyboardMarkup(current_kb))
            except Exception:
                pass

        # persist post metadata
        try:
            await db.save_post(target_id, posted_msg_id, emoji_order=draft.get('reactions'))
        except Exception:
            pass

        await client.send_message(reply_chat_id, "Posted successfully.")
        DRAFTS.pop(uid, None)

    if data == "post_now":
        # legacy path: keep for backward compatibility
        await cb.answer()
        if uid not in DRAFTS:
            await cb.message.reply_text("No active draft.")
            return
        await cb.message.reply_text("Send the channel username (eg @channelusername) or channel ID (eg -10012345) where I should post. I must be admin in that channel.")
        try:
            ch = await client.listen(cb.message.chat.id, timeout=300)
        except asyncio.TimeoutError:
            await cb.message.reply_text("Timed out. Post aborted.")
            return
        if ch.text and ch.text.lower() == "/cancel":
            await ch.reply_text("Cancelled.")
            return
        channel = ch.text.strip()
        # try to resolve chat
        try:
            target = await client.get_chat(channel)
        except Exception as e:
            await ch.reply_text("Could not find that channel. Make sure I am in the channel and provided the correct username or ID.")
            return
        # check bot privileges (robust check)
        try:
            member = await client.get_chat_member(target.id, (await client.get_me()).id)
            if not (str(member.status).lower() in ("administrator", "creator") or getattr(member, 'can_post_messages', False)):
                await ch.reply_text("I am not an admin in that channel. Please make me admin (with right to post/edit) and try again.")
                return
        except Exception:
            pass

        # delegate to shared poster routine
        await post_draft_to_target(client, uid, target.id, cb.message.chat.id)
        return

    if data.startswith("choose_channel"):
        await cb.answer()
        # data may be 'choose_channel' or 'choose_channel|<uid>'
        if "|" in data:
            _, _uid = data.split("|", 1)
            uid = int(_uid)
        # list configured channels
        channels = await db.list_channels()
        if not channels:
            await cb.message.reply_text("No configured channels. Use /add_channel first or specify a channel id manually with 'Post Now' option.")
            return
        rows = []
        for c in channels:
            ch_id = c.get('_id')
            # try to fetch a friendly label
            label = str(ch_id)
            try:
                chinfo = await client.get_chat(ch_id)
                label = chinfo.title or chinfo.username or str(ch_id)
            except Exception:
                pass
            rows.append([InlineKeyboardButton(label, callback_data=f"post_to|{uid}|{ch_id}")])
        rows.append([InlineKeyboardButton("Custom channel (enter id)", callback_data=f"post_custom|{uid}")])
        rows.append([InlineKeyboardButton("Back", callback_data=f"preview_draft|{uid}")])
        await cb.message.reply_text("Choose channel:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("post_to|"):
        await cb.answer()
        # format: post_to|<uid>|<ch_id>
        try:
            _, _uid, ch_id = data.split("|", 2)
            uid = int(_uid)
            ch_id = int(ch_id)
        except Exception:
            await cb.message.reply_text("Invalid channel selection.")
            return
        # check bot privileges
        try:
            member = await client.get_chat_member(ch_id, (await client.get_me()).id)
            if not (str(member.status).lower() in ("administrator", "creator") or getattr(member, 'can_post_messages', False)):
                await cb.message.reply_text("I am not an admin in that channel. Please make me admin (with right to post/edit) and try again.")
                return
        except Exception:
            await cb.message.reply_text("Could not verify admin status. Make sure I am a member/admin in that channel.")
            return
        # proceed to post
        await post_draft_to_target(client, uid, ch_id, cb.message.chat.id)
        return

    if data.startswith("post_custom|"):
        await cb.answer()
        _, _uid = data.split("|", 1)
        uid = int(_uid)
        await cb.message.reply_text("Send the channel username (eg @channelusername) or channel ID (eg -10012345) where I should post. I must be admin in that channel.")
        try:
            ch = await client.listen(cb.message.chat.id, timeout=300)
        except asyncio.TimeoutError:
            await cb.message.reply_text("Timed out. Post aborted.")
            return
        if ch.text and ch.text.lower() == "/cancel":
            await ch.reply_text("Cancelled.")
            return
        try:
            target = await client.get_chat(ch.text.strip())
            ch_id = target.id
        except Exception:
            await ch.reply_text("Could not find that channel. Make sure I am in the channel and provided the correct username or ID.")
            return
        # verify admin
        try:
            member = await client.get_chat_member(ch_id, (await client.get_me()).id)
            if not (str(member.status).lower() in ("administrator", "creator") or getattr(member, 'can_post_messages', False)):
                await ch.reply_text("I am not an admin in that channel. Please make me admin (with right to post/edit) and try again.")
                return
        except Exception:
            pass
        await post_draft_to_target(client, uid, ch_id, cb.message.chat.id)
        return

    if data.startswith("edit_url|") or data.startswith("edit_url"):
        await cb.answer()
        if "|" in data:
            _, _uid = data.split("|",1)
            uid = int(_uid)
        if uid not in DRAFTS:
            await cb.message.reply_text("No active draft.")
            return
        await cb.message.reply_text("Send me a list of URL buttons (Label - URL | Label2 - URL2). Send /cancel to abort.")
        try:
            msg = await client.listen(cb.message.chat.id, timeout=300)
        except asyncio.TimeoutError:
            await cb.message.reply_text("Timed out.")
            return
        if msg.text and msg.text.lower() == "/cancel":
            await msg.reply_text("Cancelled.")
            return
        rows = parse_url_buttons(msg.text)
        if not rows:
            await msg.reply_text("Could not parse any buttons. No changes made.")
            return
        DRAFTS[uid]['url_buttons'] = rows
        await msg.reply_text("URL buttons updated.")
        await send_draft_menu(client, cb.message.chat.id, uid)
        return

    if data.startswith("remove_url|") or data == "remove_url":
        await cb.answer()
        if "|" in data:
            _, _uid = data.split("|",1)
            uid = int(_uid)
        if uid in DRAFTS:
            DRAFTS[uid]['url_buttons'] = []
        await cb.message.reply_text("URL buttons removed.")
        await send_draft_menu(client, cb.message.chat.id, uid)
        return

    if data.startswith("edit_react|") or data == "edit_react":
        await cb.answer()
        if "|" in data:
            _, _uid = data.split("|",1)
            uid = int(_uid)
        if uid not in DRAFTS:
            await cb.message.reply_text("No active draft.")
            return
        await cb.message.reply_text("Send emojis (space separated) to set reaction buttons. Send /cancel to abort.")
        try:
            msg = await client.listen(cb.message.chat.id, timeout=300)
        except asyncio.TimeoutError:
            await cb.message.reply_text("Timed out.")
            return
        if msg.text and msg.text.lower() == "/cancel":
            await msg.reply_text("Cancelled.")
            return
        emojis = parse_reactions(msg.text)
        if not emojis:
            await msg.reply_text("No emojis detected. No changes made.")
            return
        DRAFTS[uid]['reactions'] = emojis
        await msg.reply_text(f"Reactions updated: {' '.join(emojis)}")
        await send_draft_menu(client, cb.message.chat.id, uid)
        return

    if data.startswith("remove_react|") or data == "remove_react":
        await cb.answer()
        if "|" in data:
            _, _uid = data.split("|",1)
            uid = int(_uid)
        if uid in DRAFTS:
            DRAFTS[uid]['reactions'] = []
        await cb.message.reply_text("Removed reactions.")
        await send_draft_menu(client, cb.message.chat.id, uid)
        return

    if data.startswith("react|"):
        await cb.answer()
        try:
            _, ch_id_s, msg_id_s, emo_hex = data.split("|", 3)
            ch_id = int(ch_id_s)
            msg_id = int(msg_id_s)
            emoji = bytes.fromhex(emo_hex).decode('utf-8')
        except Exception:
            await cb.answer("Invalid reaction data.")
            return

        # increment and fetch new count
        try:
            newcount = await db.increment_reaction(ch_id, msg_id, emoji)
        except Exception:
            newcount = None

        # try to rebuild keyboard: preserve existing url buttons if any
        try:
            msg = await client.get_messages(ch_id, msg_id)
            current_kb = []
            if msg.reply_markup and getattr(msg.reply_markup, 'inline_keyboard', None):
                # copy existing rows except possible old reaction row (we'll append a new reaction row)
                for row in msg.reply_markup.inline_keyboard:
                    # check if this row looks like reaction row by inspecting callback_data of first button
                    is_react_row = False
                    for btn in row:
                        if getattr(btn, 'callback_data', None) and str(btn.callback_data).startswith('react|'):
                            is_react_row = True
                            break
                    if not is_react_row:
                        new_row = []
                        for btn in row:
                            # reconstruct original button (url or callback)
                            if getattr(btn, 'url', None):
                                new_row.append(InlineKeyboardButton(btn.text, url=btn.url))
                            else:
                                new_row.append(InlineKeyboardButton(btn.text, callback_data=btn.callback_data))
                        current_kb.append(new_row)
            else:
                current_kb = []

            # fetch post info to get emoji order and counts
            post = await db.get_post(ch_id, msg_id)
            emoji_order = post.get('emoji_order') if post else []
            react_row = []
            for e in emoji_order or [emoji]:
                b = e.encode('utf-8').hex()
                cnt = 0
                if post and post.get('reactions'):
                    cnt = post.get('reactions', {}).get(e, 0)
                react_row.append(InlineKeyboardButton(f"{e} {cnt}", callback_data=f"react|{ch_id}|{msg_id}|{b}"))
            if react_row:
                current_kb.append(react_row)

            await client.edit_message_reply_markup(ch_id, msg_id, reply_markup=InlineKeyboardMarkup(current_kb))
        except Exception:
            pass

        return


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

