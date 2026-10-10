#clean CDF export: same data pipeline as plaintext, but meta is OURS (matchfile), not the dirty original attrs
#reading order: exports -> _make_cdf_file -> _fetch_data -> CDFGroup -> CleanCDFWriter (main methods first, helpers after)
#ISTP stands for International Solar-Terrestrial Physics; standard for naming conventions in CDF files

from export.data_processing import DataHandler
from load_cdf.models import DynamicField, Upload
from solarterra.utils import float_ts_resolver as ft
from solarterra.utils import NOW
from django.http import HttpResponse
from spacepy import pycdf
import numpy as np
import datetime as dt
import tempfile, os, io, zipfile, ctypes
from dataclasses import dataclass
import logging

logger = logging.getLogger('solarterra.export')

#DataType.numpy_type has holes (CDF_UINT2 is None), these are fallback fillers
CDF_NUMPY_TYPES = {
    'CDF_INT1': np.int8, 'CDF_BYTE': np.int8, 'CDF_UINT1': np.uint8,
    'CDF_INT2': np.int16, 'CDF_UINT2': np.uint16,
    'CDF_INT4': np.int32, 'CDF_UINT4': np.uint32, 'CDF_INT8': np.int64,
    'CDF_REAL4': np.float32, 'CDF_FLOAT': np.float32,
    'CDF_REAL8': np.float64, 'CDF_DOUBLE': np.float64,
}
#our ISTP fills for types the shared DataType map leaves None (create_datatype.py TYPE_FILLVAL), tried after it
EXPORT_FILLVAL = {
    'CDF_INT8': '-9223372036854775808',
}
#ISTP fill for floats; only a default: aggregated values get it, otherwise the var's own FILLVAL wins
DEFAULT_FLOAT_FILL = -1.0e31
#CDF_EPOCH is ms since year 0, unix is s since 1970
EPOCH_UNIX_OFFSET_MS = 62167219200000.0

#global attr names = matchfile GlobalAttributes keys, Dataset field = key.lower(); same names as plaintext export
#note that ISTP uses another formatting convention for global attributes, e.g. "Mission_group" (ours only, unless Sasha says so)
GLOBAL_ATTRIBUTE_KEYS = [
    "MISSION", "SOURCE_NAME", "DATA_TYPE", "INSTRUMENT", "DATASET_VERSION",
    "TEXT_DESCRIPTION", "LOGICAL_SOURCE", "LOGICAL_DESCRIPTION", "PI_NAME", "PI_AFFILIATION",
]


#---EXPORTS---
def make_vargroup_bundles(job, var_groups):
    '''What goes into one CDF -> [(dataset, [var_group, ...])]. Useful for multiepoch datasets'''
    bundles = []
    for item in var_groups: #ordered by dataset tag, so groups of one dataset come in a row
        var_group = job.group_vars(item)
        if not job.split_by_resolution and bundles and bundles[-1][0].pk == item.dataset_id:
            bundles[-1][1].append(var_group)
        else:
            bundles.append((item.dataset, [var_group]))
    return bundles


def clean_cdf_export(job, dataset, var_groups):
    '''One file bundle -> single CDF file response.'''
    filename, cdf_bytes = _make_cdf_file(job, dataset, var_groups)
    response = HttpResponse(cdf_bytes, content_type='application/x-cdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def multi_clean_cdf_export(job, bundles):
    '''One CDF per file bundle, zipped -> response
    Also used in splitting files by day.'''
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for dataset, var_groups in bundles:
            if not job.split_by_day:
                zip_file.writestr(*_make_cdf_file(job, dataset, var_groups))
                continue
            #empty days are skipped; no data on any day -> one whole-range file with the "no data" note
            written = 0
            for day_job in job.day_jobs():
                made = _make_cdf_file(day_job, dataset, var_groups, skip_empty=True)
                if made is not None:
                    zip_file.writestr(*made)
                    written += 1
            if written == 0:
                zip_file.writestr(*_make_cdf_file(job, dataset, var_groups))

    zip_timestamp = dt.datetime.now().strftime("%Y-%m-%d-%H-%M")
    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="clean_cdf_export_{zip_timestamp}.zip"'
    return response


#---PIPELINE---
def _make_cdf_file(job, dataset, var_groups, skip_empty=False):
    '''Builds one CDF of one dataset, one or more var groups -> (filename, cdf_bytes).
    No data still gives a file, with a note (None if skip_empty and no group has data).'''
    groups = [CDFGroup.from_vars(var_group) for var_group in var_groups]
    writer = CleanCDFWriter(dataset)
    results = [_fetch_data(dataset, group, job) for group in groups]
    found = [r for r in results if r is not None]
    if not found and skip_empty:
        return None

    file_dt_str = job.dt_str
    bin_size = None
    if found:
        bin_size = found[0][3] #same Bin for every group: it only depends on the requested range
        if job.aggregate:
            first = min(r[0][0] for r in found)
            last = max(r[0][-1] for r in found)
            file_dt_str = ft(first).strftime('%Y%m%d%H%M') + '_' + ft(last).strftime('%Y%m%d%H%M')

    #one group keeps its epoch in the name (same as split), several -> dataset level
    epoch_part = f"{groups[0].depend_var.name}_" if len(groups) == 1 else ""
    filename = f"{dataset.tag}_{epoch_part}{job.mode_tag}_{file_dt_str}.cdf"
    info = {
        'filename': filename, 'ts_start': job.ts_start, 'ts_end': job.ts_end,
        'aggregate': job.aggregate, 'validate': job.validate, 'bin_size': bin_size,
    }

    pycdf.lib.set_backward(False) #v3 format, otherwise no TT2000/INT8, not python 2.7 compatible
    with tempfile.TemporaryDirectory() as temp_dir:
        cdf_path = os.path.join(temp_dir, filename)
        cdf = pycdf.CDF(cdf_path, '')
        try:
            writer.write_global_attrs(cdf, info)
            for group, result in zip(groups, results):
                if result is None:
                    no_data = f"no data for the requested interval {job.ts_start} to {job.ts_end}"
                    #several groups -> say which one is empty
                    writer.note(f"{group.depend_var.name}: {no_data}" if len(groups) > 1 else no_data.capitalize())
                    continue
                time_array, columns, valid, _ = result
                writer.write_data(cdf, group, time_array, columns, valid, job.aggregate)
            writer.write_notes(cdf)
        finally:
            cdf.close()

        with open(cdf_path, 'rb') as cdf_file:
            cdf_bytes = cdf_file.read()

    logger.info(f"clean_cdf: wrote {filename}, {len(cdf_bytes)} bytes, {len(writer.notes)} notes")
    return filename, cdf_bytes


def _fetch_data(dataset, group, job):
    '''Query, validate, aggregate one group -> (time_array, columns, valid, bin_size). None if there's no data.'''
    data = DataHandler(
        dataset=dataset,
        filter_field=group.depend_field,
        ts_start=job.ts_start,
        ts_stop=job.ts_end,
        fields=group.data_fields,
    )
    data.query()
    if not data.queryset.exists():
        return None

    data.set_data()
    if job.validate:
        data.add_validation_to_mask()

    if job.aggregate:
        data.set_bin_arrays()
        data.set_bin_map()
        data.set_aggregated_data()
        agg = data.agg_data_by_var
        if agg.shape[1] == 0:
            return None
        columns = agg[1:]
        valid = np.array([[v is not None for v in row] for row in columns], dtype=bool).reshape(columns.shape)
        return agg[0].astype(np.float64), columns, valid, data.bin_instance.bin_seconds

    return data.data_by_var[0].astype(np.float64), data.data_by_var[1:], data.mask[1:], None


#---GROUP---
@dataclass
class CDFGroup:
    '''One var group (dataset + depend_0): its epoch var/field + data fields in file order.'''
    variables: list
    depend_var: object
    depend_field: object
    data_fields: list

    @classmethod
    def from_vars(cls, var_group):
        variables = list(var_group)
        return cls(
            variables=variables,
            depend_var=variables[0].get_depend_var(),
            depend_field=variables[0].get_depend_field(),
            #order_by name = stable var order in the file; _fetch_data hands this same list to DataHandler, so columns line up with it
            data_fields=list(
                DynamicField.objects.filter(variable_instance__in=variables).order_by('variable_instance__name')
            ),
        )


#---WRITER---
class CleanCDFWriter():
    '''One CDF of one dataset; var groups get written into it one by one. Dirty meta gets skipped + noted'''

    def __init__(self, dataset):
        self.dataset = dataset
        #file-level: shared by all groups written into this CDF
        self.notes = []
        self.written_vars = set()

    #---WRITING---
    def write_global_attrs(self, cdf, info):
        for key in GLOBAL_ATTRIBUTE_KEYS:
            value = getattr(self.dataset, key.lower(), None)
            if value:
                cdf.attrs[key] = str(value)
        upload = Upload.objects.filter(dataset=self.dataset).exclude(matchfile_version="").order_by('-created').first()
        if upload is not None:
            cdf.attrs['MATCHFILE_VERSION'] = upload.matchfile_version
        #our own attrs, same UPPER style
        cdf.attrs['LOGICAL_FILE_ID'] = info['filename'].rsplit('.', 1)[0]
        cdf.attrs['GENERATED_BY'] = 'solarterra clean CDF export (IKI RAN)'
        cdf.attrs['GENERATION_DATE'] = NOW().strftime('%Y-%m-%d %H:%M:%S UTC')
        cdf.attrs['REQUESTED_INTERVAL'] = f"{info['ts_start']} to {info['ts_end']}"
        cdf.attrs['VALIDATION'] = (
            'Values outside VALIDMIN/VALIDMAX replaced with FILLVAL' if info['validate'] else 'Not validated'
        )
        if info['aggregate'] and info['bin_size'] is not None:
            cdf.attrs['AGGREGATION'] = (
                f"Averaged into {info['bin_size']:.3f}s bins; time values are bin centers; empty bins are FILLVAL"
            )
        else:
            cdf.attrs['AGGREGATION'] = 'None'
        #machine-readable twins of the two texts above; CDF attrs have no bool type -> 'True'/'False' strings
        cdf.attrs['IS_VALIDATED'] = str(bool(info['validate']))
        cdf.attrs['IS_AGGREGATED'] = str(bool(info['aggregate']))
        #not applicable = not written (matchfiles use null for that, CDF attrs can't hold null)
        if info['aggregate'] and info['bin_size'] is not None:
            cdf.attrs['BIN_SIZE_MS'] = float(info['bin_size']) * 1000.0

    def write_data(self, cdf, group, time_array, columns, valid, aggregate):
        '''One group's epoch + data vars. Time array is in unix seconds; columns/valid are expanded like data_by_var (array field = array_size columns).'''
        epoch_name = group.depend_var.name
        epoch_values, epoch_type = self._epoch_values(time_array, group.depend_var.datatype)
        self._new_record_var(cdf, epoch_name, epoch_values, epoch_type)
        self.written_vars.add(epoch_name)
        self._write_common_attrs(cdf, cdf[epoch_name], group.depend_var, np.float64, epoch_type)
        if aggregate:
            cdf[epoch_name].attrs['VAR_NOTES'] = 'Aggregation bin centers'

        col = 0
        for df in group.data_fields:
            var = df.variable_instance
            size = df.array_size if df.is_array_field else None
            width = size or 1
            raw = columns[col:col + width]
            ok = valid[col:col + width]
            col += width

            prepared = self._prepare_values(var, raw, ok, aggregate, size)
            if prepared is None:
                continue
            values, np_type, cdf_type, fill = prepared

            try:
                self._new_record_var(cdf, var.name, values, cdf_type)
            except Exception as e:
                self.note(f"{var.name}: can't write data ({e}), variable skipped")
                if var.name in cdf:
                    del cdf[var.name] #half-made var (created, data failed) out of the file
                continue
            self.written_vars.add(var.name)
            cdf_var = cdf[var.name]
            self._write_common_attrs(cdf, cdf_var, var, np_type, cdf_type, fill, size)
            self._set_attr(cdf_var, 'DEPEND_0', epoch_name)
            if var.depend_1:
                self._write_depend_1(cdf, cdf_var, var)

    #REVIEW - separate user-facing notes from internal logging
    def write_notes(self, cdf):
        if self.notes:
            cdf.attrs['EXPORT_NOTES'] = self.notes
            #one readable block in the log too, for now
            block = "\n".join(f"    - {msg}" for msg in self.notes)
            logger.info(f"clean_cdf: {len(self.notes)} notes for {self.dataset.tag}:\n{block}")

    #---HELPERS---
    def note(self, msg):
        logger.debug(f"clean_cdf: {msg}")
        self.notes.append(msg)

    def _new_record_var(self, cdf, name, values, cdf_type):
        '''Record-varying var sized to its data. Blocking factor = record count, else the CDF lib preallocates spare records (~2x file size).'''
        values = np.asarray(values)
        cdf_var = cdf.new(name, type=cdf_type, dims=list(values.shape[1:]) or None)
        #spacepy has no public setter for this, so the raw CDF lib call
        cdf_var._call(pycdf.const.PUT_, pycdf.const.zVAR_BLOCKINGFACTOR_, ctypes.c_long(max(len(values), 1)))
        #raw = values go in as-is (EPOCH ms / TT2000 ns already converted), no datetime guessing
        cdf.raw_var(name)[...] = values
        return cdf_var

    def _prepare_values(self, var, raw, ok, aggregate, size):
        '''Raw values + mask -> (values, np_type, cdf_type, fill), shaped for CDF. None if the type is unknown.'''
        #why all this: ints can't be NaN (see missing_values_explained.md), so a "missing" slot can't stay empty;
        #CDF needs a real number of the var's type in every slot -> FILLVAL, and the FILLVAL attr tells readers which one

        #1. CDF type name -> numpy type + pycdf type const; unknown type = skip + note, never guess
        np_type = CDF_NUMPY_TYPES.get(var.datatype)
        cdf_type = getattr(pycdf.const, var.datatype, None) if var.datatype else None
        if np_type is None or cdf_type is None:
            self.note(f"{var.name}: unsupported type {var.datatype}, variable skipped")
            return None

        #2. mean of ints is not an int -> aggregated ints get written as float64 / REAL8
        if aggregate and np.issubdtype(np_type, np.integer):
            np_type, cdf_type = np.float64, pycdf.const.CDF_REAL8

        #3. the "missing" number: aggregated data is float by now -> float default;
        #raw data keeps the var's own type -> its own FILLVAL (matchfile, then DataType default)
        fill = np_type(DEFAULT_FLOAT_FILL) if aggregate else self._fill_value(var, np_type)

        #4. start with "everything missing", then copy in only the good values (ok = the validation mask)
        values = np.full(raw.shape, fill, dtype=np_type)
        values[ok] = raw[ok].astype(np_type)

        # object-type piles may let NaN sneak past the None mask, which was fixed as a bug in earlier versions
        # fill with fillval just in case
        if np.issubdtype(np_type, np.floating):
            values[np.isnan(values)] = fill

        #5. pipeline gives one row per component; CDF wants (records,) for scalars, (records, size) for arrays
        values = values[0] if size is None else values.T
        return values, np_type, cdf_type, fill

    #REVIEW - move to utils?
    @staticmethod
    def _as_list(value):
        if value is None:
            return None
        return value if isinstance(value, (list, tuple)) else [value]

    def _fill_value(self, var, np_type):
        '''Fill value: matchfile FILLVAL -> DataType default -> EXPORT_FILLVAL, first one that fits.'''
        candidates = [var.fillval]
        try:
            candidates.append(var.get_data_type_instance().fillval)
        except Exception:
            pass
        candidates.append(EXPORT_FILLVAL.get(var.datatype))
        for raw in candidates:
            if raw is None or raw == "":
                continue
            try:
                num = float(str(raw).strip("[]'\" "))
                if np.issubdtype(np_type, np.integer):
                    info = np.iinfo(np_type)
                    if not info.min <= num <= info.max:
                        self.note(f"{var.name}: FILLVAL {raw} doesn't fit {np.dtype(np_type).name}, using default")
                        continue
                    return np_type(int(num))
                return np_type(num)
            except (ValueError, TypeError):
                self.note(f"{var.name}: can't parse FILLVAL '{raw}'")
        #no fallback for the fallback: DataType default IS the fallback (create_datatype.py TYPE_FILLVAL)
        # if np.issubdtype(np_type, np.integer):
        #     info = np.iinfo(np_type)
        #     return np_type(info.min if info.min < 0 else info.max)
        # return np_type(DEFAULT_FLOAT_FILL)
        return None

    def _epoch_values(self, unix_seconds, cdf_type):
        unix_seconds = np.asarray(unix_seconds, dtype=np.float64)
        if cdf_type == 'CDF_TIME_TT2000':
            dts = [ft(s).replace(tzinfo=None) for s in unix_seconds]
            return pycdf.lib.v_datetime_to_tt2000(dts), pycdf.const.CDF_TIME_TT2000
        #EPOCH16 goes as plain EPOCH, we only store ms anyway
        return unix_seconds * 1000.0 + EPOCH_UNIX_OFFSET_MS, pycdf.const.CDF_EPOCH

    def _set_attr(self, cdf_var, name, value, cdf_type=None):
        if value is None or (isinstance(value, (str, list, tuple, np.ndarray)) and len(value) == 0):
            return
        try:
            if cdf_type is not None:
                cdf_var.attrs.new(name, value, type=cdf_type)
            else:
                cdf_var.attrs[name] = value
        except Exception as e:
            self.note(f"{cdf_var.name()}: skipped attribute {name}={value!r} ({e})")

    def _typed_attr(self, var, raw, np_type, cdf_type):
        '''Casts VALIDMIN/MAX, SCALEMIN/MAX (str or list of str) to the variable type.'''
        values = self._as_list(raw)
        if values is None:
            return None
        try:
            if cdf_type in (pycdf.const.CDF_EPOCH, pycdf.const.CDF_TIME_TT2000):
                dts = [dt.datetime.strptime(str(v).strip(), "%d-%b-%Y %H:%M:%S.%f") for v in values]
                seconds = [d.replace(tzinfo=dt.timezone.utc).timestamp() for d in dts]
                converted, _ = self._epoch_values(seconds, 'CDF_TIME_TT2000' if cdf_type == pycdf.const.CDF_TIME_TT2000 else 'CDF_EPOCH')
            else:
                converted = np.array([float(v) for v in values]).astype(np_type)
            return converted[0] if len(converted) == 1 else converted
        except Exception as e:
            self.note(f"{var.name}: can't convert {raw!r} to {np.dtype(np_type).name if np_type else cdf_type} ({e})")
            return None

    def _write_common_attrs(self, cdf, cdf_var, var, np_type, cdf_type, fill=None, size=None):
        '''Standard ISTP var attrs + labels/units. size = array size, None for scalars.'''
        self._set_attr(cdf_var, 'FIELDNAM', var.name)
        self._set_attr(cdf_var, 'CATDESC', var.catdesc)
        self._set_attr(cdf_var, 'VAR_NOTES', var.var_notes)
        self._set_attr(cdf_var, 'VAR_TYPE', var.var_logic_type)
        self._set_attr(cdf_var, 'DISPLAY_TYPE', var.display_type)
        self._set_attr(cdf_var, 'SCALETYP', var.scaletyp)
        formats = self._as_list(var.output_format)
        if formats:
            self._set_attr(cdf_var, 'FORMAT', str(formats[0]).strip())
        if fill is not None:
            self._set_attr(cdf_var, 'FILLVAL', fill, cdf_type)
        for attr_name, raw in (('VALIDMIN', var.validmin), ('VALIDMAX', var.validmax),
                               ('SCALEMIN', var.scalemin), ('SCALEMAX', var.scalemax)):
            value = self._typed_attr(var, raw, np_type, cdf_type)
            if value is not None:
                self._set_attr(cdf_var, attr_name, value, cdf_type)

        #labels + units: scalars get LABLAXIS/UNITS, arrays get LABL_PTR_1/UNIT_PTR small text vars
        units = self._as_list(var.units)
        units = [str(u).strip() for u in units] if units else None
        if size is None:
            self._set_attr(cdf_var, 'LABLAXIS', var.pick_axis_value(var.get_axis_labels_source()))
            if units:
                self._set_attr(cdf_var, 'UNITS', units[0])
            return

        labels = self._as_list(var.get_axis_labels_source())
        if labels:
            label_name = var.labl_ptr or f"label_{var.name}"
            self._write_small_text_meta(cdf, label_name, [str(l).strip() for l in labels], f"Component labels for {var.name}")
            self._set_attr(cdf_var, 'LABL_PTR_1', label_name)
        if units:
            if len(set(units)) == 1:
                self._set_attr(cdf_var, 'UNITS', units[0])
            else:
                unit_name = f"unit_{var.name}"
                self._write_small_text_meta(cdf, unit_name, units, f"Component units for {var.name}")
                self._set_attr(cdf_var, 'UNIT_PTR', unit_name)

    def _write_small_text_meta(self, cdf, name, strings, catdesc):
        if name in self.written_vars:
            return
        try:
            cdf.new(name, data=strings, type=pycdf.const.CDF_CHAR, recVary=False)
            cdf[name].attrs['FIELDNAM'] = name
            cdf[name].attrs['CATDESC'] = catdesc
            cdf[name].attrs['VAR_TYPE'] = 'metadata'
            self.written_vars.add(name)
        except Exception as e:
            self.note(f"can't write metadata variable {name} ({e})")

    def _write_depend_1(self, cdf, cdf_var, var):
        '''Writes a non-record-varying support variable (e.g. spectrogram energy bins) from NRVData.'''
        name = var.depend_1
        if name in self.written_vars:
            self._set_attr(cdf_var, 'DEPEND_1', name)
            return
        nrv = self.dataset.nrv_data.filter(variable__name=name).first()
        if nrv is None or nrv.value is None:
            self.note(f"{var.name}: DEPEND_1 '{name}' has no stored values, skipped")
            return
        support_var = nrv.variable
        np_type = CDF_NUMPY_TYPES.get(support_var.datatype, np.float64)
        cdf_type = getattr(pycdf.const, support_var.datatype, pycdf.const.CDF_REAL8)
        try:
            cdf.new(name, data=np.array(nrv.value).astype(np_type), type=cdf_type, recVary=False)
        except Exception as e:
            self.note(f"{var.name}: can't write DEPEND_1 '{name}' ({e})")
            return
        self.written_vars.add(name)
        self._write_common_attrs(cdf, cdf[name], support_var, np_type, cdf_type, self._fill_value(support_var, np_type))
        self._set_attr(cdf_var, 'DEPEND_1', name)
