import os

from django.conf import settings
from django.core import management
from django.core.management.base import BaseCommand

from load_cdf.models import Dataset, make_log_entry
from load_cdf.utils import get_dataset_tag, get_upload_tag


class Command(BaseCommand):
    help = "Bulk upload all datasets from UPLOAD_ZIP_DIR using evaluate + migrations + save_data."

    def add_arguments(self, parser):

        parser.add_argument(
            "--skip-create-datatype",
            action="store_true",
            help="Skip running create_datatype before processing datasets.",
        )

    def handle(self, *args, **options):
        zip_dir = settings.UPLOAD_ZIP_DIR
        match_dir = settings.MATCH_FILE_DIR
        skip_create_datatype = options["skip_create_datatype"]

        zip_filenames = sorted(
            [name for name in os.listdir(zip_dir) if name.lower().endswith(".zip")]
        )

        if not zip_filenames:
            msg = f"No zip files found in {zip_dir}."
            make_log_entry(msg, "WARNING")
            self.stdout.write(self.style.WARNING(msg))
            return

        make_log_entry(f"Starting {str(self)}")
        make_log_entry(f"CURRENT UPLOAD_ZIP_DIR: {zip_dir}")
        make_log_entry(f"CURRENT MATCH_FILE_DIR: {match_dir}")
        self.stdout.write(f"Found {len(zip_filenames)} dataset zip file(s).")

        success_count = 0
        skipped_count = 0
        failed = []

        for zip_filename in zip_filenames:
            dataset_tag = get_dataset_tag(zip_filename)
            upload_tag = get_upload_tag(zip_filename)
            match_filename = f"{dataset_tag}_matchfile.json"
            match_path = os.path.join(match_dir, match_filename)

            self.stdout.write(
                f"\nProcessing dataset '{dataset_tag}' (zip='{zip_filename}', match='{match_filename}')"
            )

            existing_dataset = Dataset.objects.filter(tag=dataset_tag).first()
            if existing_dataset:
                msg = f"Skipping '{dataset_tag}': dataset is already loaded."
                make_log_entry(msg, "WARNING")
                self.stdout.write(self.style.WARNING(msg))
                skipped_count += 1
                continue

            if not os.path.exists(match_path):
                err = f"Match file not found: {match_filename}"
                make_log_entry(err, "ERROR")
                self.stdout.write(self.style.ERROR(err))
                failed.append((dataset_tag, err))
                if stop_on_error:
                    break
                continue

            try:
                management.call_command("evaluate", zip_filename, match_filename)
                management.call_command("makemigrations", "data_cdf", "--skip-checks")
                management.call_command("migrate", "data_cdf", "--skip-checks")
                management.call_command("save_data", upload_tag, dataset_tag)
                success_count += 1
            except Exception as exc:
                err = f"Failed dataset '{dataset_tag}': {exc}"
                make_log_entry(err, "ERROR")
                self.stdout.write(self.style.ERROR(err))
                failed.append((dataset_tag, str(exc)))
                if stop_on_error:
                    break

        total = len(zip_filenames)
        summary = (
            f"Bulk upload finished. Success: {success_count}/{total}. "
            f"Skipped: {skipped_count}. Failed: {len(failed)}."
        )
        make_log_entry(summary)
        self.stdout.write(self.style.SUCCESS(summary))

        if failed:
            self.stdout.write("Failed datasets:")
            for dataset_tag, reason in failed:
                self.stdout.write(f"- {dataset_tag}: {reason}")
