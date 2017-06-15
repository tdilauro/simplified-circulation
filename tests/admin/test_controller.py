from nose.tools import (
    set_trace,
    eq_,
)
import flask
import json
import feedparser
from werkzeug import ImmutableMultiDict, MultiDict

from ..test_controller import CirculationControllerTest
from api.admin.controller import setup_admin_controllers, AdminAnnotator
from api.admin.problem_details import *
from api.config import (
    Configuration,
    temp_config,
)
from core.model import (
    Admin,
    CirculationEvent,
    Classification,
    Collection,
    Complaint,
    ConfigurationSetting,
    CoverageRecord,
    create,
    DataSource,
    Edition,
    ExternalIntegration,
    Genre,
    get_one,
    get_one_or_create,
    Identifier,
    Library,
    SessionManager,
    Subject,
    WorkGenre
)
from core.testing import (
    AlwaysSuccessfulCoverageProvider,
    NeverSuccessfulCoverageProvider,
)
from core.classifier import (
    genres,
    SimplifiedGenreClassifier
)
from core.opds import AcquisitionFeed
from datetime import date, datetime, timedelta

from api.authenticator import AuthenticationProvider, BasicAuthenticationProvider
from api.simple_authentication import SimpleAuthenticationProvider
from api.millenium_patron import MilleniumPatronAPI
from api.sip import SIP2AuthenticationProvider
from api.firstbook import FirstBookAuthenticationAPI
from api.clever import CleverAuthenticationAPI


class AdminControllerTest(CirculationControllerTest):

    def setup(self):
        super(AdminControllerTest, self).setup()
        ConfigurationSetting.sitewide(self._db, Configuration.SECRET_KEY).value = "a secret"
        setup_admin_controllers(self.manager)

class TestWorkController(AdminControllerTest):

    def test_details(self):
        [lp] = self.english_1.license_pools

        lp.suppressed = False
        with self.request_context_with_library("/"):
            response = self.manager.admin_work_controller.details(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(200, response.status_code)
            feed = feedparser.parse(response.get_data())
            [entry] = feed['entries']
            suppress_links = [x['href'] for x in entry['links']
                              if x['rel'] == "http://librarysimplified.org/terms/rel/hide"]
            unsuppress_links = [x['href'] for x in entry['links']
                                if x['rel'] == "http://librarysimplified.org/terms/rel/restore"]
            eq_(0, len(unsuppress_links))
            eq_(1, len(suppress_links))
            assert lp.identifier.identifier in suppress_links[0]

        lp.suppressed = True
        with self.request_context_with_library("/"):
            response = self.manager.admin_work_controller.details(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(200, response.status_code)
            feed = feedparser.parse(response.get_data())
            [entry] = feed['entries']
            suppress_links = [x['href'] for x in entry['links']
                              if x['rel'] == "http://librarysimplified.org/terms/rel/hide"]
            unsuppress_links = [x['href'] for x in entry['links']
                                if x['rel'] == "http://librarysimplified.org/terms/rel/restore"]
            eq_(0, len(suppress_links))
            eq_(1, len(unsuppress_links))
            assert lp.identifier.identifier in unsuppress_links[0]

    def test_edit(self):
        [lp] = self.english_1.license_pools

        staff_data_source = DataSource.lookup(self._db, DataSource.LIBRARY_STAFF)
        def staff_edition_count():
            return self._db.query(Edition) \
                .filter(
                    Edition.data_source == staff_data_source, 
                    Edition.primary_identifier_id == self.english_1.presentation_edition.primary_identifier.id
                ) \
                .count()

        with self.request_context_with_library("/"):
            flask.request.form = ImmutableMultiDict([
                ("title", "New title"),
                ("subtitle", "New subtitle"),
                ("series", "New series"),
                ("series_position", "144"),
                ("summary", "<p>New summary</p>")
            ])
            response = self.manager.admin_work_controller.edit(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(200, response.status_code)
            eq_("New title", self.english_1.title)
            assert "New title" in self.english_1.simple_opds_entry
            eq_("New subtitle", self.english_1.subtitle)
            assert "New subtitle" in self.english_1.simple_opds_entry
            eq_("New series", self.english_1.series)
            assert "New series" in self.english_1.simple_opds_entry
            eq_(144, self.english_1.series_position)
            assert "144" in self.english_1.simple_opds_entry
            eq_("<p>New summary</p>", self.english_1.summary_text)
            assert "&lt;p&gt;New summary&lt;/p&gt;" in self.english_1.simple_opds_entry
            eq_(1, staff_edition_count())

        with self.request_context_with_library("/"):
            # Change the summary again
            flask.request.form = ImmutableMultiDict([
                ("title", "New title"),
                ("subtitle", "New subtitle"),
                ("series", "New series"),
                ("series_position", "144"),
                ("summary", "abcd")
            ])
            response = self.manager.admin_work_controller.edit(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(200, response.status_code)
            eq_("abcd", self.english_1.summary_text)
            assert 'New summary' not in self.english_1.simple_opds_entry
            eq_(1, staff_edition_count())

        with self.request_context_with_library("/"):
            # Now delete the subtitle and series and summary entirely
            flask.request.form = ImmutableMultiDict([
                ("title", "New title"),
                ("subtitle", ""),
                ("series", ""),
                ("series_position", ""),
                ("summary", "")
            ])
            response = self.manager.admin_work_controller.edit(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(200, response.status_code)
            eq_(None, self.english_1.subtitle)
            eq_(None, self.english_1.series)
            eq_(None, self.english_1.series_position)
            eq_("", self.english_1.summary_text)
            assert 'New subtitle' not in self.english_1.simple_opds_entry
            assert 'New series' not in self.english_1.simple_opds_entry
            assert '144' not in self.english_1.simple_opds_entry
            assert 'abcd' not in self.english_1.simple_opds_entry
            eq_(1, staff_edition_count())

        with self.request_context_with_library("/"):
            # Set the fields one more time
            flask.request.form = ImmutableMultiDict([
                ("title", "New title"),
                ("subtitle", "Final subtitle"),
                ("series", "Final series"),
                ("series_position", "169"),
                ("summary", "<p>Final summary</p>")
            ])
            response = self.manager.admin_work_controller.edit(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(200, response.status_code)
            eq_("Final subtitle", self.english_1.subtitle)
            eq_("Final series", self.english_1.series)
            eq_(169, self.english_1.series_position)
            eq_("<p>Final summary</p>", self.english_1.summary_text)
            assert 'Final subtitle' in self.english_1.simple_opds_entry
            assert 'Final series' in self.english_1.simple_opds_entry
            assert '169' in self.english_1.simple_opds_entry
            assert "&lt;p&gt;Final summary&lt;/p&gt;" in self.english_1.simple_opds_entry
            eq_(1, staff_edition_count())

        with self.request_context_with_library("/"):
            # Set the series position to a non-numerical value
            flask.request.form = ImmutableMultiDict([
                ("title", "New title"),
                ("subtitle", "Final subtitle"),
                ("series", "Final series"),
                ("series_position", "abc"),
                ("summary", "<p>Final summary</p>")
            ])
            response = self.manager.admin_work_controller.edit(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(400, response.status_code)
            eq_(169, self.english_1.series_position)

    def test_edit_classifications(self):
        # start with a couple genres based on BISAC classifications from Axis 360
        work = self.english_1
        [lp] = work.license_pools
        primary_identifier = work.presentation_edition.primary_identifier
        work.audience = "Adult"
        work.fiction = True
        axis_360 = DataSource.lookup(self._db, DataSource.AXIS_360)
        classification1 = primary_identifier.classify(
            data_source=axis_360,
            subject_type=Subject.BISAC,
            subject_identifier="FICTION / Horror",
            weight=1
        )
        classification2 = primary_identifier.classify(
            data_source=axis_360,
            subject_type=Subject.BISAC,
            subject_identifier="FICTION / Science Fiction / Time Travel",
            weight=1
        )
        genre1, ignore = Genre.lookup(self._db, "Horror")
        genre2, ignore = Genre.lookup(self._db, "Science Fiction")
        work.genres = [genre1, genre2]

        # make no changes
        with self.request_context_with_library("/"):
            flask.request.form = MultiDict([
                ("audience", "Adult"),
                ("fiction", "fiction"),
                ("genres", "Horror"),
                ("genres", "Science Fiction")
            ])
            requested_genres = flask.request.form.getlist("genres")
            response = self.manager.admin_work_controller.edit_classifications(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(response.status_code, 200)

        staff_data_source = DataSource.lookup(self._db, DataSource.LIBRARY_STAFF)
        genre_classifications = self._db \
            .query(Classification) \
            .join(Subject) \
            .filter(
                Classification.identifier == primary_identifier,
                Classification.data_source == staff_data_source,
                Subject.genre_id != None
            )
        staff_genres = [
            c.subject.genre.name 
            for c in genre_classifications 
            if c.subject.genre
        ]
        eq_(staff_genres, [])
        eq_("Adult", work.audience)
        eq_(18, work.target_age.lower)
        eq_(None, work.target_age.upper)
        eq_(True, work.fiction)

        # remove all genres
        with self.request_context_with_library("/"):
            flask.request.form = MultiDict([
                ("audience", "Adult"),
                ("fiction", "fiction")
            ])
            response = self.manager.admin_work_controller.edit_classifications(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(response.status_code, 200)

        primary_identifier = work.presentation_edition.primary_identifier
        staff_data_source = DataSource.lookup(self._db, DataSource.LIBRARY_STAFF)
        none_classification_count = self._db \
            .query(Classification) \
            .join(Subject) \
            .filter(
                Classification.identifier == primary_identifier,
                Classification.data_source == staff_data_source,
                Subject.identifier == SimplifiedGenreClassifier.NONE
            ) \
            .all()
        eq_(1, len(none_classification_count))
        eq_("Adult", work.audience)
        eq_(18, work.target_age.lower)
        eq_(None, work.target_age.upper)
        eq_(True, work.fiction)

        # completely change genres
        with self.request_context_with_library("/"):
            flask.request.form = MultiDict([
                ("audience", "Adult"),
                ("fiction", "fiction"),
                ("genres", "Drama"),
                ("genres", "Urban Fantasy"),
                ("genres", "Women's Fiction")
            ])
            requested_genres = flask.request.form.getlist("genres")
            response = self.manager.admin_work_controller.edit_classifications(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(response.status_code, 200)
            
        new_genre_names = [work_genre.genre.name for work_genre in work.work_genres]
        eq_(sorted(new_genre_names), sorted(requested_genres))
        eq_("Adult", work.audience)
        eq_(18, work.target_age.lower)
        eq_(None, work.target_age.upper)
        eq_(True, work.fiction)

        # remove some genres and change audience and target age
        with self.request_context_with_library("/"):
            flask.request.form = MultiDict([
                ("audience", "Young Adult"),
                ("target_age_min", 16),
                ("target_age_max", 18),
                ("fiction", "fiction"),
                ("genres", "Urban Fantasy")
            ])
            requested_genres = flask.request.form.getlist("genres")
            response = self.manager.admin_work_controller.edit_classifications(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(response.status_code, 200)

        # new_genre_names = self._db.query(WorkGenre).filter(WorkGenre.work_id == work.id).all()
        new_genre_names = [work_genre.genre.name for work_genre in work.work_genres]
        eq_(sorted(new_genre_names), sorted(requested_genres))
        eq_("Young Adult", work.audience)
        eq_(16, work.target_age.lower)
        eq_(19, work.target_age.upper)
        eq_(True, work.fiction)

        previous_genres = new_genre_names

        # try to add a nonfiction genre
        with self.request_context_with_library("/"):
            flask.request.form = MultiDict([
                ("audience", "Young Adult"),
                ("target_age_min", 16),
                ("target_age_max", 18),
                ("fiction", "fiction"),
                ("genres", "Cooking"),
                ("genres", "Urban Fantasy")
            ])
            response = self.manager.admin_work_controller.edit_classifications(
                lp.identifier.type, lp.identifier.identifier
            )

        eq_(response, INCOMPATIBLE_GENRE)
        new_genre_names = [work_genre.genre.name for work_genre in work.work_genres]
        eq_(sorted(new_genre_names), sorted(previous_genres))
        eq_("Young Adult", work.audience)
        eq_(16, work.target_age.lower)
        eq_(19, work.target_age.upper)
        eq_(True, work.fiction)

        # try to add Erotica
        with self.request_context_with_library("/"):
            flask.request.form = MultiDict([
                ("audience", "Young Adult"),
                ("target_age_min", 16),
                ("target_age_max", 18),
                ("fiction", "fiction"),
                ("genres", "Erotica"),
                ("genres", "Urban Fantasy")
            ])
            response = self.manager.admin_work_controller.edit_classifications(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(response, EROTICA_FOR_ADULTS_ONLY)

        new_genre_names = [work_genre.genre.name for work_genre in work.work_genres]
        eq_(sorted(new_genre_names), sorted(previous_genres))
        eq_("Young Adult", work.audience)
        eq_(16, work.target_age.lower)
        eq_(19, work.target_age.upper)
        eq_(True, work.fiction)

        # try to set min target age greater than max target age
        # othe edits should not go through
        with self.request_context_with_library("/"):
            flask.request.form = MultiDict([
                ("audience", "Young Adult"),
                ("target_age_min", 16),
                ("target_age_max", 14),
                ("fiction", "nonfiction"),
                ("genres", "Cooking")
            ])
            response = self.manager.admin_work_controller.edit_classifications(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(400, response.status_code)
            eq_(INVALID_EDIT.uri, response.uri)

        new_genre_names = [work_genre.genre.name for work_genre in work.work_genres]
        eq_(sorted(new_genre_names), sorted(previous_genres))
        eq_(True, work.fiction)        

        # change to nonfiction with nonfiction genres and new target age
        with self.request_context_with_library("/"):
            flask.request.form = MultiDict([
                ("audience", "Young Adult"),
                ("target_age_min", 15),
                ("target_age_max", 17),
                ("fiction", "nonfiction"),
                ("genres", "Cooking")
            ])
            requested_genres = flask.request.form.getlist("genres")
            response = self.manager.admin_work_controller.edit_classifications(
                lp.identifier.type, lp.identifier.identifier
            )

        new_genre_names = [work_genre.genre.name for work_genre in lp.work.work_genres]
        eq_(sorted(new_genre_names), sorted(requested_genres))
        eq_("Young Adult", work.audience)
        eq_(15, work.target_age.lower)
        eq_(18, work.target_age.upper)
        eq_(False, work.fiction)

        # set to Adult and make sure that target ages is set automatically
        with self.request_context_with_library("/"):
            flask.request.form = MultiDict([
                ("audience", "Adult"),
                ("fiction", "nonfiction"),
                ("genres", "Cooking")
            ])
            requested_genres = flask.request.form.getlist("genres")
            response = self.manager.admin_work_controller.edit_classifications(
                lp.identifier.type, lp.identifier.identifier
            )

        eq_("Adult", work.audience)
        eq_(18, work.target_age.lower)
        eq_(None, work.target_age.upper)

    def test_suppress(self):
        [lp] = self.english_1.license_pools

        with self.request_context_with_library("/"):
            response = self.manager.admin_work_controller.suppress(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(200, response.status_code)
            eq_(True, lp.suppressed)

    def test_unsuppress(self):
        [lp] = self.english_1.license_pools
        lp.suppressed = True

        broken_lp = self._licensepool(
            self.english_1.presentation_edition,
            data_source_name=DataSource.OVERDRIVE
        )
        broken_lp.work = self.english_1
        broken_lp.suppressed = True

        # The broken LicensePool doesn't render properly.
        Complaint.register(
            broken_lp,
            "http://librarysimplified.org/terms/problem/cannot-render",
            "blah", "blah"
        )

        with self.request_context_with_library("/"):
            response = self.manager.admin_work_controller.unsuppress(
                lp.identifier.type, lp.identifier.identifier
            )

            # Both LicensePools are unsuppressed, even though one of them
            # has a LicensePool-specific complaint.            
            eq_(200, response.status_code)
            eq_(False, lp.suppressed)
            eq_(False, broken_lp.suppressed)

    def test_refresh_metadata(self):
        wrangler = DataSource.lookup(self._db, DataSource.METADATA_WRANGLER)

        class AlwaysSuccessfulMetadataProvider(AlwaysSuccessfulCoverageProvider):
            DATA_SOURCE_NAME = wrangler.name
        success_provider = AlwaysSuccessfulMetadataProvider(self._db)

        class NeverSuccessfulMetadataProvider(NeverSuccessfulCoverageProvider):
            DATA_SOURCE_NAME = wrangler.name
        failure_provider = NeverSuccessfulMetadataProvider(self._db)

        with self.request_context_with_library('/'):
            [lp] = self.english_1.license_pools
            response = self.manager.admin_work_controller.refresh_metadata(
                lp.identifier.type, lp.identifier.identifier, provider=success_provider
            )
            eq_(200, response.status_code)
            # Also, the work has a coverage record now for the wrangler.
            assert CoverageRecord.lookup(lp.identifier, wrangler)

            response = self.manager.admin_work_controller.refresh_metadata(
                lp.identifier.type, lp.identifier.identifier, provider=failure_provider
            )
            eq_(METADATA_REFRESH_FAILURE.status_code, response.status_code)
            eq_(METADATA_REFRESH_FAILURE.detail, response.detail)

    def test_complaints(self):
        type = iter(Complaint.VALID_TYPES)
        type1 = next(type)
        type2 = next(type)

        work = self._work(
            "fiction work with complaint",
            language="eng",
            fiction=True,
            with_open_access_download=True)
        complaint1 = self._complaint(
            work.license_pools[0],
            type1,
            "complaint1 source",
            "complaint1 detail")
        complaint2 = self._complaint(
            work.license_pools[0],
            type1,
            "complaint2 source",
            "complaint2 detail")
        complaint3 = self._complaint(
            work.license_pools[0],
            type2,
            "complaint3 source",
            "complaint3 detail")

        SessionManager.refresh_materialized_views(self._db)
        [lp] = work.license_pools

        with self.request_context_with_library("/"):
            response = self.manager.admin_work_controller.complaints(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(response['book']['identifier_type'], lp.identifier.type)
            eq_(response['book']['identifier'], lp.identifier.identifier)
            eq_(response['complaints'][type1], 2)
            eq_(response['complaints'][type2], 1)

    def test_resolve_complaints(self):
        type = iter(Complaint.VALID_TYPES)
        type1 = next(type)
        type2 = next(type)

        work = self._work(
            "fiction work with complaint",
            language="eng",
            fiction=True,
            with_open_access_download=True)
        complaint1 = self._complaint(
            work.license_pools[0],
            type1,
            "complaint1 source",
            "complaint1 detail")
        complaint2 = self._complaint(
            work.license_pools[0],
            type1,
            "complaint2 source",
            "complaint2 detail")
        
        SessionManager.refresh_materialized_views(self._db)
        [lp] = work.license_pools

        # first attempt to resolve complaints of the wrong type
        with self.request_context_with_library("/"):
            flask.request.form = ImmutableMultiDict([("type", type2)])
            response = self.manager.admin_work_controller.resolve_complaints(
                lp.identifier.type, lp.identifier.identifier
            )
            unresolved_complaints = [complaint for complaint in lp.complaints if complaint.resolved == None]
            eq_(response.status_code, 404)
            eq_(len(unresolved_complaints), 2)

        # then attempt to resolve complaints of the correct type
        with self.request_context_with_library("/"):
            flask.request.form = ImmutableMultiDict([("type", type1)])
            response = self.manager.admin_work_controller.resolve_complaints(
                lp.identifier.type, lp.identifier.identifier
            )
            unresolved_complaints = [complaint for complaint in lp.complaints
                                               if complaint.resolved == None]
            eq_(response.status_code, 200)
            eq_(len(unresolved_complaints), 0)

        # then attempt to resolve the already-resolved complaints of the correct type
        with self.request_context_with_library("/"):
            flask.request.form = ImmutableMultiDict([("type", type1)])
            response = self.manager.admin_work_controller.resolve_complaints(
                lp.identifier.type, lp.identifier.identifier
            )
            eq_(response.status_code, 409)

    def test_classifications(self):
        e, pool = self._edition(with_license_pool=True)
        work = self._work(presentation_edition=e)
        identifier = work.presentation_edition.primary_identifier
        genres = self._db.query(Genre).all()
        subject1 = self._subject(type="type1", identifier="subject1")
        subject1.genre = genres[0]
        subject2 = self._subject(type="type2", identifier="subject2")
        subject2.genre = genres[1]
        subject3 = self._subject(type="type2", identifier="subject3")
        subject3.genre = None
        source = DataSource.lookup(self._db, DataSource.AXIS_360)
        classification1 = self._classification(
            identifier=identifier, subject=subject1, 
            data_source=source, weight=1)
        classification2 = self._classification(
            identifier=identifier, subject=subject2, 
            data_source=source, weight=3)
        classification3 = self._classification(
            identifier=identifier, subject=subject3, 
            data_source=source, weight=2)

        SessionManager.refresh_materialized_views(self._db)
        [lp] = work.license_pools

        with self.request_context_with_library("/"):
            response = self.manager.admin_work_controller.classifications(
                lp.identifier.type, lp.identifier.identifier)
            eq_(response['book']['identifier_type'], lp.identifier.type)
            eq_(response['book']['identifier'], lp.identifier.identifier)

            expected_results = [classification2, classification3, classification1]
            eq_(len(response['classifications']), len(expected_results))            
            for i, classification in enumerate(expected_results):
                subject = classification.subject
                source = classification.data_source
                eq_(response['classifications'][i]['name'], subject.identifier)
                eq_(response['classifications'][i]['type'], subject.type)
                eq_(response['classifications'][i]['source'], source.name)
                eq_(response['classifications'][i]['weight'], classification.weight)


class TestSignInController(AdminControllerTest):

    def setup(self):
        super(TestSignInController, self).setup()
        self.admin, ignore = create(
            self._db, Admin, email=u'example@nypl.org',
            credential=json.dumps({
                u'access_token': u'abc123',
                u'client_id': u'', u'client_secret': u'',
                u'refresh_token': u'', u'token_expiry': u'', u'token_uri': u'',
                u'user_agent': u'', u'invalid': u''
            })
        )

    def test_authenticated_admin_from_request(self):
        # Returns an error if there's no admin auth service.
        with self.app.test_request_context('/admin'):
            flask.session['admin_email'] = self.admin.email
            response = self.manager.admin_sign_in_controller.authenticated_admin_from_request()
            eq_(ADMIN_AUTH_NOT_CONFIGURED, response)

        # Works once the admin auth service exists.
        create(
            self._db, ExternalIntegration,
            protocol=ExternalIntegration.GOOGLE_OAUTH,
            goal=ExternalIntegration.ADMIN_AUTH_GOAL
        )
        with self.app.test_request_context('/admin'):
            flask.session['admin_email'] = self.admin.email
            response = self.manager.admin_sign_in_controller.authenticated_admin_from_request()
            eq_(self.admin, response)

        # Returns an error if you aren't authenticated.
        with self.app.test_request_context('/admin'):
            # You get back a problem detail when you're not authenticated.
            response = self.manager.admin_sign_in_controller.authenticated_admin_from_request()
            eq_(401, response.status_code)
            eq_(INVALID_ADMIN_CREDENTIALS.detail, response.detail)

    def test_authenticated_admin(self):
        # Creates a new admin with fresh details.
        new_admin_details = {
            'email' : u'admin@nypl.org',
            'credentials' : u'gnarly',
        }
        with self.app.test_request_context('/admin/sign_in?redirect=foo'):
            admin = self.manager.admin_sign_in_controller.authenticated_admin(new_admin_details)
            eq_('admin@nypl.org', admin.email)
            eq_('gnarly', admin.credential)

            # Also sets up the admin's flask session.
            eq_("admin@nypl.org", flask.session["admin_email"])
            eq_(True, flask.session.permanent)

        # Or overwrites credentials for an existing admin.
        existing_admin_details = {
            'email' : u'example@nypl.org',
            'credentials' : u'b-a-n-a-n-a-s',
        }
        with self.app.test_request_context('/admin/sign_in?redirect=foo'):
            admin = self.manager.admin_sign_in_controller.authenticated_admin(existing_admin_details)
            eq_(self.admin.id, admin.id)
            eq_('b-a-n-a-n-a-s', self.admin.credential)

    def test_admin_signin(self):
        # Returns an error if there's no admin auth service.
        with self.app.test_request_context('/admin/sign_in?redirect=foo'):
            response = self.manager.admin_sign_in_controller.sign_in()
            eq_(ADMIN_AUTH_NOT_CONFIGURED, response)

        create(
            self._db, ExternalIntegration,
            protocol=ExternalIntegration.GOOGLE_OAUTH,
            goal=ExternalIntegration.ADMIN_AUTH_GOAL
        )

        # Redirects to the auth service's login page if there's an auth service
        # but no signed in admin.
        with self.app.test_request_context('/admin/sign_in?redirect=foo'):
            response = self.manager.admin_sign_in_controller.sign_in()
            eq_(302, response.status_code)
            eq_("GOOGLE REDIRECT", response.headers["Location"])

        # Redirects to the redirect parameter if an admin is signed in.
        with self.app.test_request_context('/admin/sign_in?redirect=foo'):
            flask.session['admin_email'] = self.admin.email
            response = self.manager.admin_sign_in_controller.sign_in()
            eq_(302, response.status_code)
            eq_("foo", response.headers["Location"])

    def test_redirect_after_google_sign_in(self):
        # Returns an error if there's no admin auth service.
        with self.app.test_request_context('/admin/GoogleOAuth/callback'):
            response = self.manager.admin_sign_in_controller.redirect_after_google_sign_in()
            eq_(ADMIN_AUTH_NOT_CONFIGURED, response)

        # Returns an error if the admin auth service isn't google.
        admin, ignore = create(self._db, Admin, email="admin@nypl.org")
        admin.password = "password"
        with self.app.test_request_context('/admin/GoogleOAuth/callback'):
            response = self.manager.admin_sign_in_controller.redirect_after_google_sign_in()
            eq_(ADMIN_AUTH_MECHANISM_NOT_CONFIGURED, response)

        self._db.delete(admin)
        auth_integration, ignore = create(
            self._db, ExternalIntegration,
            protocol=ExternalIntegration.GOOGLE_OAUTH,
            goal=ExternalIntegration.ADMIN_AUTH_GOAL
        )

        # Returns an error if google oauth fails..
        with self.app.test_request_context('/admin/GoogleOAuth/callback?error=foo'):
            response = self.manager.admin_sign_in_controller.redirect_after_google_sign_in()
            eq_(400, response.status_code)

        # Returns an error if the admin email isn't a staff email.
        auth_integration.set_setting("domains", json.dumps(["alibrary.org"]))
        with self.app.test_request_context('/admin/GoogleOAuth/callback?code=1234&state=foo'):
            response = self.manager.admin_sign_in_controller.redirect_after_google_sign_in()
            eq_(401, response.status_code)
        
        # Redirects to the state parameter if the admin email is valid.
        auth_integration.set_setting("domains", json.dumps(["nypl.org"]))
        with self.app.test_request_context('/admin/GoogleOAuth/callback?code=1234&state=foo'):
            response = self.manager.admin_sign_in_controller.redirect_after_google_sign_in()
            eq_(302, response.status_code)
            eq_("foo", response.headers["Location"])

    def test_staff_email(self):
        # Returns false if there's no admin auth service.
        with self.app.test_request_context('/admin/sign_in'):
            result = self.manager.admin_sign_in_controller.staff_email("working@alibrary.org")
            eq_(False, result)

        auth_integration, ignore = create(
            self._db, ExternalIntegration,
            protocol=ExternalIntegration.GOOGLE_OAUTH,
            goal=ExternalIntegration.ADMIN_AUTH_GOAL
        )
        auth_integration.set_setting("domains", json.dumps(["alibrary.org"]))

        with self.app.test_request_context('/admin/sign_in'):
            staff_email = self.manager.admin_sign_in_controller.staff_email("working@alibrary.org")
            interloper_email = self.manager.admin_sign_in_controller.staff_email("rando@gmail.com")
            eq_(True, staff_email)
            eq_(False, interloper_email)

    def test_password_sign_in(self):
        # Returns an error if there's no admin auth service and no admins.
        with self.app.test_request_context('/admin/sign_in_with_password'):
            response = self.manager.admin_sign_in_controller.password_sign_in()
            eq_(ADMIN_AUTH_NOT_CONFIGURED, response)

        # Returns an error if the admin auth service isn't password auth.
        auth_integration, ignore = create(
            self._db, ExternalIntegration,
            protocol=ExternalIntegration.GOOGLE_OAUTH,
            goal=ExternalIntegration.ADMIN_AUTH_GOAL
        )
        with self.app.test_request_context('/admin/sign_in_with_password'):
            response = self.manager.admin_sign_in_controller.password_sign_in()
            eq_(ADMIN_AUTH_MECHANISM_NOT_CONFIGURED, response)

        self._db.delete(auth_integration)
        admin, ignore = create(self._db, Admin, email="admin@nypl.org")
        admin.password = "password"

        # Returns a sign in page in response to a GET.
        with self.app.test_request_context('/admin/sign_in_with_password'):
            response = self.manager.admin_sign_in_controller.password_sign_in()
            eq_(200, response.status_code)
            assert "Email" in response.get_data()
            assert "Password" in response.get_data()

        # Returns an error if there's no admin with the provided email.
        with self.app.test_request_context('/admin/sign_in_with_password', method='POST'):
            flask.request.form = MultiDict([
                ("email", "notanadmin@nypl.org"),
                ("password", "password"),
                ("redirect", "foo")
            ])
            response = self.manager.admin_sign_in_controller.password_sign_in()
            eq_(401, response.status_code)

        # Returns an error if the password doesn't match.
        self.admin.password = "password"
        with self.app.test_request_context('/admin/sign_in_with_password', method='POST'):
            flask.request.form = MultiDict([
                ("email", self.admin.email),
                ("password", "notthepassword"),
                ("redirect", "foo")
            ])
            response = self.manager.admin_sign_in_controller.password_sign_in()
            eq_(401, response.status_code)
        
        # Redirects if the admin email/password combination is valid.
        with self.app.test_request_context('/admin/sign_in_with_password', method='POST'):
            flask.request.form = MultiDict([
                ("email", self.admin.email),
                ("password", "password"),
                ("redirect", "foo")
            ])
            response = self.manager.admin_sign_in_controller.password_sign_in()
            eq_(302, response.status_code)
            eq_("foo", response.headers["Location"])


class TestFeedController(AdminControllerTest):

    def test_complaints(self):
        type = iter(Complaint.VALID_TYPES)
        type1 = next(type)
        type2 = next(type)
        
        work1 = self._work(
            "fiction work with complaint 1",
            language="eng",
            fiction=True,
            with_open_access_download=True)
        complaint1 = self._complaint(
            work1.license_pools[0],
            type1,
            "complaint source 1",
            "complaint detail 1")
        complaint2 = self._complaint(
            work1.license_pools[0],
            type2,
            "complaint source 2",
            "complaint detail 2")
        work2 = self._work(
            "nonfiction work with complaint",
            language="eng",
            fiction=False,
            with_open_access_download=True)
        complaint3 = self._complaint(
            work2.license_pools[0],
            type1,
            "complaint source 3",
            "complaint detail 3")

        SessionManager.refresh_materialized_views(self._db)
        with self.request_context_with_library("/"):
            response = self.manager.admin_feed_controller.complaints()
            feed = feedparser.parse(response.data)
            entries = feed['entries']

            eq_(len(entries), 2)

    def test_suppressed(self):
        suppressed_work = self._work(with_open_access_download=True)
        suppressed_work.license_pools[0].suppressed = True

        unsuppressed_work = self._work()

        SessionManager.refresh_materialized_views(self._db)
        with self.request_context_with_library("/"):
            response = self.manager.admin_feed_controller.suppressed()
            feed = feedparser.parse(response.data)
            entries = feed['entries']
            eq_(1, len(entries))
            eq_(suppressed_work.title, entries[0]['title'])

    def test_genres(self):
        with self.app.test_request_context("/"):
            response = self.manager.admin_feed_controller.genres()
            
            for name in genres:
                top = "Fiction" if genres[name].is_fiction else "Nonfiction"
                eq_(response[top][name], dict({
                    "name": name,
                    "parents": [parent.name for parent in genres[name].parents],
                    "subgenres": [subgenre.name for subgenre in genres[name].subgenres]
                }))        

class TestDashboardController(AdminControllerTest):

    def test_circulation_events(self):
        [lp] = self.english_1.license_pools
        patron_id = "patronid"
        types = [
            CirculationEvent.DISTRIBUTOR_CHECKIN,
            CirculationEvent.DISTRIBUTOR_CHECKOUT,
            CirculationEvent.DISTRIBUTOR_HOLD_PLACE,
            CirculationEvent.DISTRIBUTOR_HOLD_RELEASE,
            CirculationEvent.DISTRIBUTOR_TITLE_ADD
        ]
        time = datetime.now() - timedelta(minutes=len(types))
        for type in types:
            get_one_or_create(
                self._db, CirculationEvent,
                license_pool=lp, type=type, start=time, end=time,
                foreign_patron_id=patron_id)
            time += timedelta(minutes=1)

        with self.request_context_with_library("/"):
            response = self.manager.admin_dashboard_controller.circulation_events()
            url = AdminAnnotator(self.manager.circulation, self._default_library).permalink_for(self.english_1, lp, lp.identifier)

        events = response['circulation_events']
        eq_(types[::-1], [event['type'] for event in events])
        eq_([self.english_1.title]*len(types), [event['book']['title'] for event in events])
        eq_([url]*len(types), [event['book']['url'] for event in events])
        eq_([patron_id]*len(types), [event['patron_id'] for event in events])

        # request fewer events
        with self.request_context_with_library("/?num=2"):
            response = self.manager.admin_dashboard_controller.circulation_events()
            url = AdminAnnotator(self.manager.circulation, self._default_library).permalink_for(self.english_1, lp, lp.identifier)

        eq_(2, len(response['circulation_events']))

    def test_bulk_circulation_events(self):
        [lp] = self.english_1.license_pools
        edition = self.english_1.presentation_edition
        identifier = self.english_1.presentation_edition.primary_identifier
        genres = self._db.query(Genre).all()
        get_one_or_create(self._db, WorkGenre, work=self.english_1, genre=genres[0], affinity=0.2)
        get_one_or_create(self._db, WorkGenre, work=self.english_1, genre=genres[1], affinity=0.3)
        get_one_or_create(self._db, WorkGenre, work=self.english_1, genre=genres[2], affinity=0.5)
        ordered_genre_string = ",".join([genres[2].name, genres[1].name, genres[0].name])
        types = [
            CirculationEvent.DISTRIBUTOR_CHECKIN,
            CirculationEvent.DISTRIBUTOR_CHECKOUT,
            CirculationEvent.DISTRIBUTOR_HOLD_PLACE,
            CirculationEvent.DISTRIBUTOR_HOLD_RELEASE,
            CirculationEvent.DISTRIBUTOR_TITLE_ADD
        ]
        num = len(types)
        time = datetime.now() - timedelta(minutes=len(types))
        for type in types:
            get_one_or_create(
                self._db, CirculationEvent,
                license_pool=lp, type=type, start=time, end=time)
            time += timedelta(minutes=1)

        with self.app.test_request_context("/"):
            response, requested_date = self.manager.admin_dashboard_controller.bulk_circulation_events()
        rows = response[1::] # skip header row
        eq_(num, len(rows))
        eq_(types, [row[1] for row in rows])
        eq_([identifier.identifier]*num, [row[2] for row in rows])
        eq_([identifier.type]*num, [row[3] for row in rows])
        eq_([edition.title]*num, [row[4] for row in rows])
        eq_([edition.author]*num, [row[5] for row in rows])
        eq_(["fiction"]*num, [row[6] for row in rows])
        eq_([self.english_1.audience]*num, [row[7] for row in rows])
        eq_([edition.publisher]*num, [row[8] for row in rows])
        eq_([edition.language]*num, [row[9] for row in rows])
        eq_([self.english_1.target_age_string]*num, [row[10] for row in rows])
        eq_([ordered_genre_string]*num, [row[11] for row in rows])

        # use date
        today = date.strftime(date.today() - timedelta(days=1), "%Y-%m-%d")
        with self.app.test_request_context("/?date=%s" % today):
            response, requested_date = self.manager.admin_dashboard_controller.bulk_circulation_events()
        rows = response[1::] # skip header row
        eq_(0, len(rows))

    def test_stats_patrons(self):
        with self.app.test_request_context("/"):

            # At first, there's one patron in the database.
            response = self.manager.admin_dashboard_controller.stats()
            patron_data = response.get('patrons')
            eq_(1, patron_data.get('total'))
            eq_(0, patron_data.get('with_active_loans'))
            eq_(0, patron_data.get('with_active_loans_or_holds'))
            eq_(0, patron_data.get('loans'))
            eq_(0, patron_data.get('holds'))

            edition, pool = self._edition(with_license_pool=True, with_open_access_download=False)
            edition2, open_access_pool = self._edition(with_open_access_download=True)

            # patron1 has a loan.
            patron1 = self._patron()
            pool.loan_to(patron1, end=datetime.now() + timedelta(days=5))

            # patron2 has a hold.
            patron2 = self._patron()
            pool.on_hold_to(patron2)

            # patron3 has an open access loan with no end date, but it doesn't count
            # because we don't know if it is still active.
            patron3 = self._patron()
            open_access_pool.loan_to(patron3)

            response = self.manager.admin_dashboard_controller.stats()
            patron_data = response.get('patrons')
            eq_(4, patron_data.get('total'))
            eq_(1, patron_data.get('with_active_loans'))
            eq_(2, patron_data.get('with_active_loans_or_holds'))
            eq_(1, patron_data.get('loans'))
            eq_(1, patron_data.get('holds'))
            
    def test_stats_inventory(self):
        with self.app.test_request_context("/"):

            # At first, there is 1 open access title in the database,
            # created in CirculationControllerTest.setup.
            response = self.manager.admin_dashboard_controller.stats()
            inventory_data = response.get('inventory')
            eq_(1, inventory_data.get('titles'))
            eq_(0, inventory_data.get('licenses'))
            eq_(0, inventory_data.get('available_licenses'))

            edition1, pool1 = self._edition(with_license_pool=True, with_open_access_download=False)
            pool1.open_access = False
            pool1.licenses_owned = 0
            pool1.licenses_available = 0

            edition2, pool2 = self._edition(with_license_pool=True, with_open_access_download=False)
            pool2.open_access = False
            pool2.licenses_owned = 10
            pool2.licenses_available = 0
            
            edition3, pool3 = self._edition(with_license_pool=True, with_open_access_download=False)
            pool3.open_access = False
            pool3.licenses_owned = 5
            pool3.licenses_available = 4

            response = self.manager.admin_dashboard_controller.stats()
            inventory_data = response.get('inventory')
            eq_(4, inventory_data.get('titles'))
            eq_(15, inventory_data.get('licenses'))
            eq_(4, inventory_data.get('available_licenses'))

    def test_stats_vendors(self):
        with self.app.test_request_context("/"):

            # At first, there is 1 open access title in the database,
            # created in CirculationControllerTest.setup.
            response = self.manager.admin_dashboard_controller.stats()
            vendor_data = response.get('vendors')
            eq_(1, vendor_data.get('open_access'))
            eq_(None, vendor_data.get('overdrive'))
            eq_(None, vendor_data.get('bibliotheca'))
            eq_(None, vendor_data.get('axis360'))

            edition1, pool1 = self._edition(with_license_pool=True,
                                            with_open_access_download=False,
                                            data_source_name=DataSource.OVERDRIVE)
            pool1.open_access = False
            pool1.licenses_owned = 10

            edition2, pool2 = self._edition(with_license_pool=True,
                                            with_open_access_download=False,
                                            data_source_name=DataSource.OVERDRIVE)
            pool2.open_access = False
            pool2.licenses_owned = 0

            edition3, pool3 = self._edition(with_license_pool=True,
                                            with_open_access_download=False,
                                            data_source_name=DataSource.BIBLIOTHECA)
            pool3.open_access = False
            pool3.licenses_owned = 3

            edition4, pool4 = self._edition(with_license_pool=True,
                                            with_open_access_download=False,
                                            data_source_name=DataSource.AXIS_360)
            pool4.open_access = False
            pool4.licenses_owned = 5

            response = self.manager.admin_dashboard_controller.stats()
            vendor_data = response.get('vendors')
            eq_(1, vendor_data.get('open_access'))
            eq_(1, vendor_data.get('overdrive'))
            eq_(1, vendor_data.get('bibliotheca'))
            eq_(1, vendor_data.get('axis360'))

class TestSettingsController(AdminControllerTest):

    def setup(self):
        super(TestSettingsController, self).setup()
        # Delete any existing patron auth services created by controller test setup.
        for auth_service in self._db.query(ExternalIntegration).filter(
            ExternalIntegration.goal==ExternalIntegration.PATRON_AUTH_GOAL
         ):
            self._db.delete(auth_service)

        # Delete any existing sitewide ConfigurationSettings.
        for setting in self._db.query(ConfigurationSetting).filter(
            ConfigurationSetting.library_id==None).filter(
            ConfigurationSetting.external_integration_id==None):
            self._db.delete(setting)

    def test_libraries_get_with_no_libraries(self):
        # Delete any existing library created by the controller test setup.
        library = get_one(self._db, Library)
        if library:
            self._db.delete(library)

        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.libraries()
            eq_(response.get("libraries"), [])

    def test_libraries_get_with_multiple_libraries(self):
        # Delete any existing library created by the controller test setup.
        library = get_one(self._db, Library)
        if library:
            self._db.delete(library)

        l1, ignore = create(
            self._db, Library, name="Library 1", short_name="L1",
        )
        l1.library_registry_short_name="L1"
        l1.library_registry_shared_secret="a"
        l2, ignore = create(
            self._db, Library, name="Library 2", short_name="L2",
        )

        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.libraries()
            libraries = response.get("libraries")
            eq_(2, len(libraries))

            eq_(l1.uuid, libraries[0].get("uuid"))
            eq_(l2.uuid, libraries[1].get("uuid"))

            eq_(l1.name, libraries[0].get("name"))
            eq_(l2.name, libraries[1].get("name"))

            eq_(l1.short_name, libraries[0].get("short_name"))
            eq_(l2.short_name, libraries[1].get("short_name"))

            eq_(l1.library_registry_short_name, libraries[0].get("library_registry_short_name"))
            eq_(l2.library_registry_short_name, libraries[1].get("library_registry_short_name"))

            eq_(l1.library_registry_shared_secret, libraries[0].get("library_registry_shared_secret"))
            eq_(l2.library_registry_shared_secret, libraries[1].get("library_registry_shared_secret"))

    def test_libraries_post_errors(self):
        library, ignore = get_one_or_create(
            self._db, Library
        )
        library.short_name = "nypl"
        library.library_registry_shared_secret = "secret"

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("uuid", "1234"),
                ("name", "Brooklyn Public Library"),
                ("short_name", "bpl"),
            ])
            response = self.manager.admin_settings_controller.libraries()
            eq_(response, LIBRARY_NOT_FOUND)
        
        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("uuid", library.uuid),
                ("short_name", "nypl"),
                ("library_registry_shared_secret", "secret"),
                ("random_library_registry_shared_secret", ""),
            ])
            response = self.manager.admin_settings_controller.libraries()
            eq_(response, CANNOT_SET_BOTH_RANDOM_AND_SPECIFIC_SECRET)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("uuid", library.uuid),
                ("short_name", library.short_name),
                ("random_library_registry_shared_secret", ""),
            ])
            response = self.manager.admin_settings_controller.libraries()
            eq_(response, CANNOT_REPLACE_EXISTING_SECRET_WITH_RANDOM_SECRET)

    def test_libraries_post_create(self):
        # Delete any existing library created by the controller test setup.
        library = get_one(self._db, Library)
        if library:
            self._db.delete(library)
            
        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "The New York Public Library"),
                ("short_name", "nypl"),
                ("library_registry_short_name", "NYPL"),
                ("library_registry_shared_secret", "secret"),
            ])
            response = self.manager.admin_settings_controller.libraries()
            eq_(response.status_code, 201)

        library = get_one(self._db, Library)

        eq_(library.name, "The New York Public Library")
        eq_(library.short_name, "nypl")
        eq_(library.library_registry_short_name, "NYPL")
        eq_(library.library_registry_shared_secret, "secret")

    def test_libraries_post_edit(self):
        # A library already exists.
        library, ignore = get_one_or_create(self._db, Library)

        library.name = "Nwe York Public Libary"
        library.short_name = "nypl"
        library.library_registry_short_name = None
        library.library_registry_shared_secret = None

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("uuid", library.uuid),
                ("name", "The New York Public Library"),
                ("short_name", "nypl"),
                ("library_registry_short_name", "NYPL"),
                ("random_library_registry_shared_secret", ""),
            ])
            response = self.manager.admin_settings_controller.libraries()
            eq_(response.status_code, 200)

        library = get_one(self._db, Library)

        eq_(library.name, "The New York Public Library")
        eq_(library.short_name, "nypl")
        eq_(library.library_registry_short_name, "NYPL")

        # The shared secret was randomly generated, so we can't test
        # its exact value, but we do know it's a string that can be
        # converted into a hexadecimal number.
        assert library.library_registry_shared_secret != None
        int(library.library_registry_shared_secret, 16)
        
    def test_collections_get_with_no_collections(self):
        # Delete any existing collections created by the test setup.
        for collection in self._db.query(Collection):
            self._db.delete(collection)

        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.collections()
            eq_(response.get("collections"), [])

            # All the protocols in ExternalIntegration.LICENSE_PROTOCOLS are supported by the admin interface.
            eq_(sorted([p.get("name") for p in response.get("protocols")]),
                sorted(ExternalIntegration.LICENSE_PROTOCOLS))

    def test_collections_get_with_multiple_collections(self):

        [c1] = self._default_library.collections

        c2 = self._collection(
            name="Collection 2", protocol=ExternalIntegration.BIBLIOTHECA,
        )
        c2.external_account_id = "1234"
        c2.external_integration.password = "b"

        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.collections()
            collections = response.get("collections")
            eq_(2, len(collections))

            eq_(c1.name, collections[0].get("name"))
            eq_(c2.name, collections[1].get("name"))

            eq_(c1.protocol, collections[0].get("protocol"))
            eq_(c2.protocol, collections[1].get("protocol"))

            eq_(c1.external_account_id, collections[0].get("external_account_id"))
            eq_(c2.external_account_id, collections[1].get("external_account_id"))

            eq_(c1.external_integration.password, collections[0].get("password"))
            eq_(c2.external_integration.password, collections[1].get("password"))

    def test_collections_post_errors(self):
        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("protocol", "Overdrive"),
            ])
            response = self.manager.admin_settings_controller.collections()
            eq_(response, MISSING_COLLECTION_NAME)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "collection"),
            ])
            response = self.manager.admin_settings_controller.collections()
            eq_(response, NO_PROTOCOL_FOR_NEW_COLLECTION)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "collection"),
                ("protocol", "Unknown"),
            ])
            response = self.manager.admin_settings_controller.collections()
            eq_(response, UNKNOWN_COLLECTION_PROTOCOL)

        collection = self._collection(
            name="Collection 1",
            protocol=ExternalIntegration.OVERDRIVE
        )

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "Collection 1"),
                ("protocol", "Bibliotheca"),
            ])
            response = self.manager.admin_settings_controller.collections()
            eq_(response, CANNOT_CHANGE_COLLECTION_PROTOCOL)


        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "collection"),
                ("protocol", "OPDS Import"),
                ("external_account_id", "test.com"),
                ("libraries", json.dumps(["nosuchlibrary"])),
            ])
            response = self.manager.admin_settings_controller.collections()
            eq_(response.uri, NO_SUCH_LIBRARY.uri)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "collection1"),
                ("protocol", "OPDS Import"),
            ])
            response = self.manager.admin_settings_controller.collections()
            eq_(response.uri, INCOMPLETE_COLLECTION_CONFIGURATION.uri)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "Collection 1"),
                ("protocol", "Overdrive"),
                ("external_account_id", "1234"),
                ("username", "user"),
                ("password", "password"),
            ])
            response = self.manager.admin_settings_controller.collections()
            eq_(response.uri, INCOMPLETE_COLLECTION_CONFIGURATION.uri)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "collection1"),
                ("protocol", "Bibliotheca"),
                ("external_account_id", "1234"),
                ("password", "password"),
            ])
            response = self.manager.admin_settings_controller.collections()
            eq_(response.uri, INCOMPLETE_COLLECTION_CONFIGURATION.uri)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "collection1"),
                ("protocol", "Axis 360"),
                ("username", "user"),
                ("password", "password"),
            ])
            response = self.manager.admin_settings_controller.collections()
            eq_(response.uri, INCOMPLETE_COLLECTION_CONFIGURATION.uri)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "collection1"),
                ("protocol", "OneClick"),
                ("username", "user"),
                ("password", "password"),
            ])
            response = self.manager.admin_settings_controller.collections()
            eq_(response.uri, INCOMPLETE_COLLECTION_CONFIGURATION.uri)

    def test_collections_post_create(self):
        l1, ignore = create(
            self._db, Library, name="Library 1", short_name="L1",
        )
        l2, ignore = create(
            self._db, Library, name="Library 2", short_name="L2",
        )
        l3, ignore = create(
            self._db, Library, name="Library 3", short_name="L3",
        )

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "New Collection"),
                ("protocol", "Overdrive"),
                ("libraries", json.dumps(["L1", "L2"])),
                ("external_account_id", "acctid"),
                ("username", "username"),
                ("password", "password"),
                ("website_id", "1234"),
                ("default_loan_period", "14"),
                ("default_reservation_period", "3"),
            ])
            response = self.manager.admin_settings_controller.collections()
            eq_(response.status_code, 201)

        # The collection was created and configured properly.
        collection = get_one(self._db, Collection, name="New Collection")
        eq_("New Collection", collection.name)
        eq_("acctid", collection.external_account_id)
        eq_("username", collection.external_integration.username)
        eq_("password", collection.external_integration.password)

        # Two libraries now have access to the collection.
        eq_([collection], l1.collections)
        eq_([collection], l2.collections)
        eq_([], l3.collections)

        # Additional settings were set on the collection.
        setting = collection.external_integration.setting("website_id")
        eq_("website_id", setting.key)
        eq_("1234", setting.value)

        setting = collection.external_integration.setting("default_loan_period")
        eq_("default_loan_period", setting.key)
        eq_("14", setting.value)

        setting = collection.external_integration.setting("default_reservation_period")
        eq_("default_reservation_period", setting.key)
        eq_("3", setting.value)

    def test_collections_post_edit(self):
        # The collection exists.
        collection = self._collection(
            name="Collection 1",
            protocol=ExternalIntegration.OVERDRIVE
        )

        l1, ignore = create(
            self._db, Library, name="Library 1", short_name="L1",
        )

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "Collection 1"),
                ("protocol", ExternalIntegration.OVERDRIVE),
                ("external_account_id", "1234"),
                ("username", "user2"),
                ("password", "password"),
                ("website_id", "1234"),
                ("libraries", json.dumps(["L1"])),
                ("default_loan_period", "14"),
                ("default_reservation_period", "3"),
            ])
            response = self.manager.admin_settings_controller.collections()
            eq_(response.status_code, 200)

        # The collection has been changed.
        eq_("user2", collection.external_integration.username)

        # A library now has access to the collection.
        eq_([collection], l1.collections)

        # Additional settings were set on the collection.
        setting = collection.external_integration.setting("website_id")
        eq_("website_id", setting.key)
        eq_("1234", setting.value)

        setting = collection.external_integration.setting("default_loan_period")
        eq_("default_loan_period", setting.key)
        eq_("14", setting.value)

        setting = collection.external_integration.setting("default_reservation_period")
        eq_("default_reservation_period", setting.key)
        eq_("3", setting.value)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("name", "Collection 1"),
                ("protocol", ExternalIntegration.OVERDRIVE),
                ("external_account_id", "1234"),
                ("username", "user2"),
                ("password", "password"),
                ("website_id", "1234"),
                ("default_loan_period", "14"),
                ("default_reservation_period", "3"),
                ("libraries", json.dumps([])),
            ])
            response = self.manager.admin_settings_controller.collections()
            eq_(response.status_code, 200)

        # The collection is the same.
        eq_("user2", collection.external_integration.username)
        eq_(ExternalIntegration.OVERDRIVE, collection.protocol)

        # But the library has been removed.
        eq_([], l1.collections)

    def test_admin_auth_services_get_with_no_services(self):
        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.admin_auth_services()
            eq_(response.get("admin_auth_services"), [])

            # All the protocols in ExternalIntegration.ADMIN_AUTH_PROTOCOLS
            # are supported by the admin interface.
            eq_(sorted([p for p in response.get("providers")]),
                sorted(ExternalIntegration.ADMIN_AUTH_PROTOCOLS))
        
    def test_admin_auth_services_get_with_google_oauth_service(self):
        auth_service, ignore = create(
            self._db, ExternalIntegration,
            protocol=ExternalIntegration.GOOGLE_OAUTH,
            goal=ExternalIntegration.ADMIN_AUTH_GOAL
        )
        auth_service.url = "http://oauth.test"
        auth_service.username = "user"
        auth_service.password = "pass"
        auth_service.set_setting("domains", json.dumps(["nypl.org"]))

        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.admin_auth_services()
            [service] = response.get("admin_auth_services")

            eq_(auth_service.protocol, service.get("provider"))
            eq_(auth_service.url, service.get("url"))
            eq_(auth_service.username, service.get("username"))
            eq_(auth_service.password, service.get("password"))
            eq_(["nypl.org"], service.get("domains"))

    def test_admin_auth_services_post_errors(self):
        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("provider", "Unknown"),
            ])
            response = self.manager.admin_settings_controller.admin_auth_services()
            eq_(response, UNKNOWN_ADMIN_AUTH_SERVICE_PROVIDER)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([])
            response = self.manager.admin_settings_controller.admin_auth_services()
            eq_(response, NO_PROVIDER_FOR_NEW_ADMIN_AUTH_SERVICE)

    def test_admin_auth_services_post_errors_google_oauth(self):
        auth_service, ignore = create(
            self._db, ExternalIntegration,
            protocol=ExternalIntegration.GOOGLE_OAUTH,
            goal=ExternalIntegration.ADMIN_AUTH_GOAL
        )

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([])
            response = self.manager.admin_settings_controller.admin_auth_services()
            eq_(response, CANNOT_CHANGE_ADMIN_AUTH_SERVICE_PROVIDER)
        
        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("provider", "Google OAuth"),
            ])
            response = self.manager.admin_settings_controller.admin_auth_services()
            eq_(response.uri, INCOMPLETE_ADMIN_AUTH_SERVICE_CONFIGURATION.uri)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("provider", "Google OAuth"),
                ("url", "url"),
                ("username", "username"),
                ("password", "password"),
                ("domains", "not json"),
            ])
            response = self.manager.admin_settings_controller.admin_auth_services()
            eq_(response, INVALID_ADMIN_AUTH_DOMAIN_LIST)

    def test_admin_auth_services_post_google_oauth_create(self):
        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("provider", "Google OAuth"),
                ("url", "url"),
                ("username", "username"),
                ("password", "password"),
                ("domains", json.dumps(["nypl.org", "gmail.com"])),
            ])
            response = self.manager.admin_settings_controller.admin_auth_services()
            eq_(response.status_code, 201)

        # The auth service was created and configured properly.
        auth_service = ExternalIntegration.admin_authentication(self._db)
        eq_("url", auth_service.url)
        eq_("username", auth_service.username)
        eq_("password", auth_service.password)

        setting = auth_service.setting("domains")
        eq_("domains", setting.key)
        eq_(["nypl.org", "gmail.com"], json.loads(setting.value))

    def test_admin_auth_services_post_google_oauth_edit(self):
        # The auth service exists.
        auth_service, ignore = create(
            self._db, ExternalIntegration,
            protocol=ExternalIntegration.GOOGLE_OAUTH,
            goal=ExternalIntegration.ADMIN_AUTH_GOAL
        )
        auth_service.url = "url"
        auth_service.username = "user"
        auth_service.password = "pass"
        auth_service.set_setting("domains", json.dumps(["library1.org"]))

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("provider", "Google OAuth"),
                ("url", "url2"),
                ("username", "user2"),
                ("password", "pass2"),
                ("domains", json.dumps(["library2.org"])),
            ])
            response = self.manager.admin_settings_controller.admin_auth_services()
            eq_(response.status_code, 200)

        eq_("url2", auth_service.url)
        eq_("user2", auth_service.username)
        setting = auth_service.setting("domains")
        eq_("domains", setting.key)
        eq_(["library2.org"], json.loads(setting.value))

    def test_individual_admins_get(self):
        # There are two admins that can sign in with passwords.
        admin1, ignore = create(self._db, Admin, email="admin1@nypl.org")
        admin1.password = "pass1"
        admin2, ignore = create(self._db, Admin, email="admin2@nypl.org")
        admin2.password = "pass2"

        # This admin doesn't have a password, and won't be included.
        admin3, ignore = create(self._db, Admin, email="admin3@nypl.org")

        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.individual_admins()
            admins = response.get("individualAdmins")
            eq_([{"email": "admin1@nypl.org"}, {"email": "admin2@nypl.org"}], admins)

    def test_individual_admins_post_errors(self):
        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([])
            response = self.manager.admin_settings_controller.individual_admins()
            eq_(response.uri, INVALID_INDIVIDUAL_ADMIN_CONFIGURATION.uri)

    def test_individual_admins_post_create(self):
        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("email", "admin@nypl.org"),
                ("password", "pass"),
            ])
            response = self.manager.admin_settings_controller.individual_admins()
            eq_(response.status_code, 201)

        # The admin was created.
        admin_matches = self._db.query(Admin).filter(Admin.email=="admin@nypl.org").filter(Admin.password=="pass").all()
        eq_(1, len(admin_matches))

    def test_individual_admins_post_edit(self):
        # An admin exists.
        admin, ignore = create(
            self._db, Admin, email="admin@nypl.org",
        )
        admin.password = "password"

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("email", "admin@nypl.org"),
                ("password", "new password"),
            ])
            response = self.manager.admin_settings_controller.individual_admins()
            eq_(response.status_code, 200)

        # The password was changed.
        old_password_matches = self._db.query(Admin).filter(Admin.email=="admin@nypl.org").filter(Admin.password=="password").all()
        eq_(0, len(old_password_matches))

        new_password_matches = self._db.query(Admin).filter(Admin.email=="admin@nypl.org").filter(Admin.password=="new password").all()
        eq_([admin], new_password_matches)

    def test_patron_auth_services_get_with_no_services(self):
        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.patron_auth_services()
            eq_(response.get("patron_auth_services"), [])
            protocols = response.get("protocols")
            eq_(5, len(protocols))
            eq_(SimpleAuthenticationProvider.__module__, protocols[0].get("name"))
            assert "fields" in protocols[0]
            assert "library_fields" in protocols[0]
        
    def test_patron_auth_services_get_with_simple_auth_service(self):
        auth_service, ignore = create(
            self._db, ExternalIntegration,
            protocol=SimpleAuthenticationProvider.__module__,
            goal=ExternalIntegration.PATRON_AUTH_GOAL
        )
        auth_service.setting(BasicAuthenticationProvider.TEST_IDENTIFIER).value = "user"
        auth_service.setting(BasicAuthenticationProvider.TEST_PASSWORD).value = "pass"

        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.patron_auth_services()
            [service] = response.get("patron_auth_services")

            eq_(auth_service.id, service.get("id"))
            eq_(SimpleAuthenticationProvider.__module__, service.get("protocol"))
            eq_("user", service.get("settings").get(BasicAuthenticationProvider.TEST_IDENTIFIER))
            eq_("pass", service.get("settings").get(BasicAuthenticationProvider.TEST_PASSWORD))
            eq_([], service.get("libraries"))

        auth_service.libraries += [self._default_library]
        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.patron_auth_services()
            [service] = response.get("patron_auth_services")

            eq_("user", service.get("settings").get(BasicAuthenticationProvider.TEST_IDENTIFIER))
            [library] = service.get("libraries")
            eq_(self._default_library.short_name, library.get("short_name"))
            eq_(None, library.get(AuthenticationProvider.EXTERNAL_TYPE_REGULAR_EXPRESSION))

        ConfigurationSetting.for_library_and_externalintegration(
            self._db, AuthenticationProvider.EXTERNAL_TYPE_REGULAR_EXPRESSION,
            self._default_library, auth_service,
        ).value = "^(u)"
        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.patron_auth_services()
            [service] = response.get("patron_auth_services")

            [library] = service.get("libraries")
            eq_(self._default_library.short_name, library.get("short_name"))
            eq_("^(u)", library.get(AuthenticationProvider.EXTERNAL_TYPE_REGULAR_EXPRESSION))
        
    def test_patron_auth_services_get_with_millenium_auth_service(self):
        auth_service, ignore = create(
            self._db, ExternalIntegration,
            protocol=MilleniumPatronAPI.__module__,
            goal=ExternalIntegration.PATRON_AUTH_GOAL
        )
        auth_service.setting(BasicAuthenticationProvider.TEST_IDENTIFIER).value = "user"
        auth_service.setting(BasicAuthenticationProvider.TEST_PASSWORD).value = "pass"
        auth_service.setting(BasicAuthenticationProvider.IDENTIFIER_REGULAR_EXPRESSION).value = "u*"
        auth_service.setting(BasicAuthenticationProvider.PASSWORD_REGULAR_EXPRESSION).value = "p*"
        auth_service.libraries += [self._default_library]
        ConfigurationSetting.for_library_and_externalintegration(
            self._db, AuthenticationProvider.EXTERNAL_TYPE_REGULAR_EXPRESSION,
            self._default_library, auth_service,
        ).value = "^(u)"

        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.patron_auth_services()
            [service] = response.get("patron_auth_services")

            eq_(auth_service.id, service.get("id"))
            eq_(MilleniumPatronAPI.__module__, service.get("protocol"))
            eq_("user", service.get("settings").get(BasicAuthenticationProvider.TEST_IDENTIFIER))
            eq_("pass", service.get("settings").get(BasicAuthenticationProvider.TEST_PASSWORD))
            eq_("u*", service.get("settings").get(BasicAuthenticationProvider.IDENTIFIER_REGULAR_EXPRESSION))
            eq_("p*", service.get("settings").get(BasicAuthenticationProvider.PASSWORD_REGULAR_EXPRESSION))
            [library] = service.get("libraries")
            eq_(self._default_library.short_name, library.get("short_name"))
            eq_("^(u)", library.get(AuthenticationProvider.EXTERNAL_TYPE_REGULAR_EXPRESSION))

    def test_patron_auth_services_get_with_sip2_auth_service(self):
        auth_service, ignore = create(
            self._db, ExternalIntegration,
            protocol=SIP2AuthenticationProvider.__module__,
            goal=ExternalIntegration.PATRON_AUTH_GOAL
        )
        auth_service.url = "url"
        auth_service.setting(SIP2AuthenticationProvider.PORT).value = "1234"
        auth_service.username = "user"
        auth_service.password = "pass"
        auth_service.setting(SIP2AuthenticationProvider.LOCATION_CODE).value = "5"
        auth_service.setting(SIP2AuthenticationProvider.FIELD_SEPARATOR).value = ","

        auth_service.libraries += [self._default_library]
        ConfigurationSetting.for_library_and_externalintegration(
            self._db, AuthenticationProvider.EXTERNAL_TYPE_REGULAR_EXPRESSION,
            self._default_library, auth_service,
        ).value = "^(u)"

        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.patron_auth_services()
            [service] = response.get("patron_auth_services")

            eq_(auth_service.id, service.get("id"))
            eq_(SIP2AuthenticationProvider.__module__, service.get("protocol"))
            eq_("url", service.get("settings").get(ExternalIntegration.URL))
            eq_("1234", service.get("settings").get(SIP2AuthenticationProvider.PORT))
            eq_("user", service.get("settings").get(ExternalIntegration.USERNAME))
            eq_("pass", service.get("settings").get(ExternalIntegration.PASSWORD))
            eq_("5", service.get("settings").get(SIP2AuthenticationProvider.LOCATION_CODE))
            eq_(",", service.get("settings").get(SIP2AuthenticationProvider.FIELD_SEPARATOR))
            [library] = service.get("libraries")
            eq_(self._default_library.short_name, library.get("short_name"))
            eq_("^(u)", library.get(AuthenticationProvider.EXTERNAL_TYPE_REGULAR_EXPRESSION))

    def test_patron_auth_services_get_with_firstbook_auth_service(self):
        auth_service, ignore = create(
            self._db, ExternalIntegration,
            protocol=FirstBookAuthenticationAPI.__module__,
            goal=ExternalIntegration.PATRON_AUTH_GOAL
        )
        auth_service.url = "url"
        auth_service.password = "pass"
        auth_service.libraries += [self._default_library]
        ConfigurationSetting.for_library_and_externalintegration(
            self._db, AuthenticationProvider.EXTERNAL_TYPE_REGULAR_EXPRESSION,
            self._default_library, auth_service,
        ).value = "^(u)"

        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.patron_auth_services()
            [service] = response.get("patron_auth_services")

            eq_(auth_service.id, service.get("id"))
            eq_(FirstBookAuthenticationAPI.__module__, service.get("protocol"))
            eq_("url", service.get("settings").get(ExternalIntegration.URL))
            eq_("pass", service.get("settings").get(ExternalIntegration.PASSWORD))
            [library] = service.get("libraries")
            eq_(self._default_library.short_name, library.get("short_name"))
            eq_("^(u)", library.get(AuthenticationProvider.EXTERNAL_TYPE_REGULAR_EXPRESSION))

    def test_patron_auth_services_get_with_clever_auth_service(self):
        auth_service, ignore = create(
            self._db, ExternalIntegration,
            protocol=CleverAuthenticationAPI.__module__,
            goal=ExternalIntegration.PATRON_AUTH_GOAL
        )
        auth_service.username = "user"
        auth_service.password = "pass"
        auth_service.libraries += [self._default_library]

        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.patron_auth_services()
            [service] = response.get("patron_auth_services")

            eq_(auth_service.id, service.get("id"))
            eq_(CleverAuthenticationAPI.__module__, service.get("protocol"))
            eq_("user", service.get("settings").get(ExternalIntegration.USERNAME))
            eq_("pass", service.get("settings").get(ExternalIntegration.PASSWORD))
            [library] = service.get("libraries")
            eq_(self._default_library.short_name, library.get("short_name"))

    def test_patron_auth_services_post_errors(self):
        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("protocol", "Unknown"),
            ])
            response = self.manager.admin_settings_controller.patron_auth_services()
            eq_(response, UNKNOWN_PATRON_AUTH_SERVICE_PROTOCOL)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([])
            response = self.manager.admin_settings_controller.patron_auth_services()
            eq_(response, NO_PROTOCOL_FOR_NEW_PATRON_AUTH_SERVICE)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("id", "123"),
            ])
            response = self.manager.admin_settings_controller.patron_auth_services()
            eq_(response, MISSING_PATRON_AUTH_SERVICE)

        auth_service, ignore = create(
            self._db, ExternalIntegration,
            protocol=SimpleAuthenticationProvider.__module__,
            goal=ExternalIntegration.PATRON_AUTH_GOAL
        )

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("id", auth_service.id),
                ("protocol", SIP2AuthenticationProvider.__module__),
            ])
            response = self.manager.admin_settings_controller.patron_auth_services()
            eq_(response, CANNOT_CHANGE_PATRON_AUTH_SERVICE_PROTOCOL)

        auth_service, ignore = create(
            self._db, ExternalIntegration,
            protocol=MilleniumPatronAPI.__module__,
            goal=ExternalIntegration.PATRON_AUTH_GOAL
        )

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("id", auth_service.id),
                ("protocol", MilleniumPatronAPI.__module__),
                (MilleniumPatronAPI.AUTHENTICATION_MODE, "Invalid mode"),
            ])
            response = self.manager.admin_settings_controller.patron_auth_services()
            eq_(response.uri, INVALID_PATRON_AUTH_SERVICE_CONFIGURATION_OPTION.uri)

        auth_service, ignore = create(
            self._db, ExternalIntegration,
            protocol=SimpleAuthenticationProvider.__module__,
            goal=ExternalIntegration.PATRON_AUTH_GOAL
        )

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("id", auth_service.id),
                ("protocol", SimpleAuthenticationProvider.__module__),
            ])
            response = self.manager.admin_settings_controller.patron_auth_services()
            eq_(response.uri, INCOMPLETE_PATRON_AUTH_SERVICE_CONFIGURATION.uri)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("protocol", SimpleAuthenticationProvider.__module__),
                (BasicAuthenticationProvider.TEST_IDENTIFIER, "user"),
                (BasicAuthenticationProvider.TEST_PASSWORD, "pass"),
                ("libraries", json.dumps([{ "short_name": "not-a-library" }])),
            ])
            response = self.manager.admin_settings_controller.patron_auth_services()
            eq_(response.uri, NO_SUCH_LIBRARY.uri)

        auth_service, ignore = create(
            self._db, ExternalIntegration,
            protocol=SimpleAuthenticationProvider.__module__,
            goal=ExternalIntegration.PATRON_AUTH_GOAL
        )
        library, ignore = create(
            self._db, Library, name="Library", short_name="L",
        )
        auth_service.libraries += [library]

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("protocol", SimpleAuthenticationProvider.__module__),
                (BasicAuthenticationProvider.TEST_IDENTIFIER, "user"),
                (BasicAuthenticationProvider.TEST_PASSWORD, "pass"),
                ("libraries", json.dumps([{ "short_name": library.short_name }])),
            ])
            response = self.manager.admin_settings_controller.patron_auth_services()
            eq_(response.uri, MULTIPLE_BASIC_AUTH_SERVICES.uri)

        library, ignore = create(
            self._db, Library, name="Library", short_name="L",
        )
        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("protocol", SimpleAuthenticationProvider.__module__),
                (BasicAuthenticationProvider.TEST_IDENTIFIER, "user"),
                (BasicAuthenticationProvider.TEST_PASSWORD, "pass"),
                ("libraries", json.dumps([{
                    "short_name": library.short_name,
                    AuthenticationProvider.EXTERNAL_TYPE_REGULAR_EXPRESSION: "(invalid re",
                }])),
            ])
            response = self.manager.admin_settings_controller.patron_auth_services()
            eq_(response, INVALID_EXTERNAL_TYPE_REGULAR_EXPRESSION)

    def test_patron_auth_services_post_create(self):
        library, ignore = create(
            self._db, Library, name="Library", short_name="L",
        )
        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("protocol", SimpleAuthenticationProvider.__module__),
                (BasicAuthenticationProvider.TEST_IDENTIFIER, "user"),
                (BasicAuthenticationProvider.TEST_PASSWORD, "pass"),
                ("libraries", json.dumps([{
                    "short_name": library.short_name,
                    AuthenticationProvider.EXTERNAL_TYPE_REGULAR_EXPRESSION: "^(.)",
                }])),
            ])
            response = self.manager.admin_settings_controller.patron_auth_services()
            eq_(response.status_code, 201)

        auth_service = get_one(self._db, ExternalIntegration, goal=ExternalIntegration.PATRON_AUTH_GOAL)
        eq_(SimpleAuthenticationProvider.__module__, auth_service.protocol)
        eq_("user", auth_service.setting(BasicAuthenticationProvider.TEST_IDENTIFIER).value)
        eq_("pass", auth_service.setting(BasicAuthenticationProvider.TEST_PASSWORD).value)
        eq_([library], auth_service.libraries)
        eq_("^(.)", ConfigurationSetting.for_library_and_externalintegration(
                self._db, AuthenticationProvider.EXTERNAL_TYPE_REGULAR_EXPRESSION,
                library, auth_service).value)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("protocol", MilleniumPatronAPI.__module__),
                (BasicAuthenticationProvider.TEST_IDENTIFIER, "user"),
                (BasicAuthenticationProvider.TEST_PASSWORD, "pass"),
                (MilleniumPatronAPI.VERIFY_CERTIFICATE, "true"),
                (MilleniumPatronAPI.AUTHENTICATION_MODE, MilleniumPatronAPI.PIN_AUTHENTICATION_MODE),
            ])
            response = self.manager.admin_settings_controller.patron_auth_services()
            eq_(response.status_code, 201)

        auth_service2 = get_one(self._db, ExternalIntegration,
                               goal=ExternalIntegration.PATRON_AUTH_GOAL,
                               protocol=MilleniumPatronAPI.__module__)
        assert auth_service2 != auth_service
        eq_("user", auth_service2.setting(BasicAuthenticationProvider.TEST_IDENTIFIER).value)
        eq_("pass", auth_service2.setting(BasicAuthenticationProvider.TEST_PASSWORD).value)
        eq_("true",
            auth_service2.setting(MilleniumPatronAPI.VERIFY_CERTIFICATE).value)
        eq_(MilleniumPatronAPI.PIN_AUTHENTICATION_MODE,
            auth_service2.setting(MilleniumPatronAPI.AUTHENTICATION_MODE).value)
        eq_(None, auth_service2.setting(MilleniumPatronAPI.IDENTIFIER_BLACKLIST).value)
        eq_([], auth_service2.libraries)

    def test_patron_auth_services_post_edit(self):
        l1, ignore = create(
            self._db, Library, name="Library 1", short_name="L1",
        )
        l2, ignore = create(
            self._db, Library, name="Library 2", short_name="L2",
        )

        auth_service, ignore = create(
            self._db, ExternalIntegration,
            protocol=SimpleAuthenticationProvider.__module__,
            goal=ExternalIntegration.PATRON_AUTH_GOAL
        )
        auth_service.setting(BasicAuthenticationProvider.TEST_IDENTIFIER).value = "old_user"
        auth_service.setting(BasicAuthenticationProvider.TEST_PASSWORD).value = "old_password"
        auth_service.libraries = [l1]

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("id", auth_service.id),
                ("protocol", SimpleAuthenticationProvider.__module__),
                (BasicAuthenticationProvider.TEST_IDENTIFIER, "user"),
                (BasicAuthenticationProvider.TEST_PASSWORD, "pass"),
                ("libraries", json.dumps([{
                    "short_name": l2.short_name,
                    AuthenticationProvider.EXTERNAL_TYPE_REGULAR_EXPRESSION: "^(.)",
                }])),
            ])
            response = self.manager.admin_settings_controller.patron_auth_services()
            eq_(response.status_code, 200)

        eq_(SimpleAuthenticationProvider.__module__, auth_service.protocol)
        eq_("user", auth_service.setting(BasicAuthenticationProvider.TEST_IDENTIFIER).value)
        eq_("pass", auth_service.setting(BasicAuthenticationProvider.TEST_PASSWORD).value)
        eq_([l2], auth_service.libraries)
        eq_("^(.)", ConfigurationSetting.for_library_and_externalintegration(
                self._db, AuthenticationProvider.EXTERNAL_TYPE_REGULAR_EXPRESSION,
                l2, auth_service).value)

    def test_sitewide_settings_get(self):
        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.sitewide_settings()
            settings = response.get("settings")
            fields = response.get("fields")

            eq_([], settings)
            keys = [f.get("key") for f in fields]
            assert AcquisitionFeed.GROUPED_MAX_AGE_POLICY in keys
            assert AcquisitionFeed.NONGROUPED_MAX_AGE_POLICY in keys
            assert Configuration.SECRET_KEY in keys

        ConfigurationSetting.sitewide(self._db, AcquisitionFeed.GROUPED_MAX_AGE_POLICY).value = 0
        ConfigurationSetting.sitewide(self._db, Configuration.SECRET_KEY).value = "secret"

        with self.app.test_request_context("/"):
            response = self.manager.admin_settings_controller.sitewide_settings()
            settings = response.get("settings")
            fields = response.get("fields")

            eq_(2, len(settings))
            settings_by_key = { s.get("key") : s.get("value") for s in settings }
            eq_("0", settings_by_key.get(AcquisitionFeed.GROUPED_MAX_AGE_POLICY))
            eq_("secret", settings_by_key.get(Configuration.SECRET_KEY))
            keys = [f.get("key") for f in fields]
            assert AcquisitionFeed.GROUPED_MAX_AGE_POLICY in keys
            assert AcquisitionFeed.NONGROUPED_MAX_AGE_POLICY in keys
            assert Configuration.SECRET_KEY in keys

    def test_sitewide_settings_post_errors(self):
        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([])
            response = self.manager.admin_settings_controller.sitewide_settings()
            eq_(response, MISSING_SITEWIDE_SETTING_KEY)

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("key", Configuration.SECRET_KEY),
            ])
            response = self.manager.admin_settings_controller.sitewide_settings()
            eq_(response, MISSING_SITEWIDE_SETTING_VALUE)

    def test_sitewide_settings_post_create(self):
        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("key", AcquisitionFeed.GROUPED_MAX_AGE_POLICY),
                ("value", "10"),
            ])
            response = self.manager.admin_settings_controller.sitewide_settings()
            eq_(response.status_code, 200)

        # The setting was created.
        setting = ConfigurationSetting.sitewide(self._db, AcquisitionFeed.GROUPED_MAX_AGE_POLICY)
        eq_("10", setting.value)

    def test_sitewide_settings_post_edit(self):
        setting = ConfigurationSetting.sitewide(self._db, AcquisitionFeed.GROUPED_MAX_AGE_POLICY)
        setting.value = "10"

        with self.app.test_request_context("/", method="POST"):
            flask.request.form = MultiDict([
                ("key", AcquisitionFeed.GROUPED_MAX_AGE_POLICY),
                ("value", "20"),
            ])
            response = self.manager.admin_settings_controller.sitewide_settings()
            eq_(response.status_code, 200)

        # The setting was changed.
        eq_("20", setting.value)

