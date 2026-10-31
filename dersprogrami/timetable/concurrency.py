"""Eşzamanlı düzenleme koruması: kim neyi düzenliyor (varlık), program düzenleyicisinde iyimser çakışma
denetimi ve kayıt formlarında "siz düzenlerken değişti" uyarısı.

Uygulama tek süreçte (runserver/waitress) ama birden çok iş parçacığıyla sunulur; durum bellekte değil
veritabanında tutulur (EditPresence, Timetable.revision / Timetable.changes).

Program düzenleyicisi:
- Kartları değiştiren her işlem (editing.record ve geri al / yinele) programın sürüm sayacını artırır ve kısa
  değişiklik kaydına kimin, hangi sekmeden, hangi kartları değiştirdiğini yazar.
- İstemci son gördüğü sürümü X-Timetable-Revision başlığıyla gönderir. Arada başkası değiştirdiyse kart
  işlemi yalnızca o kartlara dokunmuyorsa uygulanır; aksi halde 409 ve "stale" yanıtı döner. Başlık yoksa
  (eski istemci, testler) eskisi gibi çalışır; tek kullanıcıda ek maliyet tek küçük sorgudur.
"""

import contextvars
import hashlib
import json
import re
from datetime import timedelta
from functools import wraps

from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from .models import Card, EditPresence, School, Timetable

REVISION_HEADER = "X-Timetable-Revision"
TAB_HEADER = "X-Editor-Tab"
CHANGE_LIMIT = 40  # programda saklanan son değişiklik sayısı
MAX_CARDS = 400  # bundan çok kart değiştiren işlem "tümü" sayılır
PRESENCE_WINDOW = timedelta(seconds=90)  # bu süredir nabız gelmeyen düzenleyici gösterilmez
PRESENCE_EXPIRE = timedelta(minutes=10)  # bundan eski satırlar silinir

_request = contextvars.ContextVar("concurrency_request", default=None)


def bind_request(request):
    """SchoolAccessMiddleware her isteğin başında çağırır: değişikliği kimin yaptığı buradan okunur."""
    return _request.set(request)


def release(token):
    _request.reset(token)


# --- adlar ---------------------------------------------------------------------------------------

def _upper_tr(ch):
    return {"i": "İ", "ı": "I"}.get(ch, ch.upper())


def short_name(user):
    """"Ahmet Yılmaz" → "Ahmet Y."; ad yoksa kullanıcı adı."""
    first, last = (user.first_name or "").strip(), (user.last_name or "").strip()
    if first and last:
        return f"{first} {_upper_tr(last[0])}."
    return first or last or user.get_username()


BACK_VOWELS, FRONT_VOWELS = "aıou", "eiöü"


def _de(name):
    """Bağlaç "de/da" ünlü uyumu: "Ahmet Y. de", "Murat da", "Ayşe K. de" (harf adı: "ka" değil "ke")."""
    word = (name.split() or [""])[-1].replace("İ", "i").replace("I", "ı").lower()
    if len(word) <= 2 and word.endswith("."):  # baş harf: harf adı okunur (a, ı, o, u → da; diğerleri "-e")
        return "da" if word[:1] in BACK_VOWELS else "de"
    for ch in reversed(word):
        if ch in BACK_VOWELS:
            return "da"
        if ch in FRONT_VOWELS:
            return "de"
    return "de"


def presence_text(names, what):
    """["Ahmet Y."] → "Ahmet Y. de bu programı düzenliyor"."""
    if not names:
        return ""
    if len(names) == 1:
        return f"{names[0]} {_de(names[0])} bu {what} düzenliyor"
    if len(names) == 2:
        return f"{names[0]} ve {names[1]} {_de(names[1])} bu {what} düzenliyor"
    return f"{names[0]}, {names[1]} ve {len(names) - 2} kişi daha bu {what} düzenliyor"


def _actor():
    request = _request.get()
    if request is None:
        return None, "", ""
    tab = (request.headers.get(TAB_HEADER) or "")[:40]
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None, "", tab
    return user.pk, short_name(user), tab


# --- program sürümü ------------------------------------------------------------------------------

def bump(timetable_id, card_ids, label=""):
    """Kart değişikliğinden sonra (ya da önce, aynı istekte) sürümü artırır; yeni sürümü döndürür."""
    user_id, name, tab = _actor()
    ids = sorted({int(i) for i in card_ids})
    entry = {"user_id": user_id, "user": name, "tab": tab, "label": label[:120]}
    if len(ids) > MAX_CARDS:
        entry["all"] = True
    else:
        entry["cards"] = ids
    with transaction.atomic():
        # Önce artır: satır (SQLite'ta veritabanı) kilitlenir, kaydı okuyup yazmak sıraya girer.
        Timetable.objects.filter(pk=timetable_id).update(revision=F("revision") + 1)
        row = Timetable.objects.filter(pk=timetable_id).values_list("revision", "changes").first()
        if row is None:
            return None
        revision, changes = row
        entry["rev"] = revision
        Timetable.objects.filter(pk=timetable_id).update(changes=(list(changes or []) + [entry])[-CHANGE_LIMIT:])
    return revision


def current_revision(timetable_id):
    return Timetable.objects.filter(pk=timetable_id).values_list("revision", flat=True).first() or 0


def since(timetable_id, seen, tab=""):
    """İstemcinin gördüğü sürümden sonraki değişiklikler.

    Dönüş: {"revision", "fresh", "changed": değişen kart kimlikleri (bilinmiyorsa None), "foreign": başka
    kullanıcı/sekmenin değişiklik kayıtları}. Yalnızca aynı sekmenin (yanıtı yolda olan) işlemleri varsa taze sayılır."""
    row = Timetable.objects.filter(pk=timetable_id).values_list("revision", "changes").first()
    revision, changes = row if row else (0, [])
    if seen == revision:
        return {"revision": revision, "fresh": True, "changed": set(), "foreign": []}
    newer = [c for c in changes or [] if c.get("rev", 0) > seen]
    complete = seen < revision and len(newer) == revision - seen  # kayıt kırpılmadıysa
    foreign = [c for c in newer if not tab or c.get("tab") != tab]
    if complete and not foreign:
        return {"revision": revision, "fresh": True, "changed": set(), "foreign": []}
    changed = None
    if complete and not any(c.get("all") for c in newer):
        changed = {i for c in newer for i in c.get("cards", ())}
    return {"revision": revision, "fresh": False, "changed": changed, "foreign": foreign}


def stale_message(state, user=None):
    names = []
    self_tab = False
    for c in state["foreign"]:
        if user is not None and c.get("user_id") == user.pk:
            self_tab = True
            continue
        name = c.get("user") or "başka bir kullanıcı"
        if name not in names:
            names.append(name)
    if names:
        who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " ve " + names[-1]
        return f"Bu programı {who} değiştirdi; görünüm yenilendi."
    if self_tab:
        return "Bu program başka bir sekmede değiştirildi; görünüm yenilendi."
    return "Bu program siz düzenlerken değişti; görünüm yenilendi."


def conflict_response(request, state):
    return JsonResponse({
        "ok": False, "stale": True, "message": stale_message(state, request.user), "revision": state["revision"],
        "changes": [{"user": c.get("user") or "", "label": c.get("label", "")} for c in state["foreign"]],
        "cards": sorted(state["changed"] or []),
    }, status=409)


def guard(scope):
    """Düzenleyici uç noktası için iyimser çakışma denetimi. scope="card": pk karttır, arada değişen kartlara
    dokunmayan işlem uygulanır (taşımada hedefteki kartlar da denetlenir: request.protect_cards); scope="program":
    pk programdır, arada herhangi bir değişiklik varsa işlem reddedilir (toplu işlem, satır işlemi, geri al)."""
    def decorate(view):
        @wraps(view)
        def wrapper(request, pk, *args, **kwargs):
            raw = request.headers.get(REVISION_HEADER, "")
            if not raw.isdigit():
                return view(request, pk, *args, **kwargs)
            timetable_id = Card.objects.filter(pk=pk).values_list("timetable_id", flat=True).first() if scope == "card" else pk
            if timetable_id is None:
                return view(request, pk, *args, **kwargs)
            state = since(timetable_id, int(raw), request.headers.get(TAB_HEADER, ""))
            if not state["fresh"]:
                if scope != "card" or state["changed"] is None or pk in state["changed"]:
                    return conflict_response(request, state)
                request.protect_cards = state["changed"]
            response = view(request, pk, *args, **kwargs)
            if not response.get("Content-Type", "").startswith("application/json"):
                return response
            try:
                data = json.loads(response.content or b"{}")
            except ValueError:
                return response
            if data.get("stale"):  # taşıma, arada değişen bir kartla çakışıyor
                return conflict_response(request, state)
            data["revision"] = current_revision(timetable_id)
            if not state["fresh"]:
                data["others"] = stale_message(state, request.user)  # istemci tabloyu yeniden yükler
            return JsonResponse(data, status=response.status_code)
        return wrapper
    return decorate


# --- kim düzenliyor ------------------------------------------------------------------------------

KEY_RE = re.compile(r"^(program:\d+|kayit:[a-z0-9-]{1,40}:\d+)$")
WHAT = {"program": "programı", "kayit": "kaydı"}


def editors(school_id, key, user):
    """Son 90 sn'de nabız yazan diğer düzenleyicilerin kısa adları (kendisi hariç)."""
    rows = (EditPresence.objects.filter(school_id=school_id, key=key, editing=True,
                                        last_seen__gte=timezone.now() - PRESENCE_WINDOW)
            .exclude(user=user).select_related("user").order_by("last_seen"))
    return [short_name(r.user) for r in rows]


def _body(request):
    if request.content_type == "application/json":
        try:
            return json.loads(request.body or b"{}")
        except ValueError:
            return {}
    return request.POST


@require_POST
def api_presence(request, pk):
    """Düzenleyici nabzı: {key, editing, leave, since, tab}. Diğer düzenleyicileri ve (program için) başkasının
    yaptığı değişikliği döndürür. Sayfa kapanırken leave=1 ile (sendBeacon) satır silinir."""
    school = get_object_or_404(School, pk=pk)
    body = _body(request)
    key = str(body.get("key") or "")
    if not KEY_RE.match(key):
        return JsonResponse({"ok": False, "message": "Geçersiz anahtar."}, status=400)
    timetable_id = int(key.split(":")[1]) if key.startswith("program:") else None
    if timetable_id is not None and not Timetable.objects.filter(pk=timetable_id, school=school).exists():
        return JsonResponse({"ok": False, "message": "Program bulunamadı."}, status=404)
    if str(body.get("leave") or "") in ("1", "true", "True"):
        EditPresence.objects.filter(school=school, key=key, user=request.user).delete()
        return JsonResponse({"ok": True})
    now = timezone.now()
    editing = body.get("editing") not in (False, 0, "0", "false", "")
    EditPresence.objects.update_or_create(school=school, key=key, user=request.user,
                                          defaults={"editing": editing, "last_seen": now})
    EditPresence.objects.filter(last_seen__lt=now - PRESENCE_EXPIRE).delete()  # dizinli, ucuz
    names = editors(school.pk, key, request.user)
    data = {"ok": True, "others": names, "text": presence_text(names, WHAT[key.split(":")[0]])}
    seen = str(body.get("since", ""))
    if timetable_id is not None and seen.isdigit():
        state = since(timetable_id, int(seen), str(body.get("tab") or ""))
        data["revision"] = state["revision"]
        if not state["fresh"] and state["foreign"]:
            data["changed"] = stale_message(state, request.user)
    return JsonResponse(data)


# --- kayıt formları ------------------------------------------------------------------------------

STATE_FIELD = "_kayit_durumu"
FORCE_FIELD = "_yine_de"


def normalize(value):
    """Karşılaştırma için alan değerinin metin hali (model → kimlik, çoklu seçim → sıralı liste)."""
    if value is None or value is False:
        return ""
    if value is True:
        return "1"
    if hasattr(value, "pk"):
        return str(value.pk)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    if isinstance(value, (list, tuple, set)) or (hasattr(value, "__iter__") and not isinstance(value, (str, bytes))):
        return json.dumps(sorted(normalize(v) for v in value), ensure_ascii=False)
    return str(value).strip()


def digest(text):
    return hashlib.sha1(str(text).encode()).hexdigest()[:12]


def make_token(values):
    """values: {alan: normalize(değer)} → gizli alana yazılan yüklenme durumu (zaman + alan özetleri)."""
    return json.dumps({"t": timezone.now().isoformat(), "f": {k: digest(v) for k, v in values.items()}},
                      separators=(",", ":"))


def read_token(raw):
    try:
        data = json.loads(raw or "")
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("f"), dict):
        return None
    return {"t": parse_datetime(str(data.get("t") or "")), "f": data["f"]}


def changed_fields(token, values):
    """Yüklendiğinden beri veritabanında değişen alanlar."""
    return [k for k, v in values.items() if k in token["f"] and token["f"][k] != digest(v)]
