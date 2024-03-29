import os
from socket import AF_INET, SOCK_STREAM, socket
from typing import Tuple, Union

import pyngrok.conf
import pyngrok.ngrok
import requests
import yaml
from pydantic import HttpUrl
from pyngrok.exception import PyngrokError
from requests.exceptions import ConnectionError, InvalidURL

from . import models

logger = models.ngrok_logger()


# noinspection PyProtectedMember
def get_ngrok(public: bool = True) -> str or None:
    """Identifies if an existing ngrok tunnel by sending a `GET` request to api/tunnels to get the `ngrok` public url.

    Args:
        public: Boolean flag, whether to get the public or private endpoint.

    See Also:
        Checks for output from get_port function. If nothing, then `ngrok` isn't running.
        However, as a sanity check, the script uses port number stored in env var to make a `GET` request.

    Returns:
        str or None:
        - On success, returns the `ngrok` public URL.
        - On failure, returns None to exit function.
    """
    tunnels_url = f'http://{models.config.host}:4040/api/tunnels'
    try:
        logger.info('Looking for existing tunnels at %s', tunnels_url)
        response = requests.get(url=tunnels_url)
    except InvalidURL:
        logger.error('Invalid URL: %s', tunnels_url)
        return
    except ConnectionError:
        logger.error('Connection failed: %s', tunnels_url)
        return
    if not response.ok:
        logger.error('Failed response [%d] from %s', response.status_code, tunnels_url)
        return

    serving_at = yaml.load(response.content.decode(), Loader=yaml.FullLoader).get('tunnels', [{}])[0]

    if public:
        return serving_at.get('public_url')
    else:
        return serving_at.get('config', {}).get('addr')


# noinspection PyProtectedMember
def connect(new_connection: bool = False) -> Union[Tuple[socket, HttpUrl], Tuple[None, None]]:
    """Creates an HTTP socket and uses `pyngrok` module to bind the socket.

    Args:
        new_connection: Takes a boolean flag whether to spin up a new connection.

    Once the socket is bound, the listener is activated and runs in a forever loop accepting connections.

    See Also:
        Run the following code to setup.

        .. code-block:: python
            :emphasize-lines: 4,7,10

            from pyngrok.conf import PyngrokConfig, get_default
            from pyngrok.ngrok import set_auth_token

            # Sets auth token only during run time without modifying global config.
            PyngrokConfig.auth_token = '<NGROK_AUTH_TOKEN>'

            # Uses auth token from the specified file without modifying global config.
            get_default().config_path = "/path/to/config.yml"

            # Changes auth token at $HOME/.ngrok2/ngrok.yml
            set_auth_token('<NGROK_AUTH_TOKEN>')

    Returns:
        Tuple[socket, HttpUrl]:
        A tuple of the connected socket and the public URL.
    """
    if (local_host := get_ngrok(public=False)) and local_host.endswith(str(models.env.port)):
        logger.error('Ngrok tunnel is already running on %s', local_host)
        return None, None

    sock = socket(AF_INET, SOCK_STREAM)

    if new_connection:
        # Uncomment bind to create a whole new connection to the port
        server_address = (models.config.host, models.env.port)  # Bind a local socket to the port
        sock.bind(server_address)  # Bind only accepts tuples

    sock.listen(1)

    if models.env.ngrok_auth:
        logger.info('Using env var to set ngrok auth.')
        pyngrok.ngrok.set_auth_token(models.env.ngrok_auth)
    elif os.path.isfile('ngrok.yml'):
        logger.info('Using config file for ngrok auth')
        pyngrok.conf.get_default().config_path = 'ngrok.yml'
    else:
        logger.warning('Neither config file nor env var for ngrok auth was found.')
        return None, None

    try:
        endpoint = pyngrok.ngrok.connect(models.env.port, "http",
                                         options={"remote_addr": f"{models.config.host}:{models.env.port}"})
        endpoint = endpoint.public_url.replace('http', 'https')
        logger.info('Ngrok connection has been established at %s', endpoint)
        return sock, endpoint
    except PyngrokError as err:
        logger.error(err)
        return None, None


def tunnel(sock: socket) -> None:
    """Initiates tunneling in a never ending loop.

    Args:
        sock: Takes the connected socket as an argument.
    """
    connection = None
    while True:
        try:
            logger.info("Waiting for a connection")
            connection, client_address = sock.accept()
            logger.info("Connection established from %s", client_address)
        except KeyboardInterrupt:
            break

    logger.info("Shutting down socket connection")
    if connection:
        connection.close()
    pyngrok.ngrok.kill(pyngrok_config=None)  # uses default config when None is passed
    sock.close()
