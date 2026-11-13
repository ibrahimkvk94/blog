"""Modüller: ana sayfadaki "Ders Planlama", "Sınav Planlama" gibi bölümler.

Her modül kendi Django uygulamasıdır ve AppConfig.ready() içinde register() ile kendini tanıtır; ana sayfa, sol
menü, program değiştirici ve yetki denetimi bu kayıttan okunur. Yeni modül eklemek için timetable'a dokunmak
gerekmez: uygulamayı INSTALLED_APPS'e ve URL'lerini config/urls.py'ye ekleyip ready()'de register() çağırmak yeter.

Ortak veri (kurum, program, sınıf, öğretmen, derslik, ders adı, ders) timetable uygulamasındadır ve bütün modüller
onu kullanır. Ortak veri sayfaları (SHARED_ROUTES) hangi modülden açıldıysa o modülün menüsüyle görünür.

Erişim: kurum üyeliğinde modül seçilmemişse kullanıcı bütün modülleri görür (Membership.modules boş = tümü);
seçilmişse yalnızca onları. Modül içindeki işlemler yine kurum yetkileriyle (görüntüleme, veri girişi ...) denetlenir.
"""

from dataclasses import dataclass, field

from django.urls import reverse


@dataclass
class Module:
    key: str  # Membership.modules içinde saklanan anahtar
    title: str
    description: str
    icon: str
    namespace: str  # URL ad alanı
    landing: str  # modülün giriş sayfası (argümansız URL adı)
    entry: str  # bir programın modüldeki ilk sayfası (URL adı, argüman: program pk)
    nav_groups: list = field(default_factory=list)  # sol menü (navigation.NAV_GROUPS biçiminde)
    # Modülün kendi okul URL'leri: URL adı → (GET yetkisi, POST yetkisi); "pk" argümanı programdır.
    # Tabloda olmayan URL yalnızca merkez yöneticiye açılır (access.py'deki güvenli varsayılan).
    routes: dict = field(default_factory=dict)
    open_routes: set = field(default_factory=set)  # giriş yapmış herkese açık (ör. modülün giriş sayfası)
    labels: dict = field(default_factory=dict)  # işlem günlüğü: URL adı → "Sınav dönemi ekledi"
    order: int = 100

    def landing_url(self):
        return reverse(self.landing)

    def entry_url(self, school):
        return reverse(self.entry, args=[school.pk])


_registry = {}


def register(module):
    _registry[module.key] = module


def all_modules():
    return sorted(_registry.values(), key=lambda m: (m.order, m.title))


def get(key):
    return _registry.get(key)


def by_namespace(namespace):
    return next((m for m in _registry.values() if m.namespace == namespace), None)


def keys():
    return [m.key for m in all_modules()]


def choices():
    return [(m.key, m.title) for m in all_modules()]


# --- erişim ---------------------------------------------------------------------------------------

def allowed_keys(membership):
    """Üyeliğin açabildiği modüller (boş liste = tümü)."""
    chosen = [k for k in (membership.modules or []) if k in _registry]
    return set(chosen) if chosen else set(keys())


def user_modules(user, institution_id=None):
    """Kullanıcının açabildiği modüller (kurum verilirse o kurumda, verilmezse herhangi bir kurumda)."""
    if not user.is_authenticated:
        return []
    if user.is_superuser:
        return all_modules()
    memberships = user.memberships.all()
    if institution_id is not None:
        memberships = memberships.filter(institution_id=institution_id)
    allowed = set()
    for m in memberships:
        allowed |= allowed_keys(m)
    return [m for m in all_modules() if m.key in allowed]


def can_use(user, institution_id, key):
    return any(m.key == key for m in user_modules(user, institution_id))


def schools_for(user, key):
    """Kullanıcının bu modülde açabildiği programlar."""
    from .access import visible_schools

    schools = visible_schools(user)
    if user.is_superuser:
        return schools
    institutions = [m.institution_id for m in user.memberships.all() if key in allowed_keys(m)]
    return schools.filter(institution_id__in=institutions)


# --- açık modül -----------------------------------------------------------------------------------

SESSION_KEY = "modul"


def current(request):
    """Açık sayfanın modülü. Ortak veri sayfalarında en son girilen modül (oturumda saklanır)."""
    from . import access

    match = getattr(request, "resolver_match", None)
    if match is None:
        return None
    module = by_namespace(match.namespace)
    if module is not None and module.key != "ders":
        return module
    if match.namespace == "timetable" and match.url_name in access.SHARED_ROUTES:
        last = get(request.session.get(SESSION_KEY, "")) if hasattr(request, "session") else None
        if last is not None:
            return last
    return get("ders") if match.namespace == "timetable" else module


def remember(request, module):
    """Modüle ait (ortak olmayan) bir sayfa açılınca oturuma yazılır; ortak veri sayfaları o menüyle görünür."""
    if module is not None and hasattr(request, "session") and request.session.get(SESSION_KEY) != module.key:
        request.session[SESSION_KEY] = module.key
