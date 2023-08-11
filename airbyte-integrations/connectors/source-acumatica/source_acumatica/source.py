#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#


from abc import ABC
from datetime import datetime
import json
import requests
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple
from urllib.parse import urljoin


from airbyte_cdk.models import SyncMode
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream, IncrementalMixin
from airbyte_cdk.sources.streams.http import HttpStream

# list of all possible HTTP methods which can be used for sending of request bodies
BODY_REQUEST_METHODS = ("GET", "POST", "PUT", "PATCH")

# for custom cookie authentication
from airbyte_cdk.sources.streams.http.auth.core import HttpAuthenticator


class CookieAuthenticator(HttpAuthenticator):
    def __init__(self, config):
        self.name = config["name"]
        self.password = config["password"]
        self.tenant = config["tenant"]
        self.auth_body = {
            "name": self.name,
            "password": self.password
        }
        self.cookie_jar = self.login()

    def login(self):
        login_url = "https://{}.acumatica.com/entity/auth/login/".format(self.tenant)
        resp = requests.post(url=login_url, json=self.auth_body)
        resp.raise_for_status()
        return resp.cookies

    def get_auth_header(self) -> Mapping[str, Any]:
        return {"Cookie": "; ".join([f"{k}={v}" for k, v in requests.utils.dict_from_cookiejar(self.cookie_jar).items()])}
    
    def logout(self):
        logout_url = "https://{}.acumatica.com/entity/auth/logout/".format(self.tenant)
        resp = requests.post(url=logout_url, json = self.auth_body)
        resp.raise_for_status()


class AcumaticaStream(HttpStream, ABC):
    def __init__(self, config, authenticator, **kwargs):
        super(**kwargs).__init__(authenticator)
        self.tenant = config["tenant"]

    def get_url_base(self):
        return "https://{}.acumatica.com/entity/Default/22.200.001/".format(self.tenant)

    @property
    def url_base(self):
        return self.get_url_base()

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        # The API does not offer pagination, so we return None to indicate there are no more pages in the response
        return None

    def request_params(
        self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, any] = None, next_page_token: Mapping[str, Any] = None
    ) -> MutableMapping[str, Any]:
        return {}


class IncrementalAcumaticaStream(AcumaticaStream, IncrementalMixin):
    def __init__(self, config, authenticator, start_date: datetime, **kwargs):
        super(**kwargs).__init__(config, authenticator)
        self.start_date = start_date
        self._cursor_value = None

    @property
    def cursor_field(self) -> str:
        """
        :return str: The name of the cursor field.
        """
        return []

    @property
    def state(self) -> Mapping[str, Any]:
        if self._cursor_value:
            return {self.cursor_field: self._cursor_value}
        else:
            return {self.cursor_field: self.start_date}

    @state.setter
    def state(self, value: Mapping[str, Any]):
        self._cursor_value = value[self.cursor_field]

    def stream_slices(
        self, *, sync_mode: SyncMode, cursor_field: List[str] = None, stream_state: Mapping[str, Any] = None
    ) -> Iterable[Optional[Mapping[str, Any]]]:
        start_point = stream_state[self.cursor_field] if stream_state and self.cursor_field in stream_state else self.start_date
        yield {self.cursor_field: start_point}

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: List[str] = None,
        stream_slice: Mapping[str, Any] = None,
        stream_state: Mapping[str, Any] = None,
    ) -> Iterable[Mapping[str, Any]]:
        records = [r for r in super().read_records(sync_mode, cursor_field, stream_slice, stream_state)]
        for record in records:
            record_date = record[self.cursor_field].get("value")
            if self._cursor_value:
                self._cursor_value = max(record_date, self._cursor_value)
            else:
                self._cursor_value = record_date
            yield record


class Invoices(IncrementalAcumaticaStream):

    cursor_field = "LastModifiedDateTime"
    primary_key = "id"

    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "Invoice"

    def request_params(
        self,
        stream_state: Mapping[str, Any],
        stream_slice: Mapping[str, Any] = None,
        next_page_token: Mapping[str, Any] = None,
    ) -> MutableMapping[str, Any]:
        start_point = str(stream_slice[self.cursor_field])
        return {"$filter": f"{self.cursor_field} gt datetimeoffset'{start_point[:22]}'"}

    def parse_response(
        self,
        response: requests.Response,
        stream_state: Mapping[str, Any],
        stream_slice: Mapping[str, Any] = None,
        next_page_token: Mapping[str, Any] = None,
    ) -> Iterable[Mapping]:
        data = response.json()
        return data


class Customers(IncrementalAcumaticaStream):

    cursor_field = "LastModifiedDateTime"
    primary_key = "id"

    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "Customer"

    def request_params(
        self,
        stream_state: Mapping[str, Any],
        stream_slice: Mapping[str, Any] = None,
        next_page_token: Mapping[str, Any] = None,
    ) -> MutableMapping[str, Any]:
        start_point = str(stream_slice[self.cursor_field])
        return {"$filter": f"{self.cursor_field} gt datetimeoffset'{start_point[:22]}'"}

    def parse_response(
        self,
        response: requests.Response,
        stream_state: Mapping[str, Any],
        stream_slice: Mapping[str, Any] = None,
        next_page_token: Mapping[str, Any] = None,
    ) -> Iterable[Mapping]:
        data = response.json()
        return data


class SalesOrder(IncrementalAcumaticaStream):

    cursor_field = "CreatedDate"
    primary_key = "id"

    def path(
        self, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None, next_page_token: Mapping[str, Any] = None
    ) -> str:
        return "SalesOrder"

    def request_params(
        self,
        stream_state: Mapping[str, Any],
        stream_slice: Mapping[str, Any] = None,
        next_page_token: Mapping[str, Any] = None,
    ) -> MutableMapping[str, Any]:
        start_point = str(stream_slice[self.cursor_field])
        return {"$filter": f"{self.cursor_field} gt datetimeoffset'{start_point[:22]}'"}

    def parse_response(
        self,
        response: requests.Response,
        stream_state: Mapping[str, Any],
        stream_slice: Mapping[str, Any] = None,
        next_page_token: Mapping[str, Any] = None,
    ) -> Iterable[Mapping]:
        data = response.json()
        return data


# Source
class SourceAcumatica(AbstractSource):
    def check_connection(self, logger, config) -> Tuple[bool, any]:
        """
        :param config:  the user-input config object conforming to the connector's spec.yaml
        :param logger:  logger object
        :return Tuple[bool, any]: (True, None) if the input config can be used to connect to the API successfully, (False, error) otherwise.
        """

        try:
            name = config["name"]
            password = config["password"]
            tenant = config["tenant"]

            url = "https://{}.acumatica.com/entity/auth/login/".format(tenant)
            body = {"name": name, "password": password}
            response = requests.post(url, json=body)
            if response.ok:
                logout_url = "https://{}.acumatica.com/entity/auth/logout/".format(tenant)
                requests.post(logout_url, json=body)
                return True, None
            else:
                return False, response.text
        except:
            return False, None

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        """
        :param config: A Mapping of the user input configuration as defined in the connector spec.
        """
        auth = CookieAuthenticator(config)
        start_date = config["start_date"]
        return [
            Invoices(config=config, authenticator=auth, start_date=start_date),
            Customers(config=config, authenticator=auth, start_date=start_date),
            SalesOrder(config=config, authenticator=auth, start_date=start_date),
        ]
