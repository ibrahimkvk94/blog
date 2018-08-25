from django.shortcuts import render, HttpResponse, get_object_or_404, HttpResponseRedirect, redirect, Http404
from post.models import Post
from post.forms import PostForm,CommentForm
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render
from django.db.models import Q

# Create your views here.

def home_view(request):
    post_list = Post.objects.all()

    queryK = request.GET.get('r')
    if queryK:
        post_list = post_list.filter(Q(kategori__icontains=queryK)
                                
                                ).distinct()
    query = request.GET.get('q')
    if query:
        post_list = post_list.filter(Q(baslik__icontains=query)|
                                         Q(metin__icontains=query)|
                                          Q(tags__icontains=query)|
                                         Q(user__first_name__icontains=query)|
                                       
                                         Q(user__last_name__icontains=query)

                                    ).distinct()


    paginator = Paginator(post_list, 5)  # Show 25 contacts per page
    
    page = request.GET.get('page')
    try:
        posts = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        posts = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        posts = paginator.page(paginator.num_pages)
    
    post_list2 = Post.objects.all()

    post_list2 = post_list.order_by('like')


    paginator2 = Paginator(post_list2, 5)  # Show 25 contacts per page

    page2 = request.GET.get('page')
    try:
        posts2 = paginator.page(page2)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        posts2 = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        posts2 = paginator.page(paginator.num_pages)


    return render(request, 'home.html', {'posts':posts,'posts2':posts2, 'range': range(1,paginator.num_pages+1)})
def hakkimda_view(request):
        return render(request, 'about.html')