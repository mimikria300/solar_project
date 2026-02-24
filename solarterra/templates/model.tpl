from django.db import models
import uuid
from solarterra.abstract_models import GetManager
from load_cdf.models import CDFFileStored, Float32Field

class {{ dm_instance.model_name }}(models.Model):

	{% for field in dm_instance.fields.all %}{% with datatype=field.data_type_instance%}
	{{ field.field_name }} = {{ datatype.django_field }}(blank=True, null=True)
	{% endwith %}{% endfor %}
	
	cdf_file = models.ForeignKey(CDFFileStored, on_delete=models.SET_NULL, related_name="{{ dm_instance.model_name}}_data", db_index=False, blank=True, null=True)

	objects = GetManager()	
