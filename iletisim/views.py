from django.shortcuts import render, HttpResponse, get_object_or_404, HttpResponseRedirect, redirect, Http404
from django.contrib import messages
from django.shortcuts import render
from .forms import MesajForm
from django.core.mail import BadHeaderError, send_mail
from django.http import HttpResponse, HttpResponseRedirect

def iletisim_index(request):
    if request.method == "POST":
        form = MesajForm(request.POST or None, request.FILES or None)
        if form.is_valid():
            mesaj = form.save(commit=False)
            mesaj.save()
            messages.success(request, "Mesaj Gönderildi.",extra_tags='mesaj-basarili')
            return HttpResponseRedirect(mesaj.get_absolute_url())

    else:
        form = MesajForm()

    context = {'form':form,}

    return render(request, 'contact.html', context)


