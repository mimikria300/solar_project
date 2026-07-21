import string, re


# better to do regex here?
def get_dataset_tag(zip_filename):
    return zip_filename.split('_u')[0]

# better to do regex here?
def get_upload_tag(zip_filename):
    return zip_filename.split('_u')[-1].strip('.zip')

def normalize_str(st):
    return st.strip().replace(' ', '_')

def remove_parenthesis(st):
    return re.sub(r'\([^)]*\)', '', st).strip()

def safe_str(st):
    allowed = string.ascii_lowercase + string.digits + '_'
    parsed = normalize_str(remove_parenthesis(st)).lower()
    return ''.join(filter(lambda x: x in allowed, parsed))

def to_python_identifier(value, prefix = "dataset"):
    value = re.sub(r'[^0-9A-Za-z_]', '_', value)
    value = re.sub(r'_+', '_', value).strip('_')

    if not value:
        return prefix

    if value[0].isdigit():
        value = f"{prefix}_{value}"

    return value
