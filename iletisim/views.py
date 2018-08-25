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

def send_email(request):
    subject = "Konu"
    message = "Selam"
    from_email = "mail@ibrahimkavak.com"
    if subject and message and from_email:
        try:
            send_mail(subject, message, from_email, ['ibrahimkvk94@gmail.com'])
        except BadHeaderError:
            return HttpResponse('Invalid header found.')
        return HttpResponseRedirect('contact.html')
    else:
        # In reality we'd use a form class
        # to get proper validation errors.
        return HttpResponse('Make sure all fields are entered and valid.')