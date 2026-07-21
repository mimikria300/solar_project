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
from solarterra.utils import bigint_ts_resolver as it
from solarterra.utils import ts_bigint_resolver as tbr


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
    
    matchfile_version = models.CharField(max_length=100, blank=True)

    is_initial = models.BooleanField(default=True)

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
    nrv_created = models.BooleanField(default=False)
    
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

    time_start = models.BigIntegerField(blank=True, null=True)
    time_end = models.BigIntegerField(blank=True, null=True)

    objects = DatasetManager()

    def __str__(self):
        return self.tag
    
    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.save()
    
    def plottable_variables(self):
        return self.variables.filter(var_logic_type="data", display_type__in=["time_series", "spectrogram"]).order_by('depend_0', 'name')
    
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
        return self.variables.filter(var_logic_type="metadata").order_by('name')
    
    def ignore_variables(self):
        return self.variables.filter(var_logic_type="ignore_data").order_by('name')
    
    def _get_epoch_variable(self):
        return self.variables.filter(name__icontains='epoch').order_by('name').first()

    def _parse_valid_time(self, raw_value):
        if raw_value is None:
            return None

        try:
            value_str = raw_value[0] if isinstance(raw_value, list) else raw_value
            if not value_str:
                return None

            return datetime.datetime.strptime(
                value_str,
                "%d-%b-%Y %H:%M:%S.%f"
            ).replace(tzinfo=datetime.timezone.utc)
        except Exception:
            return None

    def _read_epoch_from_file(self, cdf_path, epoch_var_name, from_start=True):
        from spacepy import pycdf

        cdf_obj = pycdf.CDF(cdf_path)
        try:
            arr = cdf_obj[epoch_var_name][...]

            if arr.ndim > 1 and arr.shape[-1] == 1:
                arr = arr.reshape(-1)
                
            if len(arr) == 0:
                return None

            value = arr[0] if from_start else arr[-1]
            return tbr(value)
        finally:
            cdf_obj.close()

    def rebuild_time_range(self):
        epoch_variable = self._get_epoch_variable()

        if epoch_variable is None:
            self.time_start = None
            self.time_end = None
            self.save(update_fields=['time_start', 'time_end'])
            return

        files_qs = CDFFileStored.objects.filter(
            upload__dataset=self,
            loaded=True
        ).order_by('full_path')

        if not files_qs.exists():
            self.time_start = None
            self.time_end = None
            self.save(update_fields=['time_start', 'time_end'])
            return

        start = None
        for cdf_file in files_qs:
            start = self._read_epoch_from_file(
                cdf_file.full_path,
                epoch_variable.name,
                from_start=True
            )
            if start is not None:
                break

        end = None
        for cdf_file in files_qs.order_by('-full_path'):
            end = self._read_epoch_from_file(
                cdf_file.full_path,
                epoch_variable.name,
                from_start=False
            )
            if end is not None:
                break

        self.time_start = start
        self.time_end = end
        self.save(update_fields=['time_start', 'time_end'])
    
    def get_time_range(self):
        if self.time_start is None or self.time_end is None:
            return (None, None)

        min_time = it(self.time_start)
        max_time = it(self.time_end)

        epoch_variable = self._get_epoch_variable()
        if epoch_variable is None:
            return (min_time, max_time)

        validmin_dt = self._parse_valid_time(epoch_variable.validmin)
        validmax_dt = self._parse_valid_time(epoch_variable.validmax)

        if validmin_dt is not None and min_time < validmin_dt:
            min_time = validmin_dt

        if validmax_dt is not None and max_time > validmax_dt:
            max_time = validmax_dt

        return (min_time, max_time)


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
        return self.filter(dataset__in=datasets, var_logic_type="data", display_type__in=["time_series", "spectrogram"]).order_by('dataset__tag', 'name')

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
    dim_sizes = models.JSONField(blank=True, null=True)
    
    is_displayed = models.BooleanField(blank=True, null=True, default=False)

    # this one for future use, not used now
    data_category = models.CharField(max_length=200, blank=True, null=True)

    # -----MF fields------

    catdesc = models.CharField(max_length=200, blank=True, null=True)
    var_notes = models.TextField(blank=True, null=True)
    depend_0 = models.CharField(max_length=200, blank=True, null=True)
    depend_1 = models.CharField(max_length=200, blank=True, null=True)
    display_type = models.CharField(max_length=200, blank=True, null=True)
    scaletyp = models.CharField(max_length=200, blank=True, null=True)
    # data, meta_data or support_data 
    var_logic_type = models.CharField(max_length=200, blank=True, null=True)
    # this is always a list of strings (often contains a single string), saved as-is from the match file
    fillval = models.CharField(max_length=50, blank=True, null=True)
    # all JSON fields are expected to contain lists of strings (lists of lists for spectrogramms)
    output_format = models.JSONField(blank=True, null=True)
    lablaxis = models.JSONField(blank=True, null=True)
    labl_ptr = models.CharField(max_length=200, blank=True, null=True)
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

    def _pick_axis_value(self, value, index=None):
        if value is None:
            return ""

        if isinstance(value, (list, tuple)):
            if index is not None:
                if 0 <= index < len(value) and value[index] is not None:
                    return str(value[index]).strip()
                return ""

            if len(value) == 1:
                return "" if value[0] is None else str(value[0]).strip()

            return ", ".join(str(item).strip() for item in value if item is not None)

        return str(value).strip()
    
    def _get_axis_labels_source(self):
        if self.lablaxis:
            return self.lablaxis

        if not self.labl_ptr:
            return None

        return self.dataset.nrv_data.filter(
            variable__name=self.labl_ptr
        ).values_list('value', flat=True).first()

    def get_axis_label(self, index=None):
        label = self._pick_axis_value(self._get_axis_labels_source(), index)
        unit = self._pick_axis_value(self.units, index)

        if label and unit:
            return f"{label}, {unit}"

        return label or unit
    
    # NRV = depend_0 is NULL AND depend_1 is NULL AND name != epoch.
    def is_nrv(self):
        if self.depend_0 is not None or self.depend_1 is not None:
            return False
        
        name_lower = self.name.lower()
        if name_lower.startswith('epoch'):
            return False
        
        return True


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


class NRVData(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    field_name = models.CharField(max_length=100)
    value = models.JSONField(blank=True, null=True)

    dataset = models.ForeignKey(
        "Dataset", on_delete=models.CASCADE, related_name="nrv_data")
    variable = models.ForeignKey(
        "Variable", on_delete=models.CASCADE, related_name="nrv_values")
    data_type_instance = models.ForeignKey(
        'DataType', related_name="nrv_fields",
        on_delete=models.SET_NULL, blank=True, null=True)
    
    objects = GetManager()

    def __str__(self):
        return self.field_name

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
    
    def sorted_fields(self):
        fields = list(self.fields.all())
        
        def sort_key(f):
            name = f.field_name
            if 'epoch' in name or 'time' in name:
                return (0, f.field_name)
            return (1, f.field_name)
        
        return sorted(fields, key=sort_key)


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

    # field stores values in ArrayField?
    is_array_field = models.BooleanField(default=False, blank=True)
    array_size = models.PositiveIntegerField(null=True, blank=True)

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

    def get_format_str(self):
        '''
        Can be a single str for dims = 0, always a list for dims = 1. Dims > 1 is not supported yet.
        '''
        var = self.variable_instance
        format_str = None
        if var.output_format is not None:
            if var.dims == 0:
                format_str = var.output_format
            elif var.dims == 1:
                #it can be a single value or a list already, make it a list always
                if isinstance(var.output_format, list):
                    format_str = var.output_format
                else:
                    format_str = [var.output_format] * var.dim_sizes
        return format_str

    def set_format_function(self):
        '''Correct usage for a single record of multipart field: formatted_list = [f(val) for f,val in zip(field.format_function, field_values)]
        Or can be called like field.format_function[0](val_0)'''
        
        format_str = self.get_format_str()
        if isinstance(format_str, list): 
            self.format_function = [self.make_format_function(self.data_type_instance, fs) for fs in format_str]
        else:
            self.format_function = self.make_format_function(self.data_type_instance, format_string)

        return format_function

    @staticmethod
    def make_format_function(type_instance, format_str):
        '''Factory for field-specific formatter functions. X should be passed in proper python type.'''

        if type_instance.is_epoch():
            #nb: the current uploader is ommiting milliseconds completely (it rounds the timestamps to seconds)
            return lambda x: it(x).strftime("%Y-%m-%d %H:%M:%S") + f"-{it(x).microsecond // 1000:03d}" if (x is not None and x is not np.nan) else "NaN"
        elif format_str is not None and "i" in format_str.lower():
            #it is usually for year/day/etc, doesn't really need to be zero-padded; added as a place to add different behavior for int types if needed
            return lambda x: str(int(x)) if (x is not None and x is not np.nan) else "NaN"
        elif format_str is not None and "f" in format_str.lower():
            return lambda x: f"{x:{format_str.lower().strip('f')}f}" if (x is not None and x is not np.nan) else "NaN"
        elif format_str is not None and "e" in format_str.lower():
            #scientific float formatter
            return lambda x: f"{x:{format_str.lower().strip('e')}e}" if (x is not None and x is not np.nan) else "NaN"
        else:
            #fallback
            return lambda x: str(x) if (x is not None and x is not np.nan) else "NaN"

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
        return self.cdf_file_label in {'CDF_EPOCH', 'CDF_EPOCH16', 'CDF_TIME_TT2000'}


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

