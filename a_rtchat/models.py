from django.db import models
from django.contrib.auth.models import User
import shortuuid
from django.utils import timezone

# Create your models here.
class ChatGroup(models.Model):
    group_name = models.CharField(max_length=128,unique=True,default=shortuuid.uuid)
    groupchat_name = models.CharField(max_length=128, null=True,blank=True)
    admin = models.ForeignKey(User,related_name='groupschat',blank=True, null=True, on_delete=models.SET_NULL)

    user_online = models.ManyToManyField(User,related_name='online_in_groups',blank=True, null=True)
    members = models.ManyToManyField(User,related_name='chat_group', blank=True)
    is_private = models.BooleanField(default=False)
    

    def __str__(self):
        return self.group_name
    
class GroupMessage(models.Model):
    group = models.ForeignKey(ChatGroup, related_name='chat_message', on_delete=models.CASCADE)
    author = models.ForeignKey(User,on_delete=models.CASCADE)
    body = models.CharField(max_length=300)
    created = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.author.username} : {self.body}'

    class Meta:
        ordering = ['-created']
