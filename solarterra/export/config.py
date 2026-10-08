"""
Export app configuration: constants + limits shared by all export formats
(plaintext, cdf, raw_cdf) and by the middleware stack.

These are defaults; override in settings.py as needed.
"""

# Hard ceiling on total export size (bytes) before SizeCheckMiddleware rejects the request.
#override via EXPORT_MAX_SIZE_BYTES in django settings (set it tiny to demo the 413)
EXPORT_MAX_SIZE_BYTES = 5 * 1024 ** 3  # 5 GB

#rough bytes per value for size estimates, roughly rounded up
BYTES_PER_VALUE = {
    "plain_text": 16,
    "clean_cdf": 8,
}


def get_max_export_size():
    from django.conf import settings
    return getattr(settings, "EXPORT_MAX_SIZE_BYTES", EXPORT_MAX_SIZE_BYTES)

# Max number of export requests a single user can make per day, anti-DDOS measure (RateLimitMiddleware).
RATE_LIMIT_PER_USER_PER_DAY = 500

# Registry of supported export formats: file extension + MIME type per format.
# Dispatcher uses the keys here to route requests to the matching format module.
EXPORT_FORMATS = {
    "plaintext": {
        "extension": "txt",
        "mime_type": "text/plain",
    },
    "cdf": {
        "extension": "cdf",
        "mime_type": "application/x-cdf",
    },
    "raw_cdf": {
        "extension": "zip",
        "mime_type": "application/zip",
    },
}
