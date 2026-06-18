from django.core.management.base import BaseCommand
import os
from django.conf import settings
from load_cdf.models import *
import tempfile
import zipfile
import shutil
from .evaluate_extras import command_logger, UploadRequired

class Command(UploadRequired, BaseCommand):

    help = "#2 step in evaluation stage of the dataset upload.\n\
            Command unzips CDF files into temporary directory, checks to find existing directory tree,\
            checks for filename collisions.\n\
            IF --no-mv flag IS SET NO FILESYSTEM WORK IS PERFORMED. Use only when you know correct files are in the correct place\
             - save data command will not work unless the files are in the specified place. CDFFileStored objects are still saved in the database.\n\
            Has counterpart undo_012.py that cleans up the directory tree from this dataset."

    def add_arguments(self, parser):
        parser.add_argument("upload_tag", nargs=1, type=str)
        parser.add_argument("dataset_tag", nargs=1, type=str)
        parser.add_argument("--no-mv", action="store_true", help="do not actually transfer the files (used for testing purposes)")

    @command_logger
    def handle(self, *args, **options):
       
        upload = super().handle(**options)
        no_mv = options['no_mv']        

        dataset_dir_path = upload.dataset.directory

        # Create a temporary directory to extract the zip
        with tempfile.TemporaryDirectory() as temp_dir:
            # Extract the zip file
            make_log_entry(f"extracting files in temporary directory {temp_dir}", upload=upload)
            with zipfile.ZipFile(upload.zip_path, 'r') as upzip:
                upzip.extractall(temp_dir)

            # Get all CDF files from the extracted directory
            extracted_files = os.listdir(temp_dir)
            make_log_entry(f"Extracted {len(extracted_files)} files", upload=upload)

            files_to_register = extracted_files
            new_files = extracted_files
            replaced_files = []

            if no_mv:
                make_log_entry(f"FLAG --no-mv SET, NO SEARCH OF THE FILESYSTEM IS DONE!", upload=upload)
                # the data_tree_created flag is SET TRUE NONETHELESS
                upload.update(data_tree_created = True)
            else:   
                if not os.path.exists(dataset_dir_path):
                    os.makedirs(dataset_dir_path)
                    upload.update(data_tree_created = True)
                    make_log_entry(f"Created dataset directory: {dataset_dir_path}", "CREATED", upload=upload)
                    existing_files = set()
                else:
                    make_log_entry(f"Dataset directory already exists: {dataset_dir_path}, proceeding to detect file collisions", "FOUND_EXISTING", upload=upload)
                    existing_files = set(os.listdir(dataset_dir_path))
                
                replaced_files = [f for f in extracted_files if f in existing_files]
                new_files = [f for f in extracted_files if f not in existing_files]

                if replaced_files:
                        collision_logs_txt = os.path.join(settings.COLLISIONS_LOG_DIR, f"{upload.dataset.tag}_{upload.u_tag}_collisions.txt")
                        with open(collision_logs_txt, 'w+') as f:
                            f.write("\n".join(replaced_files))
                            make_log_entry(
                                f"{len(replaced_files)} collisions found for dataset {upload.dataset.tag}. "
                                f"These files will be replaced with newer versions. "
                                f"Collisions saved in {collision_logs_txt}",
                                "INFO",
                                upload=upload
                            )
                else:
                    make_log_entry(f"No collisions found for dataset {upload.dataset.tag}.", "SUCCESS", upload=upload)

            if no_mv:
                make_log_entry(f"FLAG --no-mv SET, NO ACTUAL COPY OF THE FILES IS DONE!", upload=upload)
            else:
                if files_to_register:
                    make_log_entry(
                        f"Copying {len(new_files)} new files and replacing {len(replaced_files)} existing files...", upload=upload)

                    for cdf_filename in files_to_register:
                        src = os.path.join(temp_dir, cdf_filename)
                        dst = os.path.join(dataset_dir_path, cdf_filename)
                        shutil.copy2(src, dst)

                    make_log_entry(f"Saved/replaced {len(files_to_register)} files in {dataset_dir_path}", "SUCCESS", upload=upload)
                else:
                    make_log_entry("No files found in archive.", "INFO", upload=upload)

            cdf_stored_instances = [CDFFileStored(
                full_path=os.path.join(dataset_dir_path, cdf_filename),
                upload=upload
            ) for cdf_filename in files_to_register]

            if cdf_stored_instances:
                CDFFileStored.objects.bulk_create(cdf_stored_instances)
                make_log_entry(f"Saved {len(cdf_stored_instances)} instances of CDFFileStored", "CREATED", upload=upload)
            else:
                make_log_entry(f"No CDFFileStored instances were created.", "INFO", upload=upload)
