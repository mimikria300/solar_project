from django.core.management.base import BaseCommand
from django.core import management 
from .evaluate_extras import UploadRequired


"""
This command combines undo_01n counterparts of those evaluate steps that do changes in the database.
"""

class Command(UploadRequired, BaseCommand):

    help = ""
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument("upload_tag", nargs=1, type=str)
        parser.add_argument("dataset_tag", nargs=1, type=str)

    def handle(self, *args, **options):
        
        upload = super().handle(**options)

        management.call_command("undo_016", upload.u_tag, upload.dataset.tag)
        management.call_command("undo_013", upload.u_tag, upload.dataset.tag)
        management.call_command("undo_012", upload.u_tag, upload.dataset.tag)
        #management.call_command("undo_012", upload.u_tag, upload.dataset.tag, '--no-rm')
        management.call_command("undo_011", upload.u_tag, upload.dataset.tag)


