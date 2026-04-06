import random
import json
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import SurahProgress
from .quran_db import get_chapters, get_verses, get_verse_by_index, get_distractors
from .db_config import VERSE_INDEX, VERSE_TEXT_AR, VERSE_NUMBER


# ── Auth ──────────────────────────────────────────────────────────────────────

def register_view(request):
    form = UserCreationForm(request.POST or None)
    if form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("mushaf")
    return render(request, "quiz/auth.html", {"form": form, "mode": "register"})


def login_view(request):
    form = AuthenticationForm(data=request.POST or None)
    if form.is_valid():
        login(request, form.get_user())
        return redirect("mushaf")
    return render(request, "quiz/auth.html", {"form": form, "mode": "login"})


def logout_view(request):
    logout(request)
    return redirect("login")


# ── Mushaf ────────────────────────────────────────────────────────────────────

@login_required
def mushaf_view(request):
    chapters = get_chapters()
    surah_number = int(request.GET.get("surah", 1))
    verses = get_verses(surah_number)

    progress, _ = SurahProgress.objects.get_or_create(
        user=request.user, surah_number=surah_number
    )

    return render(request, "quiz/mushaf.html", {
        "chapters": chapters,
        "verses": verses,
        "surah_number": surah_number,
        "unlocked_up_to": progress.unlocked_up_to,
    })


# ── Quiz API ──────────────────────────────────────────────────────────────────

@login_required
def quiz_question(request):
    surah_number = int(request.GET.get("surah", 1))
    verses = get_verses(surah_number)

    progress, _ = SurahProgress.objects.get_or_create(
        user=request.user, surah_number=surah_number
    )

    locked = [v for v in verses if v[VERSE_INDEX] > progress.unlocked_up_to]
    if not locked:
        return JsonResponse({"done": True})

    correct = locked[0]
    distractors = get_distractors(correct[VERSE_INDEX], n=3)
    options = [{"index": correct[VERSE_INDEX], "text": correct[VERSE_TEXT_AR]}]
    for d in distractors:
        options.append({"index": d[VERSE_INDEX], "text": d[VERSE_TEXT_AR]})
    random.shuffle(options)

    return JsonResponse({
        "done": False,
        "correct_index": correct[VERSE_INDEX],
        "verse_number": correct[VERSE_NUMBER],
        "options": options,
    })


@login_required
@require_POST
def quiz_answer(request):
    data = json.loads(request.body)
    surah_number = int(data.get("surah", 1))
    chosen_index = int(data.get("chosen_index"))
    correct_index = int(data.get("correct_index"))

    correct = chosen_index == correct_index
    if correct:
        progress, _ = SurahProgress.objects.get_or_create(
            user=request.user, surah_number=surah_number
        )
        if correct_index > progress.unlocked_up_to:
            progress.unlocked_up_to = correct_index
            progress.save()

    return JsonResponse({"correct": correct})


# ── Progress ──────────────────────────────────────────────────────────────────

@login_required
def progress_view(request):
    chapters = get_chapters()
    progress_map = {
        p.surah_number: p.unlocked_up_to
        for p in SurahProgress.objects.filter(user=request.user)
    }

    rows = []
    for ch in chapters:
        num = ch["chapter_number"]
        verses = get_verses(num)
        total = len(verses)
        unlocked = sum(1 for v in verses if v[VERSE_INDEX] <= progress_map.get(num, 0))
        pct = round(unlocked / total * 100) if total else 0
        rows.append({
            "number": num,
            "name": ch["chapter_name"],
            "unlocked": unlocked,
            "total": total,
            "pct": pct,
        })

    return render(request, "quiz/progress.html", {"rows": rows})


@login_required
@require_POST
def reset_progress(request):
    data = json.loads(request.body)
    surah_number = data.get("surah")
    qs = SurahProgress.objects.filter(user=request.user)
    if surah_number:
        qs = qs.filter(surah_number=surah_number)
    qs.update(unlocked_up_to=0)
    return JsonResponse({"ok": True})
