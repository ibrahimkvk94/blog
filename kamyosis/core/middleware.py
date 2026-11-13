from django.core.exceptions import PermissionDenied

from .kisayollar import kapali_mi


class BolumKisayolMiddleware:
    """Bölüm hesabına kapatılmış kısayolun sayfaları açılmaz (menü dışından, ör. ana sayfa kartı ya da adres yazarak)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and kapali_mi(user, request.resolver_match):
            raise PermissionDenied("Bu sayfa bölümünüzün kullanımına kapalı.")
        return None
