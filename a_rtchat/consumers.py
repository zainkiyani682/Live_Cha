from channels.generic.websocket import WebsocketConsumer
from .models import *
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from asgiref.sync import async_to_sync
import json

class ChatroomConsumer(WebsocketConsumer):
    def connect(self):
        self.user = self.scope['user']
        self.chatroom_name = self.scope['url_route']['kwargs']['chatroom_name']
        self.chatroom = get_object_or_404(ChatGroup, group_name=self.chatroom_name)

        async_to_sync(self.channel_layer.group_add)(
            self.chatroom_name, self.channel_name
        )

        print(f"[CONNECT] {self.user} joined chatroom '{self.chatroom_name}'")

        # Add and update online users
        if self.user not in self.chatroom.user_online.all():
            self.chatroom.user_online.add(self.user)
            print(f"[ONLINE] {self.user} marked as online in {self.chatroom_name}")
            self.update_online_count()

        self.accept()

        # Mark unread messages as read
        unread_messages = self.chatroom.chat_message.filter(read=False).exclude(author=self.user)
        print(f"[UNREAD] {unread_messages.count()} unread messages found")
        for message in unread_messages:
            self.mark_message_as_read(message.id)

    def disconnect(self, close_code):
        async_to_sync(self.channel_layer.group_discard)(
            self.chatroom_name, self.channel_name
        )

        print(f"[DISCONNECT] {self.user} left chatroom '{self.chatroom_name}'")

        if self.user in self.chatroom.user_online.all():
            self.chatroom.user_online.remove(self.user)
            print(f"[OFFLINE] {self.user} removed from online list in {self.chatroom_name}")
            self.update_online_count()

    def receive(self, text_data):
        text_data_json = json.loads(text_data)
        print(f"[RECEIVE] Data from {self.user}: {text_data_json}")

        if 'body' in text_data_json:
            body = text_data_json['body']
            message = GroupMessage.objects.create(
                body=body,
                author=self.user,
                group=self.chatroom,
            )
            print(f"[NEW MESSAGE] Message {message.id} created by {self.user}")

            async_to_sync(self.channel_layer.group_send)(
                self.chatroom_name,
                {
                    'type': 'message_handler',
                    'message_id': message.id,
                }
            )

        elif 'read_message_id' in text_data_json:
            message_id = text_data_json['read_message_id']
            self.mark_message_as_read(message_id)

    def message_handler(self, event):
        message_id = event['message_id']
        message = GroupMessage.objects.get(id=message_id)

        if self.user != message.author:
            if not message.delivered_to.filter(id=self.user.id).exists():
                message.delivered_to.add(self.user)

            if self.user in self.chatroom.user_online.all():
                self.mark_message_as_read(message.id)

        group_members = self.chatroom.members.exclude(id=message.author.id)
        read_by_count = message.read_by.exclude(id=message.author.id).count()
        delivered_to_count = message.delivered_to.exclude(id=message.author.id).count() + 1

        context = {
            'message': message,
            'user': self.user,
            'chat_group': self.chatroom,
            'read_by_count': read_by_count,
            'delivered_to_count': delivered_to_count,
            'total_members': group_members.count(),
        }
        print(read_by_count,'read_by_count---')

        html = render_to_string("a_rtchat/partials/chat_message_p.html", context)
        self.send(text_data=html)
   
    def broadcast_message_html(self, event):
        self.send(text_data=event["html"])
    

    def update_online_count(self):
        online_count = self.chatroom.user_online.count() - 1
        print(f"[ONLINE COUNT] {online_count} users online (excluding current) in {self.chatroom_name}")

        async_to_sync(self.channel_layer.group_send)(
            self.chatroom_name,
            {
                'type': 'online_count_handler',
                'online_count': online_count
            }
        )

    def online_count_handler(self, event):
        online_count = event['online_count']
        print(f"[ONLINE COUNT HANDLER] Sending updated count: {online_count}")

        context = {
            'online_count': online_count,
            'chat_group': self.chatroom
        }
        html = render_to_string("a_rtchat/partials/online_count.html", context)
        self.send(text_data=html)

    def message_read_broadcast(self, event):
        message_id = event['message_id']
        message = GroupMessage.objects.get(id=message_id)

        context = {
            'message': message,
            'user': self.user,
            'chat_group': self.chatroom,
            'read_by_count': message.read_by.exclude(id=message.author.id).count(),
            'total_members': message.group.members.exclude(id=message.author.id).count(),
            'delivered_to_count': message.delivered_to.exclude(id=message.author.id).count(),
        }
        html = render_to_string("a_rtchat/partials/chat_message_p.html", context)
        self.send(text_data=html)

    def chat_message_status(self, event):
        message_id = event['message_id']
        status = event['status']
        message = GroupMessage.objects.get(id=message_id)
        print(message)

        context = {
            'message': message,
            'user': self.user,
            'chat_group': self.chatroom,
            'read_by_count': message.read_by.exclude(id=message.author.id).count(),
            'total_members': message.group.members.exclude(id=message.author.id).count(),
            'delivered_to_count': message.delivered_to.exclude(id=message.author.id).count(),
            'status': status,
        }

        html = render_to_string("a_rtchat/partials/chat_message_p.html", context)
        self.send(text_data=html)
   
    def mark_message_as_read(self, message_id):
        try:
            message = GroupMessage.objects.get(id=message_id)
        except GroupMessage.DoesNotExist:
            return

        user = self.scope["user"]

        if user in message.read_by.all():
            return

        message.read_by.add(user)
        message.save()

        group_members = message.group.members.all()
        print(group_members, 'in mark_message_as_read')
        if message.group.is_private:
            if message.read_by.count() == 2:
                async_to_sync(self.channel_layer.group_send)(
                    self.chatroom_name,
                    {
                        "type": "chat_message_status",
                        "message_id": message_id,
                        "status": "read",
                    }
                )
        else:
            if set(message.read_by.all()) == set(group_members):
                print(set(message.read_by.all()), set(group_members), 'in else')
                async_to_sync(self.channel_layer.group_send)(
                    self.chatroom_name,
                    {
                        "type": "chat_message_status",
                        "message_id": message_id,
                        "status": "read",
                    }
                )
            else:
                async_to_sync(self.channel_layer.group_send)(
                    self.chatroom_name,
                    {
                        "type": "chat_message_status",
                        "message_id": message_id,
                        "status": "delivered",
                    }
                )
        print(f"[MESSAGE READ] Message {message_id} marked as read by {user.username}")
   