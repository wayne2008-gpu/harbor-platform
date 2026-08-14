import os

from synthetic_data_platform.app import create_app
from synthetic_data_platform.harbor_api import HttpHarborApiClient

_harbor_api_base_url = os.getenv("HARBOR_API_BASE_URL")
_harbor_api_client = (
    HttpHarborApiClient(_harbor_api_base_url) if _harbor_api_base_url else None
)

app = create_app(harbor_api_client=_harbor_api_client)
