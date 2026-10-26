"""Pluggable delivery backends.

The backend is selected via the DELIVERY_BACKEND environment variable
or the --backend command-line flag:

- ``smtp``      — classic SMTP with STARTTLS (default, no extra deps)
- ``gmail``     — Gmail API with OAuth2 (google-api-python-client)
- ``sendgrid``  — SendGrid v3 REST API (requests)
- ``ses``       — Amazon SES v2 API (boto3)

Optional dependencies are imported lazily so the core application
(and the test suite) works without them; using a backend without its
dependency installed raises ProviderNotInstalledError with the exact
package to install.
"""

import importlib

from config import VALID_BACKENDS

_MODULE_AND_CLASS = {
    "smtp": ("providers.smtp_provider", "SMTPProvider"),
    "gmail": ("providers.gmail_provider", "GmailProvider"),
    "sendgrid": ("providers.sendgrid_provider", "SendGridProvider"),
    "ses": ("providers.ses_provider", "SESProvider"),
}


def create_delivery_provider(backend):
    """Instantiate the delivery provider for a backend name.

    Raises:
        ValueError: If the backend name is unknown.
    """
    if backend not in _MODULE_AND_CLASS:
        raise ValueError(
            f"DELIVERY_BACKEND must be one of {', '.join(VALID_BACKENDS)} "
            f"(got {backend!r})"
        )

    module_name, class_name = _MODULE_AND_CLASS[backend]
    module = importlib.import_module(module_name)

    return getattr(module, class_name)()
