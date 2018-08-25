from django.shortcuts import render, HttpResponse, get_object_or_404, HttpResponseRedirect, redirect, Http404
from .models import Dosya
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render
from django.db.models import Q

def dosya_index(request):
    dosya_list = Dosya.objects.all()

    query = request.GET.get('q')
    if query:
        dosya_list = dosya_list.filter(Q(baslik__icontains=query)|
                                         Q(metin__icontains=query)|
                                         Q(user__first_name__icontains=query)|
                                         Q(user__last_name__icontains=query)

                                    ).distinct()


    return render(request, 'dosya/index.html', {'dosyas':dosya_list})
