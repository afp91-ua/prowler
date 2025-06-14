import sys
import json
import os
import subprocess
from typing import Any, Optional, Tuple

import ionoscloud
from ionoscloud import ApiClient, Configuration
from ionoscloud.rest import ApiException
import ionoscloud_dataplatform
from ionoscloud.api.data_centers_api import DataCentersApi
from ionoscloud.api.user_management_api import UserManagementApi

from prowler.config.config import get_default_mute_file_path, load_and_validate_config_file
from prowler.lib.logger import logger
from prowler.lib.mutelist.mutelist import Mutelist
from prowler.providers.ionos.lib.mutelist.mutelist import IonosMutelist
from prowler.providers.ionos.models import IonosIdentityInfo
from prowler.lib.utils.utils import open_file, parse_json_file, print_boxes
from colorama import Fore, Style

from prowler.providers.common.provider import Provider

class IonosProvider(Provider):
    _type: str = "ionos"
    _session: Optional[ApiClient] = None
    _identity: Optional[IonosIdentityInfo] = None
    _audit_config: dict = {}
    _output_options: Optional[Any] = None
    _mutelist: IonosMutelist
    audit_metadata: Optional[Any] = None
    _token = None
    _username = None
    _password = None
    _datacenter_id = None

    def __init__(
        self,
        ionos_username: Optional[str] = None,
        ionos_password: Optional[str] = None,
        ionos_datacenter_name: Optional[str] = None,
        config_path: Optional[str] = None,
        mutelist_path: Optional[str] = None,
        mutelist_content: dict = None,
    ):
        """
        Initializes the IonosProvider class and sets up the session.
        If no credentials are provided, it will attempt to load them from environment variables or ionosctl configuration.
        """
        logger.info("Initializing IONOS Provider...")
        self._token = self.load_ionosctl_token()
                
        self._identity = self.set_identity(
            username=ionos_username,
            password=ionos_password,
            datacenter_id="",
        )

        self._session = self.setup_session(
            identity=self._identity,
        )

        if not self.test_connection():
            logger.critical("Failed to establish connection with IONOS Cloud API, please check your credentials.")
            sys.exit(1)

        if not self._identity.username or not self._identity.password:
            self._identity.username = self.get_ionos_username()

        self._identity.datacenter_id = self.get_datacenter_id(ionos_datacenter_name)

        if config_path is None:
            self._audit_config = {}
        else:
            self._audit_config = load_and_validate_config_file("ionos", config_path)
        
        # Mutelist
        if mutelist_content:
            self._mutelist = IonosMutelist(
                mutelist_content=mutelist_content,
            )
        else:
            if not mutelist_path:
                mutelist_path = get_default_mute_file_path(self.type)
                logger.info(f"No mutelist path provided, using default: {mutelist_path}")
            self._mutelist = IonosMutelist(
                mutelist_path=mutelist_path,
            )
            logger.info(f"Loaded mutelist from {mutelist_path}")

        Provider.set_global_provider(self)

    @staticmethod
    def load_env_credentials() -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Reads IONOS credentials from environment variables.
        Returns a tuple with (username, password, token)
        """
        username = os.getenv("IONOS_USERNAME")
        password = os.getenv("IONOS_PASSWORD")
        token = os.getenv("IONOS_TOKEN")
        if username and password and token:
            logger.info("Loaded IONOS credentials from environment variables.")
        else:
            logger.warning("Not all credentials were found in environment variables.")
        return username, password, token

    @staticmethod
    def load_ionosctl_token() -> Optional[str]:
        """
        Reads the IONOS token from the ionosctl configuration file across different platforms.
        """
        platform = sys.platform
        
        is_wsl = False
        try:
            with open('/proc/version') as f:
                is_wsl = 'microsoft' in f.read().lower()
        except:
            pass

        config_paths = {
            "darwin": os.path.join(os.path.expanduser("~"), "Library", "Application Support", "ionosctl", "config.json"),
            "linux": os.path.join(os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "ionosctl", "config.json"),
            "win32": os.path.join(os.getenv("APPDATA", ""), "ionosctl", "config.json")
        }
        
        if is_wsl:
            try:
                windows_config = "/mnt/c/Users/{}/AppData/Roaming/ionosctl/config.json".format(
                    os.getenv("USER")
                )
                try:
                    with open(windows_config, "r") as config_file:
                        config = json.load(config_file)
                        logger.info("Loaded IONOS token from Windows ionosctl config file in WSL.")
                        return config.get("userdata.token")
                except Exception as e:
                    logger.debug(f"Could not load Windows config file in WSL, trying Linux path... {e}")
            except Exception as e:
                logger.debug(f"Failed to access Windows config file: {e}")
        
        config_path = config_paths.get(platform)
        
        if not config_path:
            logger.warning(f"Unsupported platform: {platform}")
            return None
            
        try:
            with open(config_path, "r") as config_file:
                config = json.load(config_file)
                logger.info("Loaded IONOS token from ionosctl config file.")
                return config.get("userdata.token")
        except (FileNotFoundError, json.JSONDecodeError) as error:
            logger.warning(f"Failed to load IONOS token from ionosctl: {error}")
            return None

    def get_ionos_username(self) -> Optional[str]:
        """
        Gets the IONOS username from the API.
        """
        user_api = UserManagementApi(self._session)
        try:
            user = user_api.um_users_get(depth=1).items[0]
            return user.properties.email
        except ApiException as error:
            logger.error(f"Failed to retrieve user information: {error}")
            sys.exit(1)

    @property
    def type(self) -> str:
        return self._type

    @property
    def identity(self) -> str:
        return self._identity

    @property
    def session(self) -> ApiClient:
        return self._session

    @property
    def audit_config(self) -> dict:
        return self._audit_config

    @property
    def mutelist(self) -> IonosMutelist:
        """
        mutelist method returns the provider's mutelist
        """
        return self._mutelist
    
    @property
    def session(self) -> ApiClient:
        return self._session

    def setup_session(
        self, 
        identity: IonosIdentityInfo,
    ) -> ApiClient:
        """
        Setup the session to interact with the IONOS Cloud API.
        """
        try:
            config = Configuration()

            config.username = identity.username
            config.password = identity.password
            config.token = identity.token

            logger.info("Successfully initialized IONOS Cloud API session.")
            return ApiClient(configuration=config)
        except Exception as error:
            logger.critical(f"Failed to initialize IONOS session: {error}")
            sys.exit(1)

    def print_credentials(self) -> None:     
        """
        Print the IONOS Cloud credentials.

        This method prints the IONOS Cloud credentials used by the provider.
        """

        username = self._session.configuration.username
        host = self._session.configuration.host
        if self._identity.token:
            if len(self._identity.token) > 8:
                masked_token = self._identity.token[:4] + "*" * 16 + self._identity.token[-4:]
            else:
                masked_token = self._identity.token
        else:
            masked_token = "Not Provided"

        datacenters = self.get_datacenters()

        datacenter_id = datacenters[0].id if datacenters else "Not Found"
        datacenter_name = datacenters[0].properties.name if datacenters else "Not Found"
        datacenter_location = datacenters[0].properties.location if datacenters else "Not Found"

        report_lines = [
            f"Datacenter ID: {Fore.YELLOW}{datacenter_id}{Style.RESET_ALL}",
            f"Datacenter Name: {Fore.YELLOW}{datacenter_name}{Style.RESET_ALL}",
            f"Datacenter Location: {Fore.YELLOW}{datacenter_location}{Style.RESET_ALL}",
        ]
        report_title = f"{Style.BRIGHT}Using the IONOS Cloud credentials below:{Style.RESET_ALL}"
        print_boxes(report_lines, report_title)

    def get_datacenter_id(self, datacenter_name: Optional[str] = None) -> str:
        """
        Gets the ID of a datacenter by its name.
        If the name is empty or None, returns the first available datacenter.
        """
        datacenters = self.get_datacenters()
        
        if not datacenter_name:
            return datacenters[0].id if datacenters else ""
        
        for datacenter in datacenters:
            if datacenter.properties.name == datacenter_name:
                return datacenter.id
        return ""

    def set_datacenter(self, datacenter_id: str) -> None:
        """
        Sets the active datacenter for operations.
        """
        self._identity.datacenter_id = datacenter_id

    def test_connection(self) -> bool:
        """
        Tests the connection with the IONOS API.
        """
        try:
            datacenter_api = DataCentersApi(self._session)
            datacenters = datacenter_api.datacenters_get()
            logger.info("Successfully connected to IONOS Cloud API.")
            return True
        except ApiException as error:
            return False

    def get_datacenters(self) -> list:
        """
        Retrieves the list of datacenters from the IONOS account.
        """
        try:
            datacenter_api = ionoscloud.DataCentersApi(self._session)
            datacenters = datacenter_api.datacenters_get(pretty=True, depth=1).items
            logger.info("Successfully retrieved datacenters from IONOS Cloud API.")
            return datacenters
        except ApiException as error:
            logger.error(f"Failed to retrieve datacenters from IONOS Cloud API: {error}")
            return []

    def set_identity(
        self,
        username: str,
        password: str,
        datacenter_id: str,
    ) -> IonosIdentityInfo:
        """
        set_identity sets the IONOS provider identity information.
        """
        return IonosIdentityInfo(
            username=username,
            password=password,
            datacenter_id=datacenter_id,
            token=self._token,
        )

    def validate_mutelist_content(self, content: dict) -> bool:
        """Validates the format of the mutelist content"""
        if not isinstance(content, dict):
            return False
        if "muted_checks" not in content:
            return False
        if not isinstance(content["muted_checks"], list):
            return False
        return True