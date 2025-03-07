# Looker SDK is imported here and higher level wrapper functions/classes are provided to interact with Looker Server
import json
import logging
import os
from functools import lru_cache
from typing import Dict, List, MutableMapping, Optional, Sequence, Set, Union, cast

import looker_sdk
from looker_sdk.error import SDKError
from looker_sdk.rtl.transport import TransportOptions
from looker_sdk.sdk.api31.models import (
    Dashboard,
    DashboardBase,
    DBConnection,
    Folder,
    LookmlModel,
    User,
    WriteQuery,
)
from pydantic import BaseModel, Field

from datahub.configuration import ConfigModel
from datahub.configuration.common import ConfigurationError

logger = logging.getLogger(__name__)


class TransportOptionsConfig(ConfigModel):
    timeout: int
    headers: MutableMapping[str, str]

    def get_transport_options(self) -> TransportOptions:
        return TransportOptions(timeout=self.timeout, headers=self.headers)


class LookerAPIConfig(ConfigModel):
    client_id: str = Field(description="Looker API client id.")
    client_secret: str = Field(description="Looker API client secret.")
    base_url: str = Field(
        description="Url to your Looker instance: `https://company.looker.com:19999` or `https://looker.company.com`, or similar. Used for making API calls to Looker and constructing clickable dashboard and chart urls."
    )
    transport_options: Optional[TransportOptionsConfig] = Field(
        None,
        description="Populates the [TransportOptions](https://github.com/looker-open-source/sdk-codegen/blob/94d6047a0d52912ac082eb91616c1e7c379ab262/python/looker_sdk/rtl/transport.py#L70) struct for looker client",
    )


class LookerAPIStats(BaseModel):
    dashboard_calls: int = 0
    user_calls: int = 0
    explore_calls: int = 0
    query_calls: int = 0
    folder_calls: int = 0
    all_connections_calls: int = 0
    connection_calls: int = 0
    lookml_model_calls: int = 0
    all_dashboards_calls: int = 0
    search_dashboards_calls: int = 0


class LookerAPI:
    """A holder class for a Looker client"""

    def __init__(self, config: LookerAPIConfig) -> None:
        self.config = config
        # The Looker SDK looks wants these as environment variables
        os.environ["LOOKERSDK_CLIENT_ID"] = config.client_id
        os.environ["LOOKERSDK_CLIENT_SECRET"] = config.client_secret
        os.environ["LOOKERSDK_BASE_URL"] = config.base_url

        self.client = looker_sdk.init31()
        self.transport_options = (
            config.transport_options.get_transport_options()
            if config.transport_options is not None
            else None
        )
        # try authenticating current user to check connectivity
        # (since it's possible to initialize an invalid client without any complaints)
        try:
            self.me = self.client.me(
                transport_options=self.transport_options
                if config.transport_options is not None
                else None
            )
        except SDKError as e:
            raise ConfigurationError(
                "Failed to initialize Looker client. Please check your configuration."
            ) from e

        self.client_stats = LookerAPIStats()

    @staticmethod
    def __fields_mapper(fields: Union[str, List[str]]) -> str:
        """Helper method to turn single string or list of fields into Looker API compatible fields param"""
        return fields if isinstance(fields, str) else ",".join(fields)

    def get_available_permissions(self) -> Set[str]:
        user_id = self.me.id
        assert user_id

        roles = self.client.user_roles(user_id)

        permissions: Set[str] = set()
        for role in roles:
            if role.permission_set and role.permission_set.permissions:
                permissions.update(role.permission_set.permissions)

        return permissions

    @lru_cache(maxsize=2000)
    def get_user(self, id_: int, user_fields: str) -> Optional[User]:
        self.client_stats.user_calls += 1
        try:
            return self.client.user(
                id_,
                fields=cast(str, user_fields),
                transport_options=self.transport_options,
            )
        except SDKError as e:
            logger.warning(f"Could not find user with id {id}")
            logger.warning(f"Failure was {e}")
        # User not found
        return None

    def execute_query(self, write_query: WriteQuery) -> List[Dict]:
        logger.debug(f"Executing query {write_query}")
        self.client_stats.query_calls += 1

        response_json = self.client.run_inline_query(
            result_format="json",
            body=write_query,
            transport_options=self.transport_options,
        )

        logger.debug("=================Response=================")
        data = json.loads(response_json)
        logger.debug("Length of response: %d", len(data))
        return data

    def dashboard(self, dashboard_id: str, fields: Union[str, List[str]]) -> Dashboard:
        self.client_stats.dashboard_calls += 1
        return self.client.dashboard(
            dashboard_id=dashboard_id,
            fields=self.__fields_mapper(fields),
            transport_options=self.transport_options,
        )

    def lookml_model_explore(self, model, explore_name):
        self.client_stats.explore_calls += 1
        return self.client.lookml_model_explore(
            model, explore_name, transport_options=self.transport_options
        )

    @lru_cache(maxsize=1000)
    def folder_ancestors(
        self, folder_id: str, fields: Union[str, List[str]] = "name"
    ) -> Sequence[Folder]:
        self.client_stats.folder_calls += 1
        return self.client.folder_ancestors(
            folder_id,
            self.__fields_mapper(fields),
            transport_options=self.transport_options,
        )

    def all_connections(self):
        self.client_stats.all_connections_calls += 1
        return self.client.all_connections(transport_options=self.transport_options)

    def connection(self, connection_name: str) -> DBConnection:
        self.client_stats.connection_calls += 1
        return self.client.connection(
            connection_name, transport_options=self.transport_options
        )

    def lookml_model(
        self, model_name: str, fields: Union[str, List[str]]
    ) -> LookmlModel:
        self.client_stats.lookml_model_calls += 1
        return self.client.lookml_model(
            model_name,
            self.__fields_mapper(fields),
            transport_options=self.transport_options,
        )

    def compute_stats(self) -> Dict:
        return {
            "client_stats": self.client_stats,
            "folder_cache": self.folder_ancestors.cache_info(),
            "user_cache": self.get_user.cache_info(),
        }

    def all_dashboards(self, fields: Union[str, List[str]]) -> Sequence[DashboardBase]:
        self.client_stats.all_dashboards_calls += 1
        return self.client.all_dashboards(
            fields=self.__fields_mapper(fields),
            transport_options=self.transport_options,
        )

    def search_dashboards(
        self, fields: Union[str, List[str]], deleted: str
    ) -> Sequence[Dashboard]:
        self.client_stats.search_dashboards_calls += 1
        return self.client.search_dashboards(
            fields=self.__fields_mapper(fields),
            deleted=deleted,
            transport_options=self.transport_options,
        )
