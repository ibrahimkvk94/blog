from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy


class ParolaDegistirView(auth_views.PasswordChangeView):
    template_name = "registration/parola_degistir.html"
    success_url = reverse_lazy("core:panel")

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        if user.parola_degismeli:
            user.parola_degismeli = False
            user.save(update_fields=["parola_degismeli"])
        messages.success(self.request, "Parolanız değiştirildi.")
        return response
