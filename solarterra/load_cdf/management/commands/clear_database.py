import os

from django.conf import settings
from django.core import management
from django.core.management.base import BaseCommand

from load_cdf.models import DataType, Dataset, LogEntry, Upload, make_log_entry


class Command(BaseCommand):
    help = (
        "Clear uploaded dataset data and generated data classes, then run "
        "makemigrations/migrate for data_cdf."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-datatypes",
            action="store_true",
            help="Keep DataType records instead of deleting them.",
        )

    def handle(self, *args, **options):
        keep_datatypes = options["keep_datatypes"]
        model_dir = settings.MODEL_DIR_PATH

        make_log_entry(f"Starting {str(self)}")
        self.stdout.write("Clearing uploaded data and generated classes...")

        # Remove upload-linked logs first to avoid stale references in summaries.
        log_count = LogEntry.objects.count()
        LogEntry.objects.all().delete()

        upload_count = Upload.objects.count()
        Upload.objects.all().delete()

        dataset_count = Dataset.objects.count()
        Dataset.objects.all().delete()

        datatype_count = 0
        if not keep_datatypes:
            datatype_count = DataType.objects.count()
            DataType.objects.all().delete()

        deleted_files = []
        if os.path.isdir(model_dir):
            for filename in sorted(os.listdir(model_dir)):
                if not filename.endswith(".py") or filename == "__init__.py":
                    continue
                file_path = os.path.join(model_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    deleted_files.append(filename)

        make_log_entry(
            "clear_database: "
            f"deleted logs={log_count}, uploads={upload_count}, datasets={dataset_count}, "
            f"datatypes={datatype_count if not keep_datatypes else 'kept'}, "
            f"model_files={len(deleted_files)}"
        )

        self.stdout.write("Running data_cdf migrations...")
        management.call_command("makemigrations", "data_cdf", "--skip-checks")
        management.call_command("migrate", "data_cdf", "--skip-checks")

        summary = (
            "Clear complete. "
            f"Deleted logs: {log_count}, uploads: {upload_count}, datasets: {dataset_count}, "
            f"model files: {len(deleted_files)}"
        )
        if keep_datatypes:
            summary += ", datatypes: kept"
        else:
            summary += f", datatypes: {datatype_count}"

        self.stdout.write(self.style.SUCCESS(summary))
