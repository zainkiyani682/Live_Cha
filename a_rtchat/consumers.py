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

        unread_messages = self.chatroom.chat_message.filter(read=False).exclude(author=self.user)
        print(f"[UNREAD] {unread_messages.count()} unread messages found")

        for message in unread_messages:
            message.read = True
            message.save()

            print(f"[READ] Message {message.id} marked as read by {self.user}")

            async_to_sync(self.channel_layer.group_send)(
                self.chatroom_name,
                {
                    'type': 'message_read_broadcast',
                    'message_id': message.id,
                }
            )

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
            message = GroupMessage.objects.filter(id=message_id, group=self.chatroom).first()
            if message and message.author != self.user and not message.read:
                message.read = True
                message.save()
                print(f"[READ CONFIRM] Message {message.id} marked as read by {self.user}")

                async_to_sync(self.channel_layer.group_send)(
                    self.chatroom_name,
                    {
                        'type': 'message_read_broadcast',
                        'message_id': message.id,
                    }
                )

    def message_handler(self, event):
        message_id = event['message_id']
        message = GroupMessage.objects.get(id=message_id)
        print(f"[MESSAGE HANDLER] Broadcasting message {message_id}")

        if self.user != message.author and not message.read:
            message.read = True
            message.save()
            print(f"[AUTO-READ] Message {message.id} auto-marked read by {self.user}")

        context = {
            'message': message,
            'user': self.user,
        }
        html = render_to_string("a_rtchat/partials/chat_message_p.html", context)
        self.send(text_data=html)

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

        # Delete any other messages with same content & unread by this author (if needed)
        GroupMessage.objects.filter(
            group=message.group,
            body=message.body,
            read=False,
            author=message.author
        ).exclude(id=message.id).delete()

        context = {
            'message': message,
            'user': self.user,
        }

        html = render_to_string("a_rtchat/partials/chat_message_p.html", context)
        self.send(text_data=html)
