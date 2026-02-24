from django.db import models
import uuid
import datetime
from solarterra.abstract_models import GetManager
from django.apps import apps
from django.conf import settings
from solarterra.utils import NOW
import os
import numpy as np
from django.core import management


#------ float32 tryout------------#

# POSTGRES ONLY IMPLEMENTATION
class Float32Field(models.Field):

    def db_type(self, connection):
        return "real"


class Upload(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    zip_path = models.TextField()
    match_file_path = models.TextField()

    #  goes after the dataset tag in zipname (for WIND_WIND_OR_PRE_v01_u123 it would be 123)
    u_tag = models.CharField(max_length=200)

    created = models.DateTimeField(auto_now_add=True)

    dataset = models.ForeignKey(
        "Dataset", on_delete=models.CASCADE, related_name="uploads", blank=True, null=True)

    # progress flags
    # 1 step
    dataset_created = models.BooleanField(default=False)
    # 2 step
    data_tree_created = models.BooleanField(default=False)
    # 3 step
    dataset_attributes_created = models.BooleanField(default=False)
    # same step, no separate flag for variable attributes, as they are Variable instance dependent
    variables_created = models.BooleanField(default=False)
    # 4 step
    matchfile_global_applied = models.BooleanField(default=False)
    # 5 step
    matchfile_vars_applied = models.BooleanField(default=False)
    # 6 step
    dynamic_model_created = models.BooleanField(default=False)
    # 7 step should is checked with a method instead
    
    objects = GetManager()

    # for saving instances before bulk inserts during evaluate
    def __init__(self, *args, **kwargs):

        super(Upload, self).__init__(*args, **kwargs)
        # dataset_attribute_list
        self.da_list = []
        # variable list
        self.var_list = []
        # variable attribute list
        self.var_attr_list = []


    class Meta:
        unique_together = ['u_tag', 'dataset']

    def __str__(self):
        return f"{self.u_tag}_{self.dataset.tag}"

    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.save()


    def terminate(self, terminal=True):
        # launch management undo command 
        management.call_command("undo", self.u_tag, self.dataset.tag)
        if terminal:
            exit(1)

    def files_found(self):
        return self.cdf_files.count()

    def files_loaded(self):
        return self.cdf_files.filter(loaded=True).count()
    
    # 7th step checked
    def data_model_file_exists(self):
        if hasattr(self.dataset, 'dynamic') and os.path.exists(self.dataset.dynamic.model_file_path):
            return True
        return False

    def ordered_logs(self):
        return self.logs.order_by('-timestamp')



class CDFFileStored(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # the name of the file
    full_path = models.CharField(max_length=300)

    # the upload it belongs to
    upload = models.ForeignKey(
        "Upload", on_delete=models.CASCADE, related_name="cdf_files")

    loaded = models.BooleanField(default=False)
    saved_rows = models.IntegerField(default=0)

    objects = GetManager()

    def __str__(self):
        return self.full_path
    
    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.save()



# ------------datasets---------------------#
'''
    Dataset is a collection of CDF files that share the same 
    match file. It is identified by a DATASET_TAG
    which is also the full path to the directory where the files are stored.
'''

class DatasetManager(GetManager):

    def have_data(self):
        ids = []
        for ds in self.all():
            
            if not hasattr(ds, 'dynamic'):
                continue
            
            data_model = ds.dynamic.resolve_class()
            
            if data_model is None:
                continue
            
            if data_model.objects.exists():
                ids.append(ds.id)

        return self.filter(id__in=ids)


class Dataset(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # the tag is the name of the directory where the files are stored + the name of the match file
    # e.g. WIND_WIND_OR_PRE_v01
    tag = models.CharField(max_length=100, unique=True)
    # should be required
    directory = models.TextField()
    # global attributes from match file - tag parts
    mission = models.CharField(max_length=100)
    source_name = models.CharField(max_length=100)
    data_type = models.CharField(max_length=100)
    instrument = models.CharField(max_length=100)
    dataset_version = models.CharField(max_length=100)

    # global attributes from match file - dataset description
    text_description = models.TextField(blank=True, null=True)
    logical_source = models.CharField(max_length=200, blank=True, null=True)
    logical_description = models.TextField(blank=True, null=True)
    pi_name = models.CharField(max_length=200, blank=True, null=True)
    pi_affiliation = models.CharField(max_length=200, blank=True, null=True)

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    objects = DatasetManager()

    def __str__(self):
        return self.tag
    
    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.save()
    
    def plottable_variables(self):
        return self.variables.filter(var_logic_type="data", display_type="time_series").order_by('depend_0', 'name')
    
    def is_migrated(self):
        return self.dynamic.resolve_class() is not None

    def has_data(self):
        if self.is_migrated():
            data_model = self.dynamic.resolve_class()
            return data_model.objects.exists()
    
    def files_found(self):
        file_count = 0
        for upload  in self.uploads.all():
            file_count += upload.files_found()
        return file_count
    
    def files_loaded(self):
        file_count = 0
        for upload  in self.uploads.all():
            file_count += upload.files_loaded()
        return file_count
    

    def data_variables(self):
        return self.variables.filter(var_logic_type="data").order_by('name')
    
    def support_variables(self):
        return self.variables.filter(var_logic_type="support_data").order_by('name')
    
    def meta_variables(self):
        return self.variables.filter(var_logic_type="meta_data").order_by('name')





# in case of multiple values create multiple instances with the same title
# will there be considerable overhead on save if unique together for title and value is added?
class DatasetAttribute(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(max_length=100)
    value = models.TextField(blank=True, null=True)
    dataset = models.ForeignKey(
        "Dataset", on_delete=models.CASCADE, related_name="attributes", blank=True, null=True)

    linked_standard_field = models.CharField(
        max_length=100, blank=True, null=True)  # name of the field in Dataset model

   
    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.save()

    def is_standard(self):
        return self.linked_standard_field is not None

    def __str__(self):
        return self.title

# ------------demarcation to vars---------------------#
class VariableManager(GetManager):

    # same condition as in Dataset.plottable_variables(), make dataset relation manager on variable the same as this one
    def plottable(self):
        datasets = Dataset.objects.have_data()
        return self.filter(dataset__in=datasets, var_logic_type="data", display_type="time_series").order_by('dataset__tag', 'name')

    def form_choices(self):
        return [(var.id, var.name) for var in self.plottable()]


'''
    Variable is a single variable in dataset CDF files.
'''
class Variable(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=100)

    # -------MFLBL fields--------

    # original cdf datatype, before conversion to Django

    datatype = models.CharField(max_length=200, blank=True, null=True)

    dims = models.PositiveSmallIntegerField(blank=True, null=True)
    dim_sizes = models.PositiveSmallIntegerField(blank=True, null=True)
    
    is_displayed = models.BooleanField(blank=True, null=True, default=False)

    # this one for future use, not used now
    data_category = models.CharField(max_length=200, blank=True, null=True)

    # -----MF fields------

    catdesc = models.CharField(max_length=200, blank=True, null=True)
    var_notes = models.TextField(blank=True, null=True)
    depend_0 = models.CharField(max_length=200, blank=True, null=True)
    display_type = models.CharField(max_length=200, blank=True, null=True)
    scaletyp = models.CharField(max_length=200, blank=True, null=True)
    # data, meta_data or support_data 
    var_logic_type = models.CharField(max_length=200, blank=True, null=True)
    # this is always a list of strings (often contains a single string), saved as-is from the match file
    fillval = models.CharField(max_length=50, blank=True, null=True)
    # all JSON fields are expected to contain lists of strings (lists of lists for spectrogramms)
    output_format = models.JSONField(blank=True, null=True)
    lablaxis = models.JSONField(blank=True, null=True)
    units = models.JSONField(blank=True, null=True)
    validmin = models.JSONField(blank=True, null=True)
    validmax = models.JSONField(blank=True, null=True)
    scalemin = models.JSONField(blank=True, null=True)
    scalemax = models.JSONField(blank=True, null=True)

    dataset = models.ForeignKey(
        "Dataset", on_delete=models.CASCADE, related_name="variables")


    objects = VariableManager()


    def __str__(self):
        return self.name

    def get_depend_field(self):
        if self.depend_0 is not None:
            depend_var = self.dataset.variables.get(name=self.depend_0)
            if depend_var is not None and depend_var.dynamic.count() == 1:
                return depend_var.dynamic.first()

    def get_numpy_data_type(self):
        field_instance = self.dynamic.first()
        if field_instance is not None:
            if field_instance.data_type_instance is not None:
                return field_instance.data_type_instance.numpy_type

    def get_list_of_fields(self):
        return list(self.dynamic.order_by('multipart_index').values_list('field_name', flat=True))
    
    def ordered_attributes(self):
        return self.attributes.order_by('title')

    def get_axis_label(self, index=None):
        label = self.lablaxis[index] if index is not None else self.lablaxis
        if self.units is not None:
            if index is not None and not isinstance(self.units, str):
                label += f", {self.units[index]}"    
            else:
                label += f", {self.units}"

        return label


class VariableAttribute(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(max_length=100)
    value = models.TextField(blank=True, null=True)
    data_type = models.CharField(max_length=100, blank=True, null=True)

    variable = models.ForeignKey(
        "Variable", on_delete=models.CASCADE, related_name="attributes")
    linked_standard_field = models.CharField(
        max_length=100, blank=True, null=True)  # name of the field in Dataset model


    objects = GetManager()
    
    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.save()

    def is_standard(self):
        return self.linked_standard_field is not None

    def __str__(self):
        return self.title


# ------------demarcation to dynamic models---------------------#


class DynamicModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # string reference to existing MODEL
    model_name = models.CharField(max_length=100)

    # actual Dataset it is made for
    dataset_instance = models.OneToOneField(
        "Dataset", on_delete=models.CASCADE, related_name="dynamic", blank=True, null=True)

    model_file_path = models.TextField()

    objects = GetManager()

    # for saving instances before bulk inserts during evaluate
    def __init__(self, *args, **kwargs):

        super(DynamicModel, self).__init__(*args, **kwargs)
        # dynamic_field_list
        self.df_list = []


    def __str__(self):
        return self.model_name

    def resolve_class(self):
        try:
            model_class = apps.get_model(
                app_label='data_cdf', model_name=self.model_name)
            return model_class
        except:
            return None


    # def data_variables(self):
    #     return self.dataset_instance.variables.filter(var_logic_type='data')



class DynamicField(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # string reference to existing MODEL FIELD
    field_name = models.CharField(max_length=100)

    # is it made from multiple vars?
    multipart = models.BooleanField(default=False)

    multipart_index = models.PositiveSmallIntegerField(blank=True, null=True)

    # actual variable instance it represents
    variable_instance = models.ForeignKey("Variable", on_delete=models.CASCADE, related_name="dynamic")
    
    # field of which model is it
    dynamic_model = models.ForeignKey("DynamicModel", on_delete=models.CASCADE, related_name="fields")

    data_type_instance = models.ForeignKey('DataType', related_name="fields", on_delete=models.SET_NULL, blank=True, null=True)

    objects = GetManager()

    
    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.save()


    def __str__(self):
        return self.field_name

    # def get_time_field(self):
    #     time_var = self.variable_instance.dataset.variables.filter(
    #         name__icontains='epoch').first()
    #     if time_var is not None and self.variable_instance.depend_0.lower() == 'epoch':
    #         return time_var.dynamic.first()
    #     else:
    #         return None

    # def get_time_field_name(self):
    #     time_field = self.get_time_field()
    #     if time_field is not None:
    #         return time_field.field_name
    #     else:
    #         return None


class DataType(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # label from CDF file, set to each variable
    cdf_file_label = models.CharField(max_length=50, unique=True)
    # default null value
    fillval = models.CharField(blank=True, null=True)

    # for template construction
    # django field closest to
    django_field = models.CharField(max_length=200)
    
    numpy_type = models.CharField(max_length=50, blank=True, null=True)

    
    def __str__(self):
        return self.cdf_file_label
    
    # takes a value in some numpy type, because python cdf library unpacks all data to numpy
    @classmethod
    def proper_type(cls, value_str, proper_value):
        # separate datetime case
        if isinstance(proper_value, datetime.datetime):
            template = "%d-%b-%Y %H:%M:%S.%f"
            try:
                dat = datetime.datetime.strptime(value_str, template)
                return dat
            except Exception as e:
                make_log_entry(f"Could not convert value str '{value_str}' to datetime using template '{template}'")
                return None

        else:
            try:
                return proper_value.__class__(value_str)

            except Exception as e:
                make_log_entry(f"Could not convert value string '{value_str}' to '{proper_value.__class__}': {e}", "ERROR")
                return None


    # used for testing 
    def vc(self, arr, value):
        print(f"{value}: {len(arr[arr==value])} / {arr.shape}")


    def is_epoch(self):
        return 'EPOCH' in self.cdf_file_label


class LogEntry(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    timestamp = models.DateTimeField(auto_now_add=True)
    upload = models.ForeignKey(
        "Upload", on_delete=models.CASCADE, related_name="logs", blank=True, null=True)
    code = models.CharField(max_length=15, null=True, blank=True)
    message = models.TextField()

    objects = GetManager()

    def __str__(self):
        return f"{self.timestamp} {self.code}"


def make_log_entry(message, code=None, upload=None, color=None):

    def to_file(code, message):
        s = f"{NOW()}   "
        if code:
            s += f"[{code}]   "
        s += message
        return s + "\n"

    def to_db(upload, code, message):
        log_entry = LogEntry(
                timestamp=NOW(),
                upload=upload,
                code=code,
                message=message)
        log_entry.save()

    with open(settings.LOG_FILE, mode="a") as f:
        f.write(to_file(code, message))

    if upload is not None:
        to_db(upload, code, message)

