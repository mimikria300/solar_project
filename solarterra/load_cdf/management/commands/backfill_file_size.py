import os
from django.core.management.base import BaseCommand
from load_cdf.models import CDFFileStored


class Command(BaseCommand):

    help = "One-off: fills CDFFileStored.file_size for files registered before the field existed (new uploads set it in 012)."

    def handle(self, *args, **options):
        filled = missing = 0
        for cdf_file in CDFFileStored.objects.filter(file_size__isnull=True):
            if os.path.exists(cdf_file.full_path):
                cdf_file.update(file_size=os.path.getsize(cdf_file.full_path))
                filled += 1
            else:
                missing += 1
        print(f"file_size filled for {filled} files, {missing} not found on disk (left empty)")
