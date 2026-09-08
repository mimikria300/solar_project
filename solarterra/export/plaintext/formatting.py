#Plaintext export file meta (headers, footers, row labels etc) building

from load_cdf.models import *

class PlainTextMeta():

    GLOBAL_ATTRIBUTE_MAP = [
        ("MISSION", "mission"),
        ("SOURCE_NAME", "source_name"),
        ("DATA_TYPE", "data_type"),
        ("INSTRUMENT", "instrument"),
        ("DATASET_VERSION", "dataset_version"),
        ("TEXT_DESCRIPTION", "text_description"),
        ("LOGICAL_SOURCE", "logical_source"),
        ("LOGICAL_DESCRIPTION", "logical_description"),
        ("PI_NAME", "pi_name"),
        ("PI_AFFILIATION", "pi_affiliation"),
    ]

    def __init__(self, var_group):

        #var_group should belong to a single dataset and have the same depend_0
        self.var_group = var_group
        self.dataset = var_group[0].dataset

        self.labels = None
        self.units = None
        self.type_and_format_pairs = None
        self.format_map = None

        self.depend_field = var_group[0].get_depend_field()

        # Get all field names ordered by variable name then component index to match header
        dyn_fields_q = DynamicField.objects.filter(variable_instance__in=var_group).order_by('variable_instance__name')
        self.dyn_fields = list(dyn_fields_q.all()) #field instances
        print(
            f"[EXPORT] in _table_builder. dataset={self.dataset.tag}, depend_field={self.depend_field.field_name}, "
            f"dynamic_fields={self.dyn_fields}"
        )
        # prepend epoch/depend field so labels, units, formats, colwidths align with record_arrays column order
        # epoch isn't added to fields which are passed to query because it will be added as the filter_field in the query
        self.dyn_fields = [self.depend_field] + self.dyn_fields

        # flat list of (dyn_field, index_or_None): array fields expand to array_size entries
        self.columns = [(self.depend_field, None)]
        for df in self.dyn_fields[1:]:
            if df.is_array_field:
                self.columns += [(df, i) for i in range(df.array_size)]
            else:
                self.columns.append((df, None))

        self.info = {
            'validate': False,
            'unvalid_count': [],
            'aggregate': False,
            'bin_size': None,
            'survived_bins': None,
            'ts_start': None, 
            'ts_stop': None,
            'status': {},
            'notes': '',
        }

    def set_everything(self):
        self.set_labels_and_units()
        self.set_type_and_format_pairs()
        self.set_format_map()
        self.set_colwidths()

    def set_labels_and_units(self):

        self.labels = []
        self.units = []
        for df, index in self.columns:
            if df.data_type_instance.is_epoch():
                self.labels.append('Epoch')
                self.units.append('dd-mm-yyyy hh:mm:ss.ms')
                continue
            var = df.variable_instance
            label = var._pick_axis_value(var._get_axis_labels_source(), index)
            unit = var._pick_axis_value(var.units, index) 
            self.labels.append(label if label else '')
            self.units.append(unit if unit else '')

    def set_type_and_format_pairs(self):

        self.type_and_format_pairs = []
        for df, index in self.columns:
            format_str = df.get_format_str()
            if isinstance(format_str, list) and index is not None:
                format_str = format_str[index]
            type_instance = df.data_type_instance
            self.type_and_format_pairs.append((type_instance, format_str))

    def set_format_map(self):

        '''
        Build a list of formatter functions corresponding to the fields.
        Sorted by the order of fields in the record arrays, which is the same as the order of field names in field_names_for_query.
        '''

        self.format_map = []
        for type_instance, format_str in self.type_and_format_pairs:

            formatter = DynamicField.make_format_function(type_instance, format_str)
            self.format_map.append(formatter)

        #alternatively, if we are sure format functions are set
        # for df in self.dyn_fields:
        #     formatter = df.format_function
        #     self.format_map.append(formatter)

    def set_colwidths(self):
        self.colwidths = []
        for label, tf_pair, unit in zip(self.labels, self.type_and_format_pairs, self.units):
            cw = max(len(label), len(unit))
            type_instance, format_str = tf_pair
            if type_instance.is_epoch():
                cw = max(cw, len("dd-mm-yyyy hh:mm:ss.ms"))
            elif format_str is not None and "i" in format_str.lower():
                cw = max(cw, int(format_str.lower().strip("i")))
            elif format_str is not None and "f" in format_str.lower():
                #print("FLOAT FORMAT STR", format_str, label, unit)
                cw = max(cw, int(format_str.lower().strip("f").split(".")[0]))
            elif format_str is not None and "e" in format_str.lower():
                cw = max(cw, int(format_str.lower().strip("e").split(".")[0]) + 5)
            else:
                #would be nice to evaluate the length of the string based on the actual data
                cw = max(cw, 10)
            self.colwidths.append(cw+5) #+5 for padding

    #----STREAMING FUNCTIONS----

    def stream_header(self):
        '''Yield the file header block: global attributes + record varying variable descriptions.'''

        depend_var = self.var_group[0].get_depend_var()
        described_variables = list(self.var_group)
        if depend_var is not None and all(var.id != depend_var.id for var in described_variables):
            described_variables = [depend_var] + described_variables

        #not a tuple, python convention for formatting
        ga = (
            '#              ************************************\n'
            '#              *****    GLOBAL ATTRIBUTES    ******\n'
            '#              ************************************\n'
            '#\n'
        )

        mf_str = self._render_global_attributes()

        rvv = (
            '#              ************************************\n'
            '#              ****  RECORD VARYING VARIABLES  ****\n'
            '#              ************************************\n'
            '#\n'
        )

        var_desc = ''
        for i, var in enumerate(described_variables, 1):
            catdesc = var.catdesc
            var_desc += f'#   {i}. {catdesc}\n'
        var_desc += '#\n'

        yield ga + mf_str + rvv + var_desc

    def _render_global_attributes(self):
        title_map = {}
        for attr in self.dataset.attributes.filter(linked_standard_field__isnull=False):
            standard_key = attr.linked_standard_field.upper()
            if standard_key not in title_map:
                title_map[standard_key] = attr.title

        lines = []
        for standard_key, dataset_field in self.GLOBAL_ATTRIBUTE_MAP:
            value = getattr(self.dataset, dataset_field, None)
            if value is None or value == "":
                continue

            original_name = title_map.get(standard_key)
            label = f"{standard_key} ({original_name})" if original_name else standard_key

            value_lines = str(value).splitlines()
            if not value_lines:
                continue

            lines.append(f"#     {label}: {value_lines[0]}\n")
            for extra_line in value_lines[1:]:
                lines.append(f"#     {extra_line}\n")

        lines.append('#\n')
        return ''.join(lines)

    def stream_label_rows(self):
        '''Yield the column label row and unit row.'''
        lblrow = ['#']
        unitrow = ['#']
        for label, unit, cw in zip(self.labels, self.units, self.colwidths):
            lblrow.append(' '*(cw - len(label)) + label)
            unitrow.append(' '*(cw - len(unit)) + unit)

        yield "".join(lblrow) + "\n"
        yield "".join(unitrow) + "\n"
    
    def _format_row(self, row):
        '''Format map application to a row, then conversion to fixed-width string.'''
        formatted_row = [" "]  # to correct first column padding to the # symbol in labels
        for value, formatter, cw in zip(row, self.format_map, self.colwidths):
            formatted_value = formatter(value)
            formatted_value = ' '*(cw - len(formatted_value)) + formatted_value
            formatted_row.append(formatted_value)
        return "".join(formatted_row) + "\n"

    def stream_formatted_rows(self, rows):

        '''Yield formatted data rows.'''
        for row in rows:
            yield self._format_row(row)

    def stream_footer(self):
        from solarterra.utils import NOW
        yield f"# End of data in the chosen interval for the dataset: {self.dataset.tag}.\n# File generated at {NOW()}\n"
        if self.info['validate']:
            yield f'# Data is validated to be in min/max bounds.\n'
            #TODO: add counter for nulled data for each var
            # yield f"Nulled {self.info['validation_removed_count']}" or some for-loop over every var or add tuple to "unvalid_counters", yes that
        else:
            yield '# Data is not validated to be in bounds.\n'
        #TODO: once we'll got the resolution match-field, we can add max points per bin to the metainfo.
        if self.info['aggregate']:
            yield f"# Data is aggregated by averaging. Bin size (time delta): {self.info['bin_size']}s. Note that empty bins may be produced by gaps in data.\n"
            yield f"# Requested data interval: {self.info['ts_start']} to {self.info['ts_end']}.\n"
            yield "# Time entries represent the aggregation bins' middle points.\n"
            #TODO: add survived bins counter
            #Number of non-empty bins: {self.info['survived_bins']}/1000.
        else:
            yield "# No aggregation performed.\n"
        
        yield self.info['notes']