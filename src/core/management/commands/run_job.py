"""Exécute immédiatement une tâche Procrastinate (recette, quickstart).

Exemple : ``manage.py run_job helpdesk.auto_close``
"""

import inspect
import time

from django.core.management.base import BaseCommand, CommandError
from procrastinate.contrib.django import app


class Command(BaseCommand):
    help = "Exécute immédiatement une tâche planifiée, sans passer par le worker."

    def add_arguments(self, parser):
        parser.add_argument("task_name", nargs="?", help="nom de la tâche, ex. helpdesk.auto_close")
        parser.add_argument("--list", action="store_true", help="liste les tâches disponibles")

    def handle(self, *args, task_name=None, list=False, **options):
        tasks = app.tasks
        if list or not task_name:
            for name in sorted(tasks):
                self.stdout.write(name)
            return
        task = tasks.get(task_name)
        if task is None:
            raise CommandError(f"Tâche inconnue : {task_name}. Utilisez --list.")
        params = inspect.signature(task.func).parameters
        result = task.func(int(time.time())) if "timestamp" in params else task.func()
        self.stdout.write(self.style.SUCCESS(f"{task_name} exécutée : {result!r}"))
