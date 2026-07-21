from django.core.management.base import BaseCommand
from load_cdf.models import DataType
from solarterra.utils import *


TYPE_CONVERSION = {
    'CDF_INT1': 'models.SmallIntegerField',
    'CDF_BYTE': 'models.SmallIntegerField',
    'CDF_UINT1': 'models.PositiveSmallIntegerField',
    'CDF_INT2': 'models.IntegerField',
    'CDF_UINT2': 'models.PositiveIntegerField',
    'CDF_INT4': 'models.IntegerField',
    'CDF_UINT4': 'models.PositiveIntegerField',
    'CDF_INT8': 'models.BigIntegerField',
    
    # pycdf opens as numpy.float32
    'CDF_FLOAT': 'Float32Field',
    # pycdf opens as numpy.float32
    'CDF_REAL4': 'Float32Field',
    # pycdfs opens as numpy.float64
    'CDF_DOUBLE': 'models.FloatField',
    # pycdf opens as numpy.float64
    'CDF_REAL8': 'models.FloatField',

    'CDF_CHAR': 'models.TextField',
    'CDF_UCHAR': 'models.TextField',
    'CDF_EPOCH': 'models.BigIntegerField',
    'CDF_TIME_TT2000': 'models.BigIntegerField',
}

TYPE_NUMPY = {
    #'CDF_INT1': '',
    #'CDF_BYTE': '',
    'CDF_UINT1': 'uint8',
    'CDF_INT2': 'int16',
    #'CDF_UINT2': '',
    'CDF_INT4': 'int32',
    #'CDF_UINT4': '',
    #'CDF_INT8': '',
    
    'CDF_FLOAT': 'float32',
    'CDF_REAL4': 'float32',
    'CDF_DOUBLE': 'float64',
    'CDF_REAL8': 'float64',

    #'CDF_CHAR': 'models.TextField',
    #'CDF_UCHAR': 'models.TextField',
    'CDF_EPOCH': 'object',
    'CDF_TIME_TT2000': 'object',
}

# taken from the cdf manual https://spdf.gsfc.nasa.gov/istp_guide/vattributes.html#FILLVAL
TYPE_FILLVAL = {
    'CDF_INT1': '-128',
    'CDF_BYTE': '-128',
    'CDF_UINT1': '255',
    'CDF_INT2': '-32768',
    'CDF_UINT2': '65535',
    'CDF_INT4': '-2147483648',
    'CDF_UINT4': '4294967295',
    'CDF_INT8': None,
    'CDF_FLOAT': '-1.0e+31',
    'CDF_REAL4': '-1.0e+31',
    'CDF_DOUBLE': '-1.0e+31',
    'CDF_REAL8': '-1.0e+31',
    'CDF_CHAR': None,
    'CDF_UCHAR': None,
    'CDF_EPOCH': None,
    'CDF_EPOCH16': '(-1.0e+31, -1.0e+31)',
    'CDF_TIME_TT2000': '-9223372036854775808',
}

class Command(BaseCommand):

    def handle(self, *args, **options):

        datatypes = []
        for cdf_file_label, django_field in TYPE_CONVERSION.items():
            print(cdf_file_label, django_field)

            numpy_type = TYPE_NUMPY[cdf_file_label] if cdf_file_label in TYPE_NUMPY.keys() else None
            
            datatypes.append(DataType(
                cdf_file_label=cdf_file_label,
                django_field=django_field,
                numpy_type=numpy_type,
                fillval=TYPE_FILLVAL[cdf_file_label]
            ))

        DataType.objects.bulk_create(datatypes)

