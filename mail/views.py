from django.shortcuts import render, HttpResponse, get_object_or_404, HttpResponseRedirect, redirect, Http404
from .models import Abone
from django.db.models import F
from django.contrib import messages

# Create your views here.
def abone_create(request):
    if request.method == "POST":
        if Abone.objects.filter(mail__contains = request.POST.get("baslik")):
            messages.success(request, "ama zaten üyesin.")
        else:
            yeniAbone = Abone(mail =  request.POST.get("baslik"))
            yeniAbone.save()

    return redirect('home')
