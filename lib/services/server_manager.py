import datetime
import json
import os
import random
import re

from proton.api import Session

from lib import exceptions
from lib.constants import CACHED_SERVERLIST, PROTON_XDG_CACHE_HOME
from lib.logger import logger
from lib.enums import FeatureEnum

from . import capture_exception


class ServerManager():
    REFRESH_INTERVAL = 15

    def __init__(self, cert_manager):
        self.cert_manager = cert_manager

    def fastest(self, session, protocol, *_):
        """Connect to fastest server.

        Args:
            session (proton.api.Session): current user session
            protocol (ProtocolEnum): ProtocolEnum.TCP, ProtocolEnum.UDP ...
        Returns:
            string: path to certificate file that is to be imported into nm
        """
        self.validate_session_protocol(session, protocol)
        self.cache_servers(session)

        servers = self.filter_servers(session)
        excluded_features = [
            FeatureEnum.SECURE_CORE, FeatureEnum.TOR, FeatureEnum.P2P
        ]

        # Filter out excluded features
        server_pool = []
        for server in servers:
            if server["Features"] not in excluded_features:
                server_pool.append(server)

        servername, domain = self.get_fastest_server(server_pool)

        try:
            entry_IP, exit_IP, equal_IPs = self.generate_ip_list(
                servername, servers
            )
        except IndexError as e:
            logger.exception("[!] IllegalServername: {}".format(e))
            raise exceptions.IllegalServername(
                "\"{}\" is not a valid server".format(servername)
            )
        except Exception as e:
            capture_exception(e)

        if equal_IPs is not None and not equal_IPs:
            domain = self.get_matching_domain(servers, exit_IP)

        return self.cert_manager.generate_vpn_cert(
            protocol, session,
            servername, entry_IP
        ), domain

    def country_f(self, session, protocol, *args):
        """Connect to fastest server in a specific country.

        Args:
            session (proton.api.Session): current user session
            protocol (ProtocolEnum): ProtocolEnum.TCP, ProtocolEnum.UDP ...
            args (tuple(list)): country code [PT|SE|CH]
        Returns:
            string: path to certificate file that is to be imported into nm
        """
        self.validate_session_protocol(session, protocol)
        if not isinstance(args, tuple):
            err_msg = "Incorrect object type, "
            + "tuple is expected but got {} instead".format(type(args))
            logger.error(
                "[!] TypeError: {}. Raising exception.".format(err_msg)
            )
            raise TypeError(err_msg)
        elif not isinstance(args[0], list):
            err_msg = "Incorrect object type, "
            + "list is expected but got {} instead".format(type(args[0]))
            logger.error(
                "[!] TypeError: {}. Raising exception.".format(err_msg)
            )
            raise TypeError(err_msg)

        try:
            country_code = args[0][1].strip().upper()
        except IndexError as e:
            logger.exception("[!] IndexError: {}".format(e))
            raise IndexError(
                "Incorrect object type, "
                + "tuple(list) is expected but got {} ".format(args)
                + "instead"
            )
        except Exception as e:
            capture_exception(e)

        self.cache_servers(session)
        servers = self.filter_servers(session)

        excluded_features = [
            FeatureEnum.SECURE_CORE, FeatureEnum.TOR, FeatureEnum.P2P
        ]

        # Filter out excluded features and countries
        server_pool = []
        for server in servers:
            if (
                server["Features"] not in excluded_features
            ) and (
                server["ExitCountry"] == country_code
            ):
                server_pool.append(server)

        if len(server_pool) == 0:
            err_msg = "Invalid country code \"{}\"".format(country_code)
            logger.error(
                "[!] ValueError: {}. Raising exception.".format(err_msg)
            )
            raise ValueError(err_msg)

        servername, domain = self.get_fastest_server(server_pool)

        try:
            entry_IP, exit_IP, equal_IPs = self.generate_ip_list(
                servername, servers
            )
        except IndexError as e:
            logger.exception("[!] IllegalServername: {}".format(e))
            raise exceptions.IllegalServername(
                "\"{}\" is not a valid server".format(servername)
            )
        except Exception as e:
            capture_exception(e)

        if equal_IPs is not None and not equal_IPs:
            domain = self.get_matching_domain(servers, exit_IP)

        return self.cert_manager.generate_vpn_cert(
            protocol, session,
            servername, entry_IP
        ), domain

    def direct(self, session, protocol, *args):
        """Connect directly to specified server.

        Args:
            session (proton.api.Session): current user session
            protocol (ProtocolEnum): ProtocolEnum.TCP, ProtocolEnum.UDP ...
            args (tuple(list)|tuple): servername to connect to
        Returns:
            string: path to certificate file that is to be imported into nm
        """
        self.validate_session_protocol(session, protocol)
        if not isinstance(args, tuple):
            err_msg = "Incorrect object type, "
            + "tuple is expected but got {} ".format(type(args))
            + "instead"
            logger.error(
                "[!] TypeError: {}. Raising exception.".format(err_msg)
            )
            raise TypeError(err_msg)
        elif (
            isinstance(args, tuple) and len(args) == 0
        ) or (
            isinstance(args, str) and len(args) == 0
        ):
            err_msg = "The provided argument \"args\" is empty"
            logger.error(
                "[!] ValueError: {}. Raising exception.".format(err_msg)
            )
            raise ValueError(err_msg)

        user_input = args[0]
        if isinstance(user_input, list):
            user_input = user_input[1]

        servername = user_input.strip().upper()

        if not self.is_servername_valid(user_input):
            err_msg = "Unexpected servername {}".format(user_input)
            logger.error(
                "[!] IllegalServername: {}. Raising exception.".format(err_msg)
            )
            raise exceptions.IllegalServername(err_msg)

        self.cache_servers(session)
        servers = self.filter_servers(session)

        try:
            entry_IP, exit_IP, equal_IPs = self.generate_ip_list(
                servername, servers
            )
        except IndexError as e:
            logger.exception("[!] IllegalServername: {}".format(e))
            raise exceptions.IllegalServername(
                "\"{}\" is not an existing server".format(servername)
            )
        except Exception as e:
            capture_exception(e)

        if servername not in [server["Name"] for server in servers]:
            err_msg = "{} is either invalid, ".format(servername)
            + "under maintenance or inaccessible with your plan"
            logger.error(
                "[!] ValueError: {}. Raising exception.".format(err_msg)
            )
            raise ValueError(err_msg)

        servername, domain = [
            (server["Name"], server["Domain"])
            for server in servers
            if servername == server["Name"]
        ][0]

        if equal_IPs is not None and not equal_IPs:
            domain = self.get_matching_domain(servers, exit_IP)

        return self.cert_manager.generate_vpn_cert(
            protocol, session,
            servername, entry_IP
        ), domain

    def feature_f(self, session, protocol, *args):
        """Connect to fastest server based on specified feature.

        Args:
            session (proton.api.Session): current user session
            protocol (ProtocolEnum): ProtocolEnum.TCP, ProtocolEnum.UDP ...
            args (tuple(list)): literal feature [p2p|tor|sc]
        Returns:
            string: path to certificate file that is to be imported into nm
        """
        self.validate_session_protocol(session, protocol)
        if not isinstance(args, tuple):
            err_msg = "Incorrect object type, "
            + "tuple is expected but got {} ".format(type(args))
            + "instead"
            logger.error(
                "[!] TypeError: {}. Raising exception.".format(err_msg)
            )
            raise TypeError(err_msg)
        elif len(args) == 0:
            err_msg = "The provided argument \"args\" is empty"
            logger.error(
                "[!] ValueError: {}. Raising exception.".format(err_msg)
            )
            raise ValueError(err_msg)
        elif not isinstance(args[0], list):
            err_msg = "Incorrect object type, "
            + "list is expected but got {} ".format(type(args))
            + "instead"
            logger.error(
                "[!] TypeError: {}. Raising exception.".format(err_msg)
            )
            raise TypeError(err_msg)

        literal_feature = args[0][0].strip().lower()
        allowed_features = {
            "sc": FeatureEnum.SECURE_CORE,
            "tor": FeatureEnum.TOR,
            "p2p": FeatureEnum.P2P,
            "stream": FeatureEnum.STREAMING,
            "ipv6": FeatureEnum.IPv6
        }

        try:
            feature = allowed_features[literal_feature]
        except KeyError as e:
            logger.exception("[!] ValueError: {}".format(e))
            raise ValueError("Feature is non-existent")
        except Exception as e:
            capture_exception(e)

        self.cache_servers(session)

        servers = self.filter_servers(session)

        server_pool = [s for s in servers if s["Features"] == feature]

        if len(server_pool) == 0:
            err_msg = "No servers found with the {} feature".format(
                literal_feature
            )
            logger.error(
                "[!] EmptyServerListError: {}. Raising exception.".format(
                    err_msg
                )
            )
            raise exceptions.EmptyServerListError(err_msg)

        servername, domain = self.get_fastest_server(server_pool)

        try:
            entry_IP, exit_IP, equal_IPs = self.generate_ip_list(
                servername, servers
            )
        except IndexError as e:
            logger.exception("[!] IllegalServername: {}".format(e))
            raise exceptions.IllegalServername(
                "\"{}\" is not a valid server".format(servername)
            )
        except Exception as e:
            capture_exception(e)

        if equal_IPs is not None and not equal_IPs:
            domain = self.get_matching_domain(servers, exit_IP)

        return self.cert_manager.generate_vpn_cert(
            protocol, session,
            servername, entry_IP
        ), domain

    def random_c(self, session, protocol, *_):
        """Connect to a random server.

        Args:
            session (proton.api.Session): current user session
            protocol (ProtocolEnum): ProtocolEnum.TCP, ProtocolEnum.UDP ...
        Returns:
            string: path to certificate file that is to be imported into nm
        """
        self.validate_session_protocol(session, protocol)
        servers = self.filter_servers(session)

        random_choice = random.choice(servers)
        servername = random_choice["Name"]
        domain = random_choice["Domain"]

        try:
            entry_IP, exit_IP, equal_IPs = self.generate_ip_list(
                servername, servers
            )
        except IndexError as e:
            logger.exception("[!] IllegalServername: {}".format(e))
            raise exceptions.IllegalServername(
                "\"{}\" is not a valid server".format(servername)
            )
        except Exception as e:
            capture_exception(e)

        if equal_IPs is not None and not equal_IPs:
            domain = self.get_matching_domain(servers, exit_IP)

        return self.cert_manager.generate_vpn_cert(
            protocol, session,
            servername, entry_IP
        ), domain

    def get_matching_domain(self, server_pool, exit_IP):
        for server in server_pool:
            for physical_server in server["Servers"]:
                if exit_IP in physical_server["EntryIP"]:
                    return physical_server["Domain"]

    def validate_session_protocol(self, session, protocol):
        """Validates session and protocol

        Args:
            session (proton.api.Session): current user session
            protocol (ProtocolEnum): ProtocolEnum.TCP, ProtocolEnum.UDP ...
        """
        logger.info("Validating session and protocol")
        if not isinstance(session, Session):
            err_msg = "Incorrect object type, "
            + "{} is expected ".format(type(Session))
            + "but got {} instead".format(type(session))
            logger.error(
                "[!] TypeError: {}. Raising exception.".format(
                    err_msg
                )
            )
            raise TypeError(err_msg)

        if not isinstance(protocol, str):
            err_msg = "Incorrect object type, "
            + "str is expected but got {} instead".format(type(protocol))
            logger.error(
                "[!] TypeError: {}. Raising exception.".format(
                    err_msg
                )
            )
            raise TypeError(err_msg)
        elif len(protocol) == 0:
            err_msg = "The provided argument \"protocol\" is empty"
            logger.error(
                "[!] TypeError: {}. Raising exception.".format(
                    err_msg
                )
            )
            raise ValueError(err_msg)

    def cache_servers(
        self, session,
        force=False, cached_serverlist=CACHED_SERVERLIST
    ):
        """Cache server data from API.

        Args:
            session (proton.api.Session): current user session
            cached_serverlist (string): path to cached server list
            force (bool): wether refresh interval shuld be ignored or not
        """
        logger.info("Caching servers")
        if not isinstance(cached_serverlist, str):
            err_msg = "Incorrect object type, "
            + "str is expected but got {} instead".format(
                type(cached_serverlist)
            )
            logger.error(
                "[!] TypeError: {}. Raising exception".format(err_msg)
            )
            raise TypeError(err_msg)

        if isinstance(cached_serverlist, str) and len(cached_serverlist) == 0:
            logger.error(
                "[!] FileNotFoundError: \"{}\"".format(cached_serverlist)
            )
            raise FileNotFoundError("No such file exists")

        if os.path.isdir(cached_serverlist):
            logger.error(
                "[!] IsADirectoryError: \"{}\"".format(cached_serverlist)
            )
            raise IsADirectoryError(
                "Provided file path is a directory, while file path expected"
            )

        if not os.path.isdir(PROTON_XDG_CACHE_HOME):
            os.mkdir(PROTON_XDG_CACHE_HOME)

        try:
            last_modified_time = datetime.datetime.fromtimestamp(
                os.path.getmtime(cached_serverlist)
            )
        except FileNotFoundError:
            last_modified_time = datetime.datetime.now()
        except Exception as e:
            capture_exception(e)

        now_time = datetime.datetime.now()
        time_ago = now_time - datetime.timedelta(minutes=self.REFRESH_INTERVAL)

        if (
            not os.path.isfile(cached_serverlist)
        ) or (
            time_ago > last_modified_time or force
        ):

            data = session.api_request(endpoint="/vpn/logicals")

            with open(cached_serverlist, "w") as f:
                json.dump(data, f)

    def generate_ip_list(
        self, servername, servers,
        server_certificate_check=True
    ):
        """Exctract IPs from server list, based on servername.

        Args:
            servername (string): servername [PT#1]
            servers (list): curated list containing the servers
        Returns:
            list: IPs for the selected server
        """
        logger.info("Generating IP list")
        try:
            subservers = self.extract_server_value(
                servername, "Servers", servers
            )
        except IndexError as e:
            logger.info("[!] IndexError: {}".format(e))
            raise IndexError(e)
        except Exception as e:
            capture_exception(e)

        equal_IPs = None
        exit_IP = None
        if server_certificate_check:
            ip_list = [
                (subserver["EntryIP"], subserver["ExitIP"])
                for subserver
                in subservers
                if subserver["Status"] == 1
            ]
            entry_IP, exit_IP = random.choice(ip_list)
            equal_IPs = True if entry_IP == exit_IP else False
        else:
            entry_IP = [
                subserver["EntryIP"]
                for subserver
                in subservers
                if subserver["Status"] == 1
            ]
        return [entry_IP], exit_IP, equal_IPs

    def filter_servers(self, session):
        """Filter servers based on user tier.

        Args:
            session (proton.api.Session): current user session
        Returns:
            list: serverlist extracted from raw json, based on user tier
        """
        logger.info("Filtering servers by tier")
        with open(CACHED_SERVERLIST, "r") as f:
            server_data = json.load(f)

        user_tier = self.fetch_user_tier(session)

        servers = server_data["LogicalServers"]

        # Sort server IDs by Tier
        return [server for server in servers if server["Tier"] <= user_tier and server["Status"] == 1] # noqa

    def fetch_user_tier(self, session):
        """Fetches a users tier from the API.

        Args:
            session (proton.api.Session): current user session
        Returns:
            int: current user session tier
        """
        data = session.api_request(endpoint="/vpn")
        return data["VPN"]["MaxTier"]

    def get_fastest_server(self, server_pool):
        """Get fastest server from a list of servers.

        Args:
            server_pool (list): pool with servers
        Returns:
            string: servername with the highest score (fastest)
        """
        logger.info("Getting fastest server")
        if not isinstance(server_pool, list):
            err_msg = "Incorrect object type, "
            + "list is expected but got {} instead".format(
                type(server_pool)
            )
            logger.error(
                "[!] TypeError: {}. Raising exception.".format(err_msg)
            )
            raise TypeError(err_msg)

        # Sort servers by "speed" and select top n according to pool_size
        fastest_pool = sorted(
            server_pool, key=lambda server: server["Score"]
        )
        if len(fastest_pool) >= 50:
            pool_size = 4
        else:
            pool_size = 1

        random_choice = random.choice(fastest_pool[:pool_size])
        fastest_server_name = random_choice["Name"]
        fastest_server_domain = random_choice["Domain"]

        return fastest_server_name, fastest_server_domain

    def extract_server_value(self, servername, key, servers):
        """Extract server data based on servername.

        Args:
            servername (string): servername [PT#1]
            key (string): keyword that contains servernames in json
            servers (list): a list containing the servers
        Returns:
            list: dict with server information
        """
        value = [
            server[key] for server
            in servers if
            server['Name'] == servername
        ]
        return value[0]

    def extract_country_name(self, code):
        """Extract country name based on specified code.

        Args:
            code (string): country code [PT|SE|CH]
        Returns:
            string:
                country name if found, else returns country code
        """
        from lib.country_codes import country_codes
        return country_codes.get(code, code)

    def is_servername_valid(self, servername):
        """Check if the provided servername is in a valid format.

        Args:
            servername (string): the servername [SE-PT#1]
        Returns:
            bool
        """
        logger.info("Validating servername")
        if not isinstance(servername, str):
            err_msg = "Incorrect object type, "
            + "str is expected but got {} instead".format(type(servername))
            logger.error(
                "[!] TypeError: {}. Raising Exception.".format(err_msg)
            )
            raise TypeError(err_msg)

        re_short = re.compile(r"^((\w\w)(-|#)?(\d{1,3})-?(TOR)?)$")
        # For long format (IS-DE-01 | Secure-Core/Free/US Servers)
        re_long = re.compile(
            r"^(((\w\w)(-|#)?([A-Z]{2}|FREE))(-|#)?(\d{1,3})-?(TOR)?)$"
        )
        return_servername = False

        if re_short.search(servername):
            user_server = re_short.search(servername)

            country_code = user_server.group(2)
            number = user_server.group(4).lstrip("0")
            tor = user_server.group(5)
            servername = "{0}#{1}".format(country_code, number)
            return_servername = servername + "{0}".format(
                '-' + tor if tor is not None else ''
            )

        elif re_long.search(servername):
            user_server = re_long.search(servername)
            country_code = user_server.group(3)
            country_code2 = user_server.group(5)
            number = user_server.group(7).lstrip("0")
            tor = user_server.group(8)
            return_servername = "{0}-{1}#{2}".format(
                country_code, country_code2, number
            ) + "{0}".format(
                '-' + tor if tor is not None else ''
            )

        return False if not return_servername else True
