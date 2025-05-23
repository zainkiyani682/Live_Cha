from channels.generic.websocket import AsyncWebsocketConsumer
from .models import *
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
import json
from asgiref.sync import sync_to_async
class ChatroomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope['user']
        self.chatroom_name = self.scope['url_route']['kwargs']['chatroom_name']
        self.chatroom = await self.get_chatroom(self.chatroom_name)

        await self.channel_layer.group_add(
            self.chatroom_name, self.channel_name
        )

        print(f"[CONNECT] {self.user} joined chatroom '{self.chatroom_name}'")

        # Add and update online users
        if self.user not in await self.get_online_users():
            await self.add_online_user(self.user)
            print(f"[ONLINE] {self.user} marked as online in {self.chatroom_name}")
            await self.update_online_count()

        await self.accept()

        # Mark unread messages as read
        # unread_messages = await self.get_unread_messages()
        # print(f"[UNREAD] {len(unread_messages)} unread messages found")
        # for message in unread_messages:
        #     await self.mark_message_as_read(message.id)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.chatroom_name, self.channel_name
        )

        print(f"[DISCONNECT] {self.user} left chatroom '{self.chatroom_name}'")

        if self.user in await self.get_online_users():
            await self.remove_online_user(self.user)
            print(f"[OFFLINE] {self.user} removed from online list in {self.chatroom_name}")
            await self.update_online_count()

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        print(f"[RECEIVE] Data from {self.user}: {text_data_json}")

        if 'body' in text_data_json:
            body = text_data_json['body']
            message = await self.create_message(body)
            print(f"[NEW MESSAGE] Message {message.id} created by {self.user}")

            await self.channel_layer.group_send(
                self.chatroom_name,
                {
                    'type': 'message_handler',
                    'message_id': message.id,
                }
            )

        elif 'read_message_id' in text_data_json:
            message_id = text_data_json['read_message_id']
            print(f"[READ MESSAGE] User {self.user} read message {message_id}")
            await self.mark_message_as_read(message_id)

    async def message_handler(self, event):
        message_id = event['message_id']
        message = await self.get_message(message_id)
        print("in message")

        message_author = await sync_to_async(lambda: message.author)()
        print(f"[MESSAGE HANDLER] Message author: {message_author}")

        # Only mark as delivered if not the author and not already delivered
        if self.user != message_author:
            if not await self.is_message_delivered_to_user(message, self.user):
                print(f"[DELIVERED] Message {message_id} delivered to {self.user}")
                await self.add_message_to_delivered(message, self.user)

        # Get group members excluding author
        group_members = await self.get_group_members_excluding_author(message)
        read_by_count = await self.get_read_by_count(message)
        delivered_to_count = await self.get_delivered_to_count(message)
        total_members = len(group_members)
        print(f"[MESSAGE HANDLER---] Read by count: {read_by_count}, Delivered to count: {delivered_to_count}, Total members: {total_members}")
        # Status logic: Only non-author members count
        if total_members > 0 and read_by_count == total_members:
            status = "read"
        elif delivered_to_count > 0:
            status = "delivered"
        else:
            status = "sent"

        context = {
            'message': message,
            'user': message.author,
            'chat_group': self.chatroom,
            'read_by_count': read_by_count,
            'delivered_to_count': delivered_to_count,
            'total_members': total_members,
            'status': status or "delivered"
        }

        html = await sync_to_async(render_to_string)("a_rtchat/partials/chat_message_p.html", context)
        await self.send(text_data=html)

    async def broadcast_message_html(self, event):
            await self.send(text_data=event["html"])

    async def update_online_count(self):
        online_count = len(await self.get_online_users()) - 1
        print(f"[ONLINE COUNT] {online_count} users online (excluding current) in {self.chatroom_name}")

        await self.channel_layer.group_send(
            self.chatroom_name,
            {
                'type': 'online_count_handler',
                'online_count': online_count
            }
        )

    async def online_count_handler(self, event):
        online_count = event['online_count'] + 1
        print(f"[ONLINE COUNT HANDLER] Sending updated count: {online_count}")

        context = {
            'online_count': online_count,
            'chat_group': self.chatroom
        }

        # Wrap render_to_string with sync_to_async
        html = await sync_to_async(render_to_string)("a_rtchat/partials/online_count.html", context)
        await self.send(text_data=html)

    async def get_message_status(self, message):
        group_members = await self.get_group_members_excluding_author(message)
        read_by_count = await self.get_read_by_count(message)
        delivered_to_count = await self.get_delivered_to_count(message)
        total_members = len(group_members)
        print(f"[MESSAGE STATUS] Read by count: {read_by_count}, Delivered to count: {delivered_to_count}, Total members: {total_members}")
        if total_members > 0 and read_by_count == total_members:
            return "read"
        elif delivered_to_count > 0:
            return "delivered"
        else:
            return "sent"

    async def mark_message_as_read(self, message_id):
        try:
            message = await self.get_message(message_id)
        except GroupMessage.DoesNotExist:
            return

        user = self.scope["user"]

        # Check if the user has already read the message
        if user in await self.get_message_read_by(message):
            return

        # Add the user to the read_by list
        await self.add_message_to_read_by(message, user)

        # Consistent status calculation
        status = await self.get_message_status(message)

        # Broadcast the status update to the group
        await self.channel_layer.group_send(
            self.chatroom_name,
            {
                "type": "chat_message_status",
                "message_id": message_id,
                "status": status,
            }
        )

        print(f"[MESSAGE READ] Message {message_id} marked as {status} by {user.username}")

    async def chat_message_status(self, event):
        message_id = event['message_id']
        status = event['status']

        # Fetch the message object
        message = await self.get_message(message_id)

        # Consistent status calculation for rendering
        group_members = await self.get_group_members_excluding_author(message)
        read_by_count = await self.get_read_by_count(message)
        delivered_to_count = await self.get_delivered_to_count(message)
        total_members = len(group_members)
        context = {
            'message': message,
            'user': message.author,
            'chat_group': self.chatroom,
            'read_by_count': read_by_count,
            'delivered_to_count': delivered_to_count,
            'total_members': total_members,
            'status': status,
        }
        html = await sync_to_async(render_to_string)("a_rtchat/partials/chat_message_p.html", context)
        await self.send(text_data=html)

    # Helper methods for async database operations
    async def get_chatroom(self, chatroom_name):
        return await ChatGroup.objects.filter(group_name=chatroom_name).afirst()

    async def get_online_users(self):
        print(f"[GET ONLINE USERS] Fetching online users for {self.chatroom_name}")
        return await sync_to_async(list)(self.chatroom.user_online.all())

    async def add_online_user(self, user):
        await sync_to_async(self.chatroom.user_online.add)(user)

    async def remove_online_user(self, user):
        await sync_to_async(self.chatroom.user_online.remove)(user)

    async def get_unread_messages(self):
       return await sync_to_async(list)(
        self.chatroom.chat_message.filter(read=False).exclude(author=self.user).all()
    )

    async def create_message(self, body):
        return await GroupMessage.objects.acreate(body=body, author=self.user, group=self.chatroom)

    async def get_message(self, message_id):
        return await GroupMessage.objects.filter(id=message_id).afirst()

    async def is_message_delivered_to_user(self, message, user):
        return await message.delivered_to.filter(id=user.id).aexists()

    async def add_message_to_delivered(self, message, user):
        await sync_to_async(message.delivered_to.add)(user)

    async def get_group_members_excluding_author(self, message):
        group = await sync_to_async(lambda: message.group)()
        return await sync_to_async(list)(group.members.exclude(id=message.author.id).all())


    async def get_read_by_count(self, message):
        author_id = await sync_to_async(lambda: message.author.id)()
        return await sync_to_async(lambda: message.read_by.exclude(id=author_id).count())()

    async def get_delivered_to_count(self, message):
        author_id = await sync_to_async(lambda: message.author.id)()
        return await sync_to_async(lambda: message.delivered_to.exclude(id=author_id).count())()

    async def get_message_read_by(self, message):
         return await sync_to_async(list)(message.read_by.all())

    async def add_message_to_read_by(self, message, user):
        await sync_to_async(message.read_by.add)(user)

    async def get_group_members(self, message):
        group = await sync_to_async(lambda: message.group)()
        return await sync_to_async(list)(group.members.all())