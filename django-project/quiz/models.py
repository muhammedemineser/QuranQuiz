from django.db import models
from django.contrib.auth.models import User


class SurahProgress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="progress")
    surah_number = models.PositiveSmallIntegerField()
    unlocked_up_to = models.PositiveIntegerField(default=0)  # verse_index

    class Meta:
        unique_together = ("user", "surah_number")

    def __str__(self):
        return f"{self.user.username} – Surah {self.surah_number}: {self.unlocked_up_to}"
