from nose.tools import set_trace
import logging
import base64
import json
import os
import datetime
from flask_babel import lazy_gettext as _

from core.util.problem_detail import ProblemDetail

from api.authenticator import (
    OAuthAuthenticationProvider,
    OAuthController,
    PatronData,
)
from api.config import Configuration
from core.model import (
    get_one,
    get_one_or_create,
    Credential,
    DataSource,
    ExternalIntegration,
    Patron,
)
from core.util.http import HTTP
from api.problem_details import *


UNSUPPORTED_CLEVER_USER_TYPE = pd(
    "http://librarysimplified.org/terms/problem/unsupported-clever-user-type",
    401,
    _("Your Clever user type is not supported."),
    _("Your Clever user type is not supported. You can request a code from First Book instead"),
)

CLEVER_NOT_ELIGIBLE = pd(
    "http://librarysimplified.org/terms/problem/clever-not-eligible",
    401,
    _("Your Clever account is not eligible to access this application."),
    _("Your Clever account is not eligible to access this application."),
)


# Load Title I NCES ID data from json.
TITLE_I_NCES_IDS = None
clever_dir = os.path.split(__file__)[0]

with open('%s/title_i.json' % clever_dir) as f:
    json_data = f.read()
    TITLE_I_NCES_IDS = json.loads(json_data)


class CleverAuthenticationAPI(OAuthAuthenticationProvider):

    URI = "http://librarysimplified.org/terms/auth/clever"

    NAME = 'Clever'

    DESCRIPTION = _("""
        An authentication service for Open eBooks that uses Clever as an
        OAuth provider.""")

    LOGIN_BUTTON_IMAGE = "CleverLoginButton280.png"

    SETTINGS = [
        { "key": ExternalIntegration.USERNAME, "label": _("Client ID"), "required": True },
        { "key": ExternalIntegration.PASSWORD, "label": _("Client Secret"), "required": True },
    ] + OAuthAuthenticationProvider.SETTINGS

    # Unlike other authentication providers, external type regular expression
    # doesn't make sense for Clever. This removes the LIBRARY_SETTINGS from the
    # parent class.
    LIBRARY_SETTINGS = []

    TOKEN_TYPE = "Clever token"
    TOKEN_DATA_SOURCE_NAME = 'Clever'

    EXTERNAL_AUTHENTICATE_URL = "https://clever.com/oauth/authorize?response_type=code&client_id=%(client_id)s&redirect_uri=%(oauth_callback_url)s&state=%(state)s"
    CLEVER_TOKEN_URL = "https://clever.com/oauth/tokens"
    CLEVER_API_BASE_URL = "https://api.clever.com"

    # To check Title I status we need state, which is associated with
    # a school in Clever's API. Any users at the district-level will
    # need to get a code from First Book instead.
    SUPPORTED_USER_TYPES = ['student', 'teacher']

    # Begin implementations of OAuthAuthenticationProvider abstract
    # methods.

    def oauth_callback(self, _db, code):
        """Verify the incoming parameters with the OAuth provider. Exchange
        the authorization code for an access token. Create or look up
        appropriate database records.

        :param code: The authorization code generated by the
            authorization server, as per section 4.1.2 of RFC 6749. This
            method will exchange the authorization code for an access
            token.

        :return: A ProblemDetail if there's a problem. Otherwise, a
            3-tuple (Credential, Patron, PatronData). The Credential
            contains the access token provided by the OAuth provider. The
            Patron object represents the authenticated Patron, and the
            PatronData object includes information about the patron
            obtained from the OAuth provider which cannot be stored in the
            circulation manager's database, but which should be passed on
            to the client.

        """
        # Ask the OAuth provider to verify the code that was passed
        # in.  This will give us a bearer token we can use to look up
        # detailed patron information.
        token = self.remote_exchange_code_for_bearer_token(_db, code)
        if isinstance(token, ProblemDetail):
            return token

        # Now that we have a bearer token, use it to look up patron
        # information.
        patrondata = self.remote_patron_lookup(token)
        if isinstance(patrondata, ProblemDetail):
            return patrondata

        # Convert the PatronData into a Patron object.
        patron, is_new = patrondata.get_or_create_patron(_db, self.library_id)

        # Create a credential for the Patron.
        credential, is_new = self.create_token(_db, patron, token)
        return credential, patron, patrondata

    # End implementations of OAuthAuthenticationProvider abstract
    # methods.

    def remote_exchange_code_for_bearer_token(self, _db, code):
        """Ask the OAuth provider to convert a code (passed in to the OAuth
        callback) into a bearer token.

        We can use the bearer token to act on behalf of a specific
        patron. It also gives us confidence that the patron
        authenticated correctly with Clever.

        :return: A ProblemDetail if there's a problem; otherwise, the
            bearer token.
        """
        payload = self._remote_exchange_payload(_db, code)
        authorization = base64.b64encode(
            self.client_id + ":" + self.client_secret
        )
        headers = {
            'Authorization': 'Basic %s' % authorization,
            'Content-Type': 'application/json',
        }
        response = self._get_token(payload, headers)
        invalid = INVALID_CREDENTIALS.detailed(
            _("A valid Clever login is required.")
        )
        if not response:
            return invalid
        token = response.get('access_token', None)
        if not token:
            return invalid
        return token

    def _remote_exchange_payload(self, _db, code):
        library = self.library(_db)
        return dict(
            code=code,
            grant_type='authorization_code',
            redirect_uri=OAuthController.oauth_authentication_callback_url(
                library.short_name
            )
        )

    def remote_patron_lookup(self, token):
        """Use a bearer token for a patron to look up that patron's Clever
        record through the Clever API.

        This is the only method that has access to a patron's personal
        information as provided by Clever. Here's an inventory of the
        information we process and what happens to it:

        * The Clever 'id' associated with this patron is passed out of
          this method through the PatronData object, and persisted to
          two database fields: 'patrons.external_identifier' and
          'patrons.authorization_identifier'.

          As far as we know, the Clever ID is an opaque reference
          which uniquely identifies a given patron but contains no
          personal information about them.

        * The patron's personal name is passed out of this method
          through the PatronData object. This information cannot be
          persisted to the server-side database, because there's no
          place to store it. You can verify this by looking at the
          PatronData class in authenticator.py and the Patron class in
          core/model/patron.py.

          Upon login, the patron's personal name is sent via HTTP to
          the authorized client, running on a device being operated by
          the patron. (See the OAuthController.oauth_authentication_callback()
          method for this.) Access to this information is important in an
          environment where devices are shared across a classroom. When
          the patron logs out, the Open eBooks client destroys this
          information.

        * If the patron is a student, their grade level
          ("Kindergarten" through "12") is converted into an Open
          eBooks patron type ("E" for "Early Grades", "M" for "Middle
          Grades", or "H" for "High School"). This is stored in the
          PatronData object returned from this method, and persisted
          to the database field 'patrons.external_type'. If the patron
          is not a student, their Open eBooks patron type is set to
          "A" for "All Access").

          This system does not track a patron's grade level or store
          it in the database. Only the coarser-grained Open eBooks
          patron type is tracked. This is used to show age-appropriate
          books to the patron.

        * The internal Clever ID of the patron's school is used to
          make a _second_ Clever API request to get information about
          the school. From that, we get the school's NCES ID, which we
          cross-check against data we've gathered separately to
          validate the school's Title I status. The school ID and NCES
          ID are not stored in the PatronData object or persisted to
          the database. Any patron who ends up in the database is
          presumed to have passed this check.

        To summarize, an opaque ID associated with the patron is
        persisted to the database, as is a coarse-grained indicator of
        the patron's age. The patron's personal name is available to
        the server for the duration of the current request, but cannot
        be persisted to the database. The patron's personal name is
        made available to the authorized client, which destroys that
        information on logout. No other information about the patron
        makes it out of this method.

        :return: A ProblemDetail if there's a problem. Otherwise, a PatronData
            with the data listed above.
        """
        bearer_headers = {
            'Authorization': 'Bearer %s' % token
        }
        result = self._get(self.CLEVER_API_BASE_URL + '/me', bearer_headers)
        data = result.get('data', {}) or {}

        identifier = data.get('id', None)

        if not identifier:
            return INVALID_CREDENTIALS.detailed(
                _("A valid Clever login is required.")
            )

        if result.get('type') not in self.SUPPORTED_USER_TYPES:
            return UNSUPPORTED_CLEVER_USER_TYPE

        links = result['links']

        user_link = [l for l in links if l['rel'] == 'canonical'][0]['uri']
        user = self._get(self.CLEVER_API_BASE_URL + user_link, bearer_headers)

        user_data = user['data']
        school_id = user_data['school']
        school = self._get(
            self.CLEVER_API_BASE_URL + '/v1.1/schools/%s' % school_id,
            bearer_headers
        )

        school_nces_id = school['data'].get('nces_id')

        # TODO: check student free and reduced lunch status as well

        if school_nces_id not in TITLE_I_NCES_IDS:
            self.log.info("%s didn't match a Title I NCES ID" % school_nces_id)
            return CLEVER_NOT_ELIGIBLE

        if result['type'] == 'student':
            grade = user_data.get('grade')
            external_type = None
            if grade in ["Kindergarten", "1", "2", "3"]:
                external_type = "E"
            elif grade in ["4", "5", "6", "7", "8"]:
                external_type = "M"
            elif grade in ["9", "10", "11", "12"]:
                external_type = "H"
        else:
            external_type = "A"

        patrondata = PatronData(
            permanent_id=identifier,
            authorization_identifier=identifier,
            external_type=external_type,
            personal_name = user_data.get('name'),
            complete=True
        )
        return patrondata

    def _get_token(self, payload, headers):
        response = HTTP.post_with_timeout(
            self.CLEVER_TOKEN_URL, json.dumps(payload), headers=headers
        )
        return response.json()

    def _get(self, url, headers):
        return HTTP.get_with_timeout(url, headers=headers).json()

AuthenticationProvider = CleverAuthenticationAPI
