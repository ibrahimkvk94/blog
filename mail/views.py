from django.shortcuts import render, HttpResponse, get_object_or_404, HttpResponseRedirect, redirect, Http404
from .models import Abone
from django.db.models import F
from django.contrib import messages
from django.core.mail import send_mail
# Create your views here.
def abone_create(request):
    if request.method == "POST":
        if Abone.objects.filter(mail__contains = request.POST.get("baslik")):
            messages.success(request, "ama zaten üyesin.")
        else:
            yeniAbone = Abone(mail =  request.POST.get("baslik"))
            yeniAbone.save()

    return redirect('home')
def mail_sender(mailx):
    send_mail('ibrahimkavak.com Yeni Yazı Paylaşıldı.',
    'Merhaba, sayın abonemiz ibrahimkavak.com da yeni yazı paylaştık. Okumak için hemen sitemizi ziyaret ediniz.',
    'ibrahimkvk94@gmail.com',
    [mailx],
    fail_silently=False)
    return "Mail Send"