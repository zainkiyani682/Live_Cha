from django.shortcuts import render, get_object_or_404,redirect
from django.contrib.auth.decorators import login_required
from .models import *
from .forms import *
from django.http import Http404
from django.contrib import messages
# Create your views here.
@login_required
def chat_view(request, chatroom_name = 'public-chat'):
    chat_group = get_object_or_404(ChatGroup,group_name=chatroom_name)
    chat_message = chat_group.chat_message.all()[:30]
    form = ChatMessageCreateForm()
    other_user = None
    if chat_group.is_private:
        if request.user not in chat_group.members.all():
            raise Http404()
        for member in chat_group.members.all():
            if member!=request.user:
                other_user = member
                break

    if chat_group.groupchat_name:
        if request.user not in chat_group.members.all():
            if request.user.emailaddress_set.filter(verified=True).exists():
                chat_group.members.add(request.user)
            else:
                
                messages.warning(request, "You neeed to verify your email to join the chat!")
                return redirect('profile-settings')


    if request.htmx:
        form =  ChatMessageCreateForm(request.POST)
        if form.is_valid():
            message = form.save(commit=False)
            message.author = request.user
            message.group = chat_group
            message.save()
            context = {
                'message' : message,
                'user' : request.user
            }
            return render(request, 'a_rtchat/partials/chat_message_p.html', context)
    context = {
        'chat_messages': chat_message,
        'form': form, 
        'other_user':other_user, 
        'chatroom_name':chatroom_name,
        'chat_group':chat_group,

    }

    return render(request, 'a_rtchat/chat.html', context)

@login_required
def get_or_create_chatroom(request,username):
    if request.user.username == username:
        return redirect('home')
    other_user = User.objects.get(username=username)
    my_chatrooms = request.user.chat_group.filter(is_private=True)
    if my_chatrooms.exists():
        for chatroom in my_chatrooms:
            if other_user in chatroom.members.all():
                chatroom = chatroom
                break
            else:
                chatroom = ChatGroup.objects.create(is_private=True)
                chatroom.members.add(other_user,request.user)
    else:
        chatroom = ChatGroup.objects.create(is_private=True)
        chatroom.members.add(other_user,request.user)

    return redirect('chatroom', chatroom.group_name)

@login_required  
def create_groupchat(request):
     form = NewGroupForm()

     if request.method =='POST':
         form = NewGroupForm(request.POST)
         if form.is_valid():
             new_groupchat = form.save(commit=False)
             new_groupchat.admin = request.user
             new_groupchat.save()
             new_groupchat.members.add(request.user)
             return redirect('chatroom', new_groupchat.group_name)

     context = {
         'form':form
     }
     return render(request, 'a_rtchat/create_groupchat.html', context)


@login_required
def chatroom_edit_view(request,chatroom_name):
    chat_group = get_object_or_404(ChatGroup,group_name=chatroom_name)
    if request.user != chat_group.admin:
        raise Http404()
    form = ChatRoomEditForm(instance=chat_group)
    if request.method =="POST":
        form = ChatRoomEditForm(request.POST, instance=chat_group)
        if form.is_valid():
            form.save()
            remove_members = request.POST.getlist('remove_members')
            for member_id in remove_members:
                member = User.objects.get(id=member_id)
                chat_group.members.remove(member)

            return redirect('chatroom', chatroom_name)


    context = {
        'form':form,
        'chat_group': chat_group
    }

    return render(request, 'a_rtchat/chatroom_edit.html', context)

@login_required
def chatroom_delete_view(request,chatroom_name):
    chat_group = get_object_or_404(ChatGroup,group_name=chatroom_name)
    if request.user != chat_group.admin:
        raise Http404()
    
    if request.method =="POST":
        chat_group.delete()
        messages.success(request, 'Chatroom deleted')
        return redirect('home')

    return render(request, 'a_rtchat/chatroom_delete.html', {'chat_group': chat_group})

