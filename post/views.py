from django.shortcuts import render, HttpResponse, get_object_or_404, HttpResponseRedirect, redirect, Http404
from .models import Post
from .forms import PostForm,CommentForm
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import render
from django.db.models import Q

        
def post_index(request):
    post_list = Post.objects.all()

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
    return render(request, 'post/index.html', {'posts':posts, 'range': range(int(paginator.num_pages))})

def post_detail(request, slug):
    post = get_object_or_404(Post, slug=slug)
    form = CommentForm(request.POST or None)
    if form.is_valid():
        comments = form.save(commit=False)
        comments.post = post
        comments.save()
        return HttpResponseRedirect(post.get_absolute_url())


    context = {'post' : post,
               'form':form,}

    return render(request, 'post/single2.html', context)


def post_create(request):
    if not request.user.is_authenticated:
        return Http404()
    if request.method == "POST":
        form = PostForm(request.POST or None, request.FILES or None)
        if form.is_valid():
            post = form.save(commit=False)
            post.user = request.user
            post.save()
            messages.success(request, "Başarılı bir şekilde oluşturdunuz.",extra_tags='mesaj-basarili')
            return HttpResponseRedirect(post.get_absolute_url())

    else:
        form = PostForm()

    context = {'form':form,}

    return render(request, 'post/form.html', context)

def post_upload(request):
    return render(request,'uploads.html')

def post_update(request, slug):
    if not request.user.is_authenticated:
        return Http404()
    post = get_object_or_404(Post, slug=slug)
    form = PostForm(request.POST or None,request.FILES or None,instance=post )
    if form.is_valid():
        form.save()
        messages.success(request, "Başarılı bir şekilde değiştirdiniz." ,extra_tags='mesaj-basarili')
        return HttpResponseRedirect(post.get_absolute_url())
    context = {'form': form, }

    return render(request, 'post/form.html', context)

def post_delete(request,slug):
    if not request.user.is_authenticated:
        return Http404()

    post = get_object_or_404(Post, slug=slug)
    post.delete()
    messages.success(request, "Başarılı bir şekilde sildiniz.")
    return redirect('post:index')

def like(request,slug):
    post = get_object_or_404(Post, slug=slug)
    form = PostForm(request.POST or None,request.FILES or None,instance=post )
    post.like=post.like+1
    post.save()
    context = {'post' : post,
                'form':form,}
    return render(request, 'post/single2.html', context)

def BestRead(request):
    post_list = Post.objects.all()

    post_list = post_list.order_by('like')


    paginator = Paginator(post_list, 6)  # Show 25 contacts per page

    page = request.GET.get('page')
    try:
        posts = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        posts = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        posts = paginator.page(paginator.num_pages)
    return render(request, 'post/index.html', {'posts2':posts})
