from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """`parola_degismeli` işaretli kullanıcıyı parolasını değiştirene kadar parola sayfasına yönlendirir."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.parola_degismeli:
            serbest = (reverse("parola_degistir"), reverse("logout"))
            if request.path not in serbest and not request.path.startswith("/static/"):
                return redirect("parola_degistir")
        return self.get_response(request)
