# About

This is a Django project to load data from .CDF files to the db using ORM and plot them using plotly python library.

# Installation

1. Set up postgres cluster and create an empty database for solar_project. Use of postgres database is required for the current version of this project.

	https://www.postgresql.org/docs/current/installation.html

2. Create virtual environment for you project and install venv_requirements

```
python -m venv solar_venv
. solar_venv/bin/activate
pip install -r venv_requirements
```

4. Fill in configs/settings.json file with your parameters

```python

# S_K django secret key 
from django.core.management.utils import get_random_secret_key  
get_random_secret_key()

# DB - credentials for you  postgres database connection
# LOADER - absolute paths to the designated directories
# DATA_ROOT - directory that will contain the uploaded data tree
# MATCH_FILE_DIR - directory that will contain matchfiles for the datasets
# UPLOAD_ZIP_DIR - directory that will contain zipped datasets

```

4. Run initial migrations for the load_cdf app, skipping url configuration checks

```
python manage.py makemigrations load_cdf --skip-checks
python manage.py migrate load_cdf --skip-checks
```

5. Start the web-server and check that there are no errors at launch

```
python manage.py runserver <ip-address:port>
```

6. Before starting evaluation and data upload for any dataset, create available DataType instances for future use. This is a one-time action that is done by   launching create_datatype management command.

```shell
python manage.py create_datatype
```
# Project description

Project consists of 2 tightly coupled apps:

- <b>load_cdf</b>  handles the uploads of CDF datasets into the database
- <b>pages</b> handles data processing (validation and aggregation) and plotting

- *<b>data_cdf</b> app is only accessed programmatically (that's where data models are saved) and should not require manual interference, except for migrations*
## load_cdf

Datasets are uploaded one-by-one in 2(.5) steps:

- evaluation
Fills in all the metadata about the dataset that is about to be uploaded

- (migrations)
Creates the sql table for this dataset inside the DB. Run these with --skip-checks option

- data upload
Saves all the data from this dataset into the DB

Steps are performed using django management commands.

#### Evaluation

Each dataset is represented with 2 files:

- <matchfile.json> 
Matchfile contains metadata about the dataset that is collected, adjusted and combined manually in order to standartize completely different datasets prepared by different research groups.

These files have to be stored in the directory you specified in settings.json in LOADER.MATCH_FILE_DIR

- <dataset.zip>
File contains zipped CDF files with the data.

These files have to be stored in the directory you specified in settings.json in LOADER.UPLOAD_ZIP_DIR

Each dataset has unique dataset.tag that consists of 5 parts, separated by \_:
(ex. INTERBALL_IT_K0_ELE_v01)

Project tag ( INTERBALL )
Mission tag ( IT>Interball Tail Probe )
Data_type ( IT>Interball Tail Probe )
Instrument ( ELE>Thermal Electron Data )
Dataset_version ( v01 )

During evaluation dataset files are automatically unpacked and organized in a tree structure inside the directory you specified in settings.json in LOADER.DATA_ROOT. Loader then looks for them there.

To launch evaluation:

```shell
python manage.py evaluate <dataset_zip_file_name> <match_file_name>
```

<b>evaluate.py</b> launches 8 sequential sub-commands, that represent stages of the evaluation. Sub-commands are numbered and can be launched independently for convenience.

<b>The last command  018_create_data_model_template requires immediate migrations (of the data_cdf app) and web-server restart, otherwise the system is left in the unstable state.</b>

When just testing the evaluation process, comment it out in the evaluate.

Each upload is tracked with corresponding Upload instance with a unique u_tag. Upload attempts are logged. Logs can be found in the file, which you specified in settings.json LOG_FILE. Also logs are stored in the database - you can see them on the upload page upload_info/<upload_id>

##### undo.py

For every evaluate sub-command that creates any database instances or does filesystem manipulation, there is a corresponding undo_01n.py command to undo the changes (except for the last one 018_create_data_model_template - the model file has to be deleted manually, and then migrations have to be applied). These commands can be launched one-by-one or in sequence by running undo.py. Parameters for the undo command are different from those of evaluate!

```shell
# IMPORTANT parameters are different from those of evaluate!!!
python manage.py undo <upload.u_tag> <dataset.tag>
```

#### Data upload

```shell
python manage.py save_data <upload.u_tag> <dataset.tag>
```

save_data.py  saves data from files indexed for upload, one-by-one. Evaluation stage and migrations have to be completed to start data upload.

## pages

The app uses python plotly library to plot the data uploaded to the DB.

This app contains views for the following pages:
 
 - data_info
 Shows all the data about evaluated and uploaded datasets, organized by missions
 Also shows information about each variable in the dataset and each upload

- search
Shows form that allows to choose variables and timeframe for plotting, organised by missions and datasets 

- system_data
Shows basic parameters of your project configuration