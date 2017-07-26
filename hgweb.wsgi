import hmac
import os

import requests

# enable demandloading to reduce startup time
from mercurial import demandimport
demandimport.enable()
from mercurial.hgweb import hgweb  # noqa

# Path to repo or hgweb config to serve (see 'hg help hgweb')
config = "/app/hgweb.config"

PHABRICATOR_URL = os.environ.get('PHABRICATOR_URL',
                                 'https://mozphab.dev.mozaws.net').rstrip('/')


class PhabricatorAuth(object):
    """WSGI app wrapper to add phabricator api-key authentication."""

    def __init__(self, app):
        self._app = app
        self._whoamiurl = PHABRICATOR_URL + '/api/user.whoami'

    def __call__(self, environ, start_response):
        try:
            if self._need_auth(environ) and not self._authenticated(environ):
                return self._login(environ, start_response)
        except:
            return self._server_error(environ, start_response)

        return self._app(environ, start_response)

    def _need_auth(self, environ):
        """Return boolean indicating if auth is required for this request.

        Mercurial performs all mutations on the not safe HTTP methods. We want
        anonymous users to be able to use the server. So don't require auth for
        GET and HEAD methods.
        """
        method = environ.get('REQUEST_METHOD')
        return method not in ('GET', 'HEAD')

    def _authenticated(self, environ):
        """Return boolean indicating if the request is authenticated."""
        username, apikey = self._auth_credentials(environ)
        if not username or not apikey:
            return False

        return self._phabricator_authenticate(username, apikey)

    def _auth_credentials(self, environ):
        """Return a tuple of auth credentials (username, apikey)."""
        auth_header = environ.get('HTTP_AUTHORIZATION')
        if not auth_header:
            return None, None

        from base64 import b64decode
        try:
            _, b64credentials = auth_header.split(None, 1)
            credentials = b64decode(b64credentials).decode('utf-8')
            username, apikey = credentials.split(':', 1)
        except:
            return None, None

        return username, apikey

    def _phabricator_authenticate(self, username, apikey):
        """Return True if apikey authenticates with phabricator."""
        response = requests.request(
            method='GET', url=self._whoamiurl, data={
                'api.token': apikey,
            }).json()

        if response['error_code']:
            # Assume any error returned by phabricator means
            # we failed to authenticate.
            return False

        # TODO: We might need to check the roles returned by phabricator
        # to ensure the account is active and in good standing.
        return hmac.compare_digest(response['result']['userName'], username)

    def _server_error(self, environ, start_response):
        start_response('500 Internal Server Error', [
            ('Content-Type', 'text/html'),
        ])
        return ['500 Internal Server Error']

    def _login(self, environ, start_response):
        start_response('401 Authentication Required', [
            ('Content-Type', 'text/html'),
            ('WWW-Authenticate',
             'Basic realm="{} username and API key"'.format(PHABRICATOR_URL))
        ])
        return ['401 Authentication Required']


application = PhabricatorAuth(hgweb(config))
