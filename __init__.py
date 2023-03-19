#!/usr/bin/env python3

import gettext
import html
import re
import time
from queue import Queue, Empty
from threading import Thread

from calibre.ebooks.metadata import check_isbn
from calibre.ebooks.metadata.book.base import Metadata
from calibre.ebooks.metadata.sources.base import Source, Option, fixauthors, fixcase
from calibre_plugins.isfdb3.objects import Publication, Title, PublicationsList, TitleList, TitleCovers
# import calibre_plugins.isfdb3.myglobals
from calibre_plugins.isfdb3.myglobals import LANGUAGES, IDENTIFIER_TYPES, EXTERNAL_IDS

# References:
#
# The ISFDB home page: http://www.isfdb.org/cgi-bin/index.cgi
# The ISFDB wiki: http://www.isfdb.org/wiki/index.php/Main_Page
# The ISFDB database scheme: http://www.isfdb.org/wiki/index.php/Database_Schema
# The ISFDB Web API: http://www.isfdb.org/wiki/index.php/Web_API
#
# ISFDB Bibliographic Tools
# This project provides a tool for querying a local ISFDB database
# https://sourceforge.net/projects/isfdb/
# https://sourceforge.net/p/isfdb/wiki/Home/
# https://github.com/JohnSmithDev/ISFDB-Tools
# The ISFDB database is available here: http://www.isfdb.org/wiki/index.php/ISFDB_Downloads

# https://pyvideo.org/pycon-za-2018/custom-metadata-plugins-for-calibre-cataloguing-an-old-paper-library.html
# https://github.com/confluence/isfdb2-calibre

# _ = gettext.gettext  # is already done by load_translations()
load_translations()


class ISFDB3(Source):
    name = 'ISFDB3'
    description = _('Downloads metadata and covers from ISFDB (https://www.isfdb.org/)')
    author = 'Michael Detambel - Forked from Adrianna Pińska\'s ISFDB2 (https://github.com/confluence/isfdb2-calibre)'
    version = (1, 2, 1)  # Changes in forked version: see changelog

    # Changelog
    # Version 1.2.1 03-19-2023
    # - Installing error when using locale.getdefaultlocale(). Changed to locale.getlocale() with fallback to 'en_US'.
    #   Thanks to andytinkham for the error report.
    # Version 1.2.0 03-12-2023
    # - New: Fetch all idemtifier types from ISFDB publication page.
    # - New: In simple sarch mode, very short or generic titles returns a lot of title and/or pub records.
    #   '=' as the first character in title fields raises an exact title search.
    # - Translation of ISFDB pages text as an option started (very experimental at the moment).
    # - Handling of unwanted tags fixed.
    # - New: Handling of ratings.
    # - Protocol of isfdb.org links is now https.
    # Version 1.1.6 02-17-2023
    # - Pub types added: NONFICTIOB and OMNIBUS (was ignored till now).
    # Version 1.1.5 01-27-2023
    # - Pub type added: MAGAZINE (was ignored till now).
    # Version 1.1.4 11-30-2022
    # - Handling redirection to a title page, if only one title record found.
    # Version 1.1.3 11-15-2022
    # - In simple search, to filter authors from title list, unquote the author's name from url
    #   (convert percent encoded characters back).
    # Version 1.1.2 07-14-2022
    # - Comparing author in simple search case-insensitive.
    # Version 1.1.1 07-13-2022
    # - Advanced search is now only for logged-in users. Fallback to simple search.
    # Version 1.1.0 02-16-2022
    # - Configuration for unwanted tags / Remove duplicates in tags.
    # - Erroneously series source link in comment, not source links for titles and pubs.
    # Version 1.0.3 02-10-2022
    # - Optimized title/pub merge: Cache title id for all pub ids in author/title search (analig search with ISBN).
    # Version 1.0.2 02-06-2022
    # - Parse error for dictionary LANGUAGES (moved from class to module scope).
    # - Typo in calling translate method.
    # Version 1.0.1 - 02-05-2022
    # - Small typo: none vs. None.
    # Version 1.0.0 - 01-31-2022
    # - Initial release.

    minimum_calibre_version = (5, 0, 0)
    # From https://manual.calibre-ebook.com/de/_modules/calibre/ebooks/metadata/sources/base.html
    #: Set this to True to ignore HTTPS certificate errors when connecting to this source.
    ignore_ssl_errors = True
    #: Set this to True if your plugin returns HTML formatted comments
    has_html_comments = True
    # Setting this to True means that the browser object will indicate that it supports gzip transfer encoding.
    # This can speed up downloads but make sure that the source actually supports gzip transfer encoding correctly first
    supports_gzip_transfer_encoding = False
    #: If True this source can return multiple covers for a given query
    can_get_multiple_covers = True
    #: If set to True covers downloaded by this plugin are automatically trimmed.
    auto_trim_covers = False
    # Cached cover URLs can sometimes be unreliable (i.e. the download could fail or the returned image could be
    # bogus). If that is often the case with this source, set to False
    cached_cover_url_is_reliable = True
    #: If set to True, and this source returns multiple results for a query, some of which have ISBNs and some of which
    # do not, the results without ISBNs will be ignored
    prefer_results_with_isbn = False

    # Set of capabilities supported by this plugin. Useful capabilities are: 'identify', 'cover'
    capabilities = frozenset(['identify', 'cover'])
    #: List of metadata fields that can potentially be downloaded by this plugin during the identify phase
    touched_fields = {'title', 'authors', 'series', 'series_index', 'languages', 'rating', 'publisher', 'pubdate',
                      'comments', 'tags', 'identifier:isfdb', 'identifier:isfdb-catalog', 'identifier:isfdb-title'}
    for identifier_list in EXTERNAL_IDS.items():
        # Calibre identifier type and identifier description
        touched_fields.add('identifier:{}'.format(identifier_list[0]))
    touched_fields = frozenset(touched_fields)

    #: A string that is displayed at the top of the config widget for this plugin
    # config_help_message = None
    config_help_message = _('For further explanations see isfdb3.md file.')

    # # Set config values
    # # import calibre_plugins.isfdb3.config as cfg

    REVERSELANGUAGES = {}
    for k, v in LANGUAGES.items():
        REVERSELANGUAGES[v] = k

    # User defined options. Let calibre build the gui.
    # A list of :class:`Option` objects. They will be used to automatically
    #: construct the configuration widget for this plugin
    '''
    :param name: The name of this option. Must be a valid python identifier
    :param type_: The type of this option, one of ('number', 'string', 'bool', 'choices')
    :param default: The default value for this option
    :param label: A short (few words) description of this option
    :param desc: A longer description of this option
    :param choices: A dict of possible values, used only if type='choices'. dict is of the form 
    {key:human readable label, ...}
    '''
    options = (
        Option(
            'max_results',
            'number',
            10,
            _('Maximum number of search results to download:'),
            _('This setting only applies to ISBN and title / author searches. Book records with a valid ISFDB '
              'publication and/or title ID will return exactly one result.'),
        ),
        Option(
            'max_covers',
            'number',
            10,
            _('Maximum number of covers to download:'),
            _('The maximum number of covers to download. This only applies to publication records with no cover. '
              'If there is a cover associated with the record, only that cover will be downloaded.')
        ),
        Option(
            'search_publications',
            'bool',
            True,
            _('Search ISFDB publications?'),
            _('This only applies to title / author searches. A record with a publication ID will always return '
              'a publication.')
        ),
        Option(
            'search_titles',
            'bool',
            True,
            _('Search ISFDB titles?'),
            _('This only applies to title / author searches. A record with a title ID and no publication ID '
              'will always return a title.')
        ),
        Option(
            'search_options',
            'choices',
            'contains',
            _('Search options'),
            _('Choose one of the options for search variants.'),
            {'is_exactly': 'is exactly', 'is_not_exactly': 'is not exactly', 'contains': 'contains',
             'does_not_contains': 'does not contain', 'starts_with': 'starts with', 'ends_with': 'ends with'}
        ),
        Option(
            'combine_series',
            'bool',
            True,
            _('Combine series and sub-series?'),
            _('Choosing this option will set the series field with series and sub-series (if any).')
        ),
        Option(
            'combine_series_with',
            'string',
            '.',
            _('Combine series and sub-series with'),
            _('String to concatenate series und sub-series in the series field. '
              'Examples: "." (Calibre sort character), " | ", ...')
        ),
        Option(
            'unwanted_tags',
            'string',
            '',
            _('Unwanted Tags'),
            _('Comma-seperated list of tags to ignore.')
        ),
        Option(
            'note_translations',
            'bool',
            True,
            _('Note translations in comments.'),
            _('Choosing this option will set information and links to ISFDB pages with translations in the indicated '
              'language(s), if provided.')
        ),
        Option(
            'translate_isfdb',
            'bool',
            False,
            _('Translate ISFDB.'),
            _('Choosing this option will traslate ISFDB texts.')
        ),
        # Option(
        #     'identifier_types',
        #     'choices',
        #     None,
        #     _('Identifier types'),
        #     _('Choose one or more identifier types to fetch from ISFDB in addition to the ISBN and the '
        #       'ISFDB identifiers itself.'),
        #     IDENTIFIER_TYPES,
        #     # {'dnb': 'Deutsche Nationalbibliothek', ...}
        # ),
        Option(
            'languages',
            'choices',
            'ger',
            _('Languages'),
            _('Choose one language to filter titles. English is ever set.'),
            REVERSELANGUAGES,
            # {'ger': 'German', 'spa': 'Spanish', 'fre': 'French'}
        ),
        Option(
            'log_level',
            'choices',
            'INFO',
            _('Logging level.'),
            _('ERROR = only error messages, DEBUG: all logging messages.'),
            {'ERROR': 'ERROR', 'INFO': 'INFO', 'DEBUG': 'DEBUG'},
            # {40: 'ERROR', 30: 'WARNING', 20: 'INFO', 10: 'DEBUG'},
        )
    )

    # Add built-in identifier types for isfdb (can not be touched by user)
    IDENTIFIER_TYPES.update({"isfdb-catalog": 'ISFDB catalog number',
                             "isfdb-title": 'ISFDB Title number',
                             "isfdb": 'ISFDB Publication number',
                             })

    def __init__(self, *args, **kwargs):
        super(ISFDB3, self).__init__(*args, **kwargs)
        self._publication_id_to_title_id_cache = {}

    def cache_publication_id_to_title_id(self, isfdb_id, title_id):
        with self.cache_lock:
            self._publication_id_to_title_id_cache[isfdb_id] = title_id

    def cached_publication_id_to_title_id(self, isfdb_id):
        with self.cache_lock:
            return self._publication_id_to_title_id_cache.get(isfdb_id, None)

    def dump_caches(self):
        dump = super(ISFDB3, self).dump_caches()
        with self.cache_lock:
            dump.update({
                'publication_id_to_title_id': self._publication_id_to_title_id_cache.copy(),
            })
        return dump

    def load_caches(self, dump):
        super(ISFDB3, self).load_caches(dump)
        with self.cache_lock:
            self._publication_id_to_title_id_cache.update(dump['publication_id_to_title_id'])

    def get_book_url(self, identifiers):
        # The 'isfdb id' is the publication id of the isf database
        isfdb_id = identifiers.get('isfdb', None)
        title_id = identifiers.get('isfdb-title', None)

        if isfdb_id:
            url = Publication.url_from_id(isfdb_id)
            return 'isfdb', isfdb_id, url  # The url is used (and can be accessed) in the book info window!

        if title_id:
            url = Title.url_from_id(title_id)
            return 'isfdb-title', title_id, url  # The url is used (and can be accessed) in the book info window!

        return None

    def get_cached_cover_url(self, identifiers):
        isfdb_id = identifiers.get('isfdb', None)
        if isfdb_id:
            return self.cached_identifier_to_cover_url(isfdb_id)

        # If we have multiple books with the same ISBN and no ID this may reuse the same cover for multiple books
        # But we probably won't get into this situation, so let's leave this for now
        isbn = identifiers.get('isbn', None)
        if isbn:
            return self.cached_identifier_to_cover_url(self.cached_isbn_to_identifier(isbn))

        return None

    def get_author_tokens(self, authors, only_first_author=True):
        # We override this because we don't want to strip out middle initials!
        # This *just* attempts to unscramble "surname, first name".
        if only_first_author:
            authors = authors[:1]
        for author in authors:
            if "," in author:
                parts = author.split(",")
                parts = parts[1:] + parts[:1]
                author = " ".join(parts)
            for author_token in author.split():
                yield author_token

    def clean_downloaded_metadata(self, mi):
        """
        Call this method in your plugin's identify method to normalize metadata
        before putting the Metadata object into result_queue. You can of
        course, use a custom algorithm suited to your metadata source.
        """
        docase = mi.language == 'eng'  # or mi.is_null('language')
        if docase and mi.title:
            mi.title = fixcase(mi.title)
        if docase and mi.authors:
            # ToDo: no fixcase for '(Editor)' / '(Herausgeber)'
            mi.authors = fixauthors(mi.authors)
        if docase and mi.tags:
            mi.tags = list(map(fixcase, mi.tags))
        mi.isbn = check_isbn(mi.isbn)

    def identify(self, log, result_queue, abort, title=None, authors=None, identifiers={}, timeout=30):
        """
        This method will find exactly one result if an ISFDB ID is
        present, otherwise up to the maximum searching first for the
        ISBN and then for title and author.
        """

        log.info(' ')
        log.info('*' * 40)
        log.info(_('ISFDB3 is starting...'))
        log.info(_('Log level is {0}.').format(self.prefs['log_level']))

        if self.prefs['log_level'] in 'DEBUG':
            log.debug('*** Enter ISFDB3.identify().')
            log.debug('abort={0}'.format(abort))
            log.debug('title={0}'.format(title))
            log.debug('authors={0}'.format(authors))
            log.debug('identifiers={0}'.format(identifiers))

        # For very short titles there ist a possible marker '=' as the first character in title field
        self.prefs['exact_search'] = False
        log.debug('self.prefs={0}'.format(self.prefs))
        if title:
            if title[0] == '=':
                self.prefs['exact_search'] = True
                title = title[1:]
                log.debug('title={0}'.format(title))
                log.debug('self.prefs={0}'.format(self.prefs))

        matches = set()  # A tuple of (page url, relevance)

        # If we have an ISFDB pub ID, or a title ID, we use it to construct the publication URL directly

        book_url_tuple = self.get_book_url(identifiers)
        if self.prefs['log_level'] in 'DEBUG':
            log.debug('book_url_tuple={0}'.format(book_url_tuple))

        if book_url_tuple:

            ##############################################
            # 1. Search with publication id or title id  #
            ##############################################

            id_type, id_val, url = book_url_tuple  # page type (title, pub, series), isfdb id, page url
            if url is not None:
                matches.add((url, 0))  # most relevant
                if self.prefs['log_level'] in 'DEBUG':
                    log.debug('Add match: id_type={0}, id_val={1}, url={2}.'.format(id_type, id_val, url))

            # ToDo: If only a title id is found, fetch all linked pub ids and put it in matches

            # If we have a publication id ('isfdb) and a title id (isfdb-title), cache the title id
            isfdb_id = identifiers.get('isfdb', None)
            title_id = identifiers.get('isfdb-title', None)
            if self.prefs['log_level'] in 'DEBUG':
                log.debug('isfdb_id={0}, title_id={1}.'.format(isfdb_id, title_id))
            if isfdb_id and title_id:
                self.cache_publication_id_to_title_id(isfdb_id, title_id)
        else:

            if abort.is_set():
                if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                    log.info(_('Abort is set.'))
                return

            ########################################
            # 2. Search with ISBN                  #
            ########################################

            # If there's an ISBN, search by ISBN first, then by isfdb catalog id
            isbn = check_isbn(identifiers.get('isbn', None))
            catalog_id = identifiers.get('isfdb-catalog', None)

            # Fall back to non-ISBN catalog ID -- ISFDB uses the same field for both.
            if isbn or catalog_id:
                # Fetching publications
                query = PublicationsList.url_from_isbn(isbn or catalog_id, log, self.prefs)
                stubs = PublicationsList.from_url(self.browser, query, timeout, log, self.prefs)

                for stub in stubs:
                    if stub["url"] is not None:
                        matches.add((stub["url"], 1))
                        if self.prefs['log_level'] in 'DEBUG':
                            log.debug('Add match: {0}.'.format(stub["url"]))
                        if len(matches) >= self.prefs["max_results"]:
                            break

                if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                    log.info(_('{0} matches with isbn and/or isfdb-catalog ids.').format(len(matches)))

            if abort.is_set():
                if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                    log.info(_('Abort is set.'))
                return

            ########################################
            # Search with title and author(s)      #
            ########################################

            if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                log.info(_('No id(s) given. Trying a search with title and author(s).'))

            # Keyword search for magazines?
            # Title:The Magazine of Fantasy and Science Fiction Year:1955 Month:03 Week: Vol:8 No:3
            possible_keywords = ['Title:', 'Year:', 'Month:', 'Week:', 'Vol:', 'No:']
            found_keywords = []
            for x in possible_keywords:
                if x in title:
                    found_keywords.append(x)
            if any(found_keywords):
                # Special search for magazine
                query = TitleList.url_from_title_with_keywords(title, found_keywords, log, self.prefs)
                stubs = TitleList.from_url(self.browser, query, timeout, log, self.prefs)
                if self.prefs['log_level'] in 'DEBUG':
                    log.debug('{0} stubs found with TitleList.from_url().'.format(len(stubs)))
                # Sort stubs in ascending order by title date
                sorted_stubs = sorted(stubs, key=lambda k: k['date'])
                if self.prefs['log_level'] in 'DEBUG':
                    log.debug('sorted_stubs from TitleList.from_url(): {0}.'.format(sorted_stubs))
                for stub in sorted_stubs:
                    relevance = 2
                    # if stripped(stub["title"]) == stripped(title):  # ???
                    if stub["title"].strip() == title.strip():
                        relevance = 0
                    if self.prefs['log_level'] in 'DEBUG':
                        log.debug('stub["url"]={0}.'.format(stub["url"]))
                    if stub["url"] is not None:
                        matches.add((stub["url"], relevance))
                        if self.prefs['log_level'] in 'DEBUG':
                            log.debug('Add match from title list: {0}.'.format(stub["url"]))
                        if len(matches) >= self.prefs["max_results"]:
                            break
                        ######################################################################
                        # Fetch all linked pub records for this title,                       #
                        # even if the book title is not identical with the publication title #
                        ######################################################################
                        stub_with_pubs = Title.from_url(self.browser, stub["url"], timeout, log, self.prefs)
                        if self.prefs['log_level'] in 'DEBUG':
                            log.debug('stub_with_pubs after Title.from_url()={0}'.format(stub_with_pubs))
                        if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                            log.info(_('Fetching all linked pub records...'))
                        for pubno in stub_with_pubs['publications']:
                            # We have a publication id and a title id, so cache the title id
                            self.cache_publication_id_to_title_id(pubno, stub_with_pubs['isfdb-title'])
                            # If the title found in isfdb's title record is identical to the metadata title,
                            # promote this title record
                            relevance = 2
                            # if stripped(stub["title"]) == stripped(title):  # ???
                            if stub["title"].strip() == title.strip():
                                relevance = 0
                            url = Publication.url_from_id(pubno)
                            matches.add((url, relevance))
                            if self.prefs['log_level'] in 'DEBUG':
                                log.debug('Add match from publications list: {0}.'.format(url))
                            if len(matches) >= self.prefs["max_results"]:
                                break

            else:

                def stripped(s):
                    return "".join(c.lower() for c in s if c.isalpha() or c.isspace())

                authors = authors or []
                author_tokens = self.get_author_tokens(authors, only_first_author=True)
                author = ' '.join(author_tokens)
                title_tokens = self.get_title_tokens(title, strip_joiners=False, strip_subtitle=True)
                title = ' '.join(title_tokens)
                if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                    log.info(_('Searching with author={0}, title={1}.').format(author, title))

                ##################################################
                # 3a. Search with title and author(s) for titles #
                ##################################################

                # If we still haven't found enough results, also search *titles* by title and author
                if len(matches) < self.prefs["max_results"] and self.prefs["search_titles"]:
                    # title=In The Vault, author=H. P. Lovecraft
                    # Fetch a title list
                    query = TitleList.url_from_title_and_author(title, author, log, self.prefs)
                    # The title list contains a language col
                    stubs = TitleList.from_url(self.browser, query, timeout, log, self.prefs)
                    if self.prefs['log_level'] in 'DEBUG':
                        log.debug('{0} stubs found with TitleList.from_url().'.format(len(stubs)))

                    # Sort stubs in ascending order by title date
                    sorted_stubs = sorted(stubs, key=lambda k: k['date'])
                    if self.prefs['log_level'] in 'DEBUG':
                        log.debug('sorted_stubs from TitleList.from_url(): {0}.'.format(sorted_stubs))
                        # [{'title': 'In the Vault', 'url': 'http://www.isfdb.org/cgi-bin/title.cgi?41896', 'authors': ['H. P. Lovecraft']},
                        # {'title': 'In the Vault', 'url': 'http://www.isfdb.org/cgi-bin/title.cgi?2946687', 'authors': ['H. P. Lovecraft']}]

                    for stub in sorted_stubs:
                        # log.info('stub={0}'.format(stub))
                        # If the title found in isfdb's title record is identical to the metadata title,
                        # promote this title record
                        relevance = 2
                        if stripped(stub["title"]) == stripped(title):
                            relevance = 0

                        if self.prefs['log_level'] in 'DEBUG':
                            log.debug('stub["url"]={0}.'.format(stub["url"]))
                        # Workaround for:
                        # titlelist.from_url 'http://www.isfdb.org/cgi-bin/adv_search_results.cgi?ORDERBY=title_title&START=0&TYPE=Title&USE_1=title_title&OPERATOR_1=contains&TERM_1=Der+Sternenj%E4ger&USE_2=author_canonical&OPERATOR_2=contains&TERM_2=Kurt+Brand&CONJUNCTION_1=AND'. Found 2 titles.
                        # matches={('http://www.isfdb.org/cgi-bin/title.cgi?1816860', 0), ('http://www.isfdb.org/cgi-bin/title.cgi?1816862', 0), (None, 0)}
                        if stub["url"] is not None:
                            matches.add((stub["url"], relevance))
                            if self.prefs['log_level'] in 'DEBUG':
                                log.debug('Add match from title list: {0}.'.format(stub["url"]))
                            if len(matches) >= self.prefs["max_results"]:
                                break

                            ######################################################################
                            # Fetch all linked pub records for this title,                       #
                            # even if the book title is not identical with the publication title #
                            ######################################################################

                            stub_with_pubs = Title.from_url(self.browser, stub["url"], timeout, log, self.prefs)
                            if self.prefs['log_level'] in 'DEBUG':
                                log.debug('stub_with_pubs after Title.from_url()={0}'.format(stub_with_pubs))
                            # stub one delivers:
                            # {'isfdb-title': '2946687', 'title': 'In the Vault', 'authors': ['H. P. Lovecraft'],
                            # 'pubdate': datetime.datetime(2018, 1, 1, 2, 0), 'type': 'SHORTFICTION', 'tags': ['short fiction'],
                            # 'language': 'eng', 'comments': '<br />Quelle: http://www.isfdb.org/cgi-bin/title.cgi?2946687',
                            # 'publications': ['868274']}
                            # stub two delivers:
                            # {'isfdb-title': '41896', 'title': 'In the Vault', 'authors': ['H. P. Lovecraft'],
                            # 'pubdate': datetime.datetime(1925, 11, 1, 2, 0), 'type': 'SHORTFICTION', 'tags': ['short fiction', 'short story', 'horror', 'cemetery', 'thriller'],
                            # 'length': 'short story', 'webpages': 'http://en.wikipedia.org/wiki/In_the_Vault', 'language': 'eng',
                            # 'comments': '<br />Quelle: http://www.isfdb.org/cgi-bin/title.cgi?41896',
                            # 'publications': ['706981', '61879', '273106', '618032', '44960', '359388', '618034', '297445', '297440', '367691', '302799', '309509', '18059', '11658', '38934', '145971', '282647', '248690', '306035', '237633', '120561', '282648', '591894', '237637', '564083', '609374', '282649', '309179', '264815', '682730', '423983', '396460', '824200', '416243', '359195', '38935', '789800', '391376', '35792', '282521', '282721', '282522', '308779', '601355', '170301', '185181', '35793', '359410', '282722', '303253', '78446', '65445', '277217', '64078', '567162', '791582', '555987', '379243', '325738', '287198', '249955', '446578', '293057', '356003', '332409', '374550', '469219', '570586', '463546', '531112', '529150', '593595', '774732', '579248', '623804', '623778', '648278', '776874', '776870', '666333', '765111', '779323', '745178', '805986', '806173', '239285', '288973', '352022', '431714', '506197', '511485', '514714', '560685', '855800', '706744', '708866']}
                            # Fetching all linked pub records
                            if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                                log.info(_('Fetching all linked pub records...'))
                            for pubno in stub_with_pubs['publications']:
                                # We have a publication id and a title id, so cache the title id
                                self.cache_publication_id_to_title_id(pubno, stub_with_pubs['isfdb-title'])
                                # If the title found in isfdb's title record is identical to the metadata title,
                                # promote this title record
                                relevance = 2
                                if stripped(stub["title"]) == stripped(title):
                                    relevance = 0
                                url = Publication.url_from_id(pubno)
                                matches.add((url, relevance))
                                if self.prefs['log_level'] in 'DEBUG':
                                    log.debug('Add match from publications list: {0}.'.format(url))
                                if len(matches) >= self.prefs["max_results"]:
                                    break

                if abort.is_set():
                    if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                        log.info(_('Abort is set.'))
                    return

                ########################################################
                # 3b. Search with title and author(s) for publications #
                ########################################################

                # Why this? (bertholdm)
                # If we haven't reached the maximum number of results, also search by title and author
                if len(matches) < self.prefs["max_results"] and self.prefs["search_publications"]:

                    query = PublicationsList.url_from_title_and_author(title, author, log, self.prefs)
                    stubs = PublicationsList.from_url(self.browser, query, timeout, log, self.prefs)
                    # For the title "In the Vault" by "H. P. Lovecraft" no publications are found by title.
                    # Although the story shows up in 95 publications, but these have other titles
                    # (magazine title, anthology title, ...)
                    if stubs is None:
                        if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                            log.info(_('No publications found with title and author(s) search for »{0}« by {1}.').
                                     format(title, author))

                    # Sort stubs in ascending order by pub year
                    sorted_stubs = sorted(stubs, key=lambda k: k['pub_year'])
                    if self.prefs['log_level'] in 'DEBUG':
                        log.debug('sorted_stubs from PublicationsList.from_url(): {0}.'.format(sorted_stubs))

                    # for stub in stubs:
                    for stub in sorted_stubs:
                        relevance = 2
                        if stripped(stub["title"]) == stripped(title):
                            relevance = 0  # this is the exact title
                        if stub["url"] is not None:
                            matches.add((stub["url"], relevance))
                            if self.prefs['log_level'] in 'DEBUG':
                                log.debug('Add match: {0}.'.format(stub["url"]))
                            if len(matches) >= self.prefs["max_results"]:
                                break

                if abort.is_set():
                    if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                        log.info(_('Abort is set.'))
                    return

            # if abort.is_set():
            #     if self.loc_prefs['log_level'] in ('DEBUG', 'INFO'):
            #         log.info(_('Abort is set.'))
            #     return

            # See: ToDo: In case id field has title id: fetch all linked pub ids and put in matches list (above)

        # Transfer the search results to the workers

        if self.prefs['log_level'] in ('DEBUG', 'INFO'):
            log.info(_('Matches found (URL, relevance): {0}.').format(matches))
        # {('http://www.isfdb.org/cgi-bin/title.cgi?41896', 0), ('http://www.isfdb.org/cgi-bin/title.cgi?2946687', 0)}.
        if self.prefs['log_level'] in ('DEBUG', 'INFO'):
            log.info(_('Starting workers...'))

        workers = [Worker(m_url, result_queue, self.browser, log, m_rel, self, self.prefs, timeout) for (m_url, m_rel)
                   in matches]

        for w in workers:
            w.start()
            # Don't send all requests at the same time
            time.sleep(0.1)

        while not abort.is_set():
            a_worker_is_alive = False
            for w in workers:
                w.join(0.2)
                if abort.is_set():
                    break
                if w.is_alive():
                    a_worker_is_alive = True
            if not a_worker_is_alive:
                break

    def download_cover(self, log, result_queue, abort, title=None, authors=None, identifiers={}, timeout=30,
                       get_best_cover=False):
        urls = []

        cached_url = self.get_cached_cover_url(identifiers)
        title_id = identifiers.get("isfdb-title")

        if self.prefs['log_level'] in 'DEBUG':
            log.debug('*** Enter download_cover().')
            log.debug("cached_url={0}, title_id={1}.".format(cached_url, title_id))

        if not cached_url and not title_id:
            if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                log.info(_("Not enough information. Running identify."))
            rq = Queue()
            self.identify(log, rq, abort, title, authors, identifiers, timeout)

            if abort.is_set():
                return

            results = []

            while True:
                try:
                    results.append(rq.get_nowait())
                except Empty:
                    break

            if len(results) == 1:
                # Found a specific publication or title; try to get cached url or title
                # log.info('Found a specific publication or title; try to get cached url or title.')
                # log.info('results[0]={}'.format(results[0]))
                mi = results[0]
                cached_url = self.get_cached_cover_url(mi.identifiers)
                title_id = mi.identifiers.get("isfdb-title")
            else:
                # Try to get all title results
                # log.info('Try to get {0} title results.'.format(len(results)))
                for mi in results:
                    title_id = mi.identifiers.get("isfdb-title")
                    if title_id:
                        break

        if cached_url:
            if self.prefs['log_level'] in 'DEBUG':
                log.debug("Using cached cover URL.")
            urls.append(cached_url)

        elif title_id:
            if self.prefs['log_level'] in 'DEBUG':
                log.debug("Finding all title covers.")
            title_covers_url = TitleCovers.url_from_id(title_id)
            urls.extend(TitleCovers.from_url(self.browser, title_covers_url, timeout, log, self.prefs))

        else:
            # Everything is spiders
            if self.prefs['log_level'] in ('DEBUG', 'INFO', 'ERROR'):
                log.error(_("We were unable to find any covers."))

        if abort.is_set():
            return

        if self.prefs['log_level'] in 'DEBUG':
            log.debug("Going to download covers from {0}.".format(urls))

        self.download_multiple_covers(title, authors, urls, get_best_cover, timeout, result_queue, abort, log)


class Worker(Thread):
    """
    Get book details from ISFDB book page in a separate thread.
    """

    def __init__(self, url, result_queue, browser, log, relevance, plugin, prefs, timeout=20):
        Thread.__init__(self)
        self.daemon = True
        self.url = url
        self.result_queue = result_queue
        self.log = log
        self.timeout = timeout
        self.relevance = relevance
        self.plugin = plugin
        self.browser = browser.clone_browser()
        self.prefs = prefs

    def run(self):

        if self.prefs['log_level'] in 'DEBUG':
            self.log.debug('*** Enter Worker.run()')

        # ToDo:
        # why not this approach for search with title and/or author(s):
        # 1. search for title record(s) (ambiguous titles) and save title record info
        # 2. for each title record search all publications (following links in publications container)
        # 3. for each publication record fetch publication data and series data and merge with title data
        # 4. present the publications found in calibre gui

        # this would be better than exact title search from publication(s), wich will fail in some cases:
        # Title: Best SF Stories from New Worlds 7
        # Publication: Best S.F. Stories from New Worlds 7

        try:
            if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                self.log.info(_('Worker parsing ISFDB url: %r') % self.url)

            start = time.time()
            pub = {}

            if Publication.is_type_of(self.url, self.log, self.prefs):
                if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                    self.log.info(_("This url is a Publication."))
                pub = Publication.from_url(self.browser, self.url, self.timeout, self.log, self.prefs)
                if self.prefs['log_level'] in 'DEBUG':
                    self.log.debug("pub after Publication.from_url()={0}".format(pub))
                    # {'isfdb': '675613', 'title': 'Die Hypno-Sklaven', 'authors': ['Kurt Mahr'], 'author_string': 'Kurt Mahr',
                    # 'pubdate': datetime.datetime(1975, 6, 3, 2, 0), isfdb-catalog': 'TA199',
                    # ''publisher': 'Pabel-Moewig', 'series': 'Terra Astra', 'series_index': 199,
                    # 'type': 'CHAPBOOK', 'dnb': '1140457357', 'comments': '...

                title_id = self.plugin.cached_publication_id_to_title_id(pub["isfdb"])
                if not title_id and "isfdb-title" in pub:
                    title_id = pub["isfdb-title"]
                if self.prefs['log_level'] in 'DEBUG':
                    self.log.debug("title_id={0}".format(title_id))

                if not title_id:
                    if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                        self.log.info(
                            _("Could not find title ID in original metadata or on publication page. Searching for title."))
                    if "author_string" not in pub:
                        self.log.error(_('Warning: pub["author_string"] is not set.'))
                        pub["author_string"] = ''
                    if "title" in pub:
                        title = pub["title"]
                    else:
                        title = ''
                    author = pub["author_string"]
                    ttype = pub["type"]

                    query = TitleList.url_from_exact_title_author_and_type(title, author, ttype, self.log, self.prefs)
                    stubs = TitleList.from_url(self.browser, query, self.timeout, self.log, self.prefs)

                    title_ids = [Title.id_from_url(t["url"]) for t in stubs]
                else:
                    title_ids = [title_id]

                for title_id in title_ids:
                    title_url = Title.url_from_id(title_id)
                    if self.prefs['log_level'] in 'DEBUG':
                        self.log.debug('title_url={0}'.format(title_url))

                    if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                        self.log.info(_("Fetching additional title information from %s") % title_url)
                    tit = Title.from_url(self.browser, title_url, self.timeout, self.log, self.prefs)
                    if self.prefs['log_level'] in 'DEBUG':
                        self.log.debug('tit={0}'.format(tit))

                    if pub["isfdb"] in tit["publications"]:
                        if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                            self.log.info(_("This is the exact title! Merge title and publication info."))

                        # Merge title and publication info, with publication info taking precedence

                        # ToDo: Merge title info and linked publication(s) info, even if the book title is not exact
                        #  identical in title record and linked publication record(s):
                        # Title: Best S.F. Stories from New Worlds / # Title Record # 36317
                        # Publication: Best S.F. Stories from New Worlds / Publication Record # 35921
                        # Publication: The Best SF Stories from New Worlds / Publication Record # 275065

                        if "series" in tit:
                            if "series" not in pub:
                                pub["series"] = tit["series"]

                        tit.update(pub)
                        pub = tit
                        if self.prefs['log_level'] in 'DEBUG':
                            self.log.debug('pub={0}'.format(pub))
                        break  # exact title for publication found, so quit the title loop

                    if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                        self.log.info(_("This is not the correct title."))

                else:
                    if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                        self.log.info(_("We could not find a title record for this publication."))

            elif Title.is_type_of(self.url, self.log, self.prefs):

                if self.prefs['log_level'] in ('DEBUG', 'INFO'):
                    self.log.info(_("This url is a Title."))
                pub = Title.from_url(self.browser, self.url, self.timeout, self.log, self.prefs)
                if self.prefs['log_level'] in 'DEBUG':
                    self.log.debug('pub after Title.from_url()={0}'.format(pub))
                # run one delivers:
                # {'isfdb-title': '2946687', 'title': 'In the Vault', 'authors': ['H. P. Lovecraft'],
                # 'pubdate': datetime.datetime(2018, 1, 1, 2, 0), 'type': 'SHORTFICTION', 'tags': ['short fiction'],
                # 'language': 'eng', 'comments': '<br />Quelle: http://www.isfdb.org/cgi-bin/title.cgi?2946687',
                # 'publications': ['868274']}
                # run two delivers:
                # {'isfdb-title': '41896', 'title': 'In the Vault', 'authors': ['H. P. Lovecraft'],
                # 'pubdate': datetime.datetime(1925, 11, 1, 2, 0), 'type': 'SHORTFICTION', 'tags': ['short fiction', 'short story', 'horror', 'cemetery', 'thriller'],
                # 'length': 'short story', 'webpages': 'http://en.wikipedia.org/wiki/In_the_Vault',
                # 'language': 'eng', 'comments': '<br />Quelle: http://www.isfdb.org/cgi-bin/title.cgi?41896',
                # 'publications': ['706981', '61879', '273106', '618032', '44960', '359388', '618034', '297445', '297440',
                # '367691', '302799', '309509', '18059', '11658', '38934', '145971', '282647', '248690', '306035', '237633',
                # '120561', '282648', '591894', '237637', '564083', '609374', '282649', '309179', '264815', '682730',
                # '423983', '396460', '824200', '416243', '359195', '38935', '789800', '391376', '35792', '282521',
                # '282721', '282522', '308779', '601355', '170301', '185181', '35793', '359410', '282722', '303253',
                # '78446', '65445', '277217', '64078', '567162', '791582', '555987', '379243', '325738', '287198', '249955',
                # '446578', '293057', '356003', '332409', '374550', '469219', '570586', '463546', '531112', '529150',
                # '593595', '774732', '579248', '623804', '623778', '648278', '776874', '776870', '666333', '765111',
                # '779323', '745178', '805986', '806173', '239285', '288973', '352022', '431714', '506197', '511485',
                # '514714', '560685', '855800', '706744', '708866']}

            else:
                if self.prefs['log_level'] in ('DEBUG', 'INFO', 'ERROR'):
                    self.log.error(_("Out of cheese error! Unrecognised url!"))
                return

            # if not pub.get("title") or not pub.get("authors"):
            if not pub.get("title") and not pub.get("authors"):
                if self.prefs['log_level'] in ('DEBUG', 'INFO', 'ERROR'):
                    self.log.error(_('Insufficient metadata found for %r') % self.url)
                return

            if len(pub["authors"]) == 0:
                pub["authors"] = [_('Unknown')]

            # Put extracted metadata in queue
            if self.prefs['log_level'] in 'DEBUG':
                self.log.debug('Put extracted metadata in queue.')

            # Initialize the book queue
            mi = Metadata(pub["title"], pub["authors"])

            # Avoid Calibre's default title and/or author(s) merge behavior by distinguish titles
            if pub.get("isfdb-title"):
                mi.title = mi.title + ' (title #' + str(pub.get("isfdb-title")) + ')'
                if self.prefs['log_level'] in 'DEBUG':
                    self.log.debug('Adding book title id to avoid merging: {0}'.format(mi.title))

            # Set isfdb3 identifiers
            if pub.get("isfdb"):
                mi.set_identifier('isfdb', pub['isfdb'])
            if pub.get("isfdb-catalog"):
                mi.set_identifier('isfdb-catalog', pub['isfdb-catalog'])
            if pub.get("isfdb-title"):
                mi.set_identifier('isfdb-title', pub['isfdb-title'])

            # Set isfdb.org external identifiers
            if 'identifiers' in pub:  # external identifiers came only from publication records, not title records
                if self.prefs['log_level'] in 'DEBUG':
                    self.log.debug('pub["identifiers"]={0}'.format(pub["identifiers"]))
                # if 'isbn' in pub["identifiers"]:
                #    mi.isbn = pub['identifiers']['isbn']
                for identifier_type, identifier_number in pub['identifiers'].items():
                    if self.prefs['log_level'] in 'DEBUG':
                        self.log.debug('identifier_type:identifier_number={0}:{1}'.
                                       format(identifier_type, identifier_number))
                    mi.set_identifier(str(identifier_type), str(identifier_number))

            # Fill object mi with the data from the metadata source, digged out in 'objects.py'

            # Remove unwanted tags from tag list
            # ToDo: Save tags already in metadata?
            unwanted_tags = [x.strip() for x in self.prefs['unwanted_tags'].split(',')]
            if self.prefs['log_level'] in 'DEBUG':
                self.log.debug('pub["tags"]={0}'.format(pub["tags"]))
            pub["tags"] = [x for x in pub["tags"] if x not in unwanted_tags]
            if self.prefs['log_level'] in 'DEBUG':
                self.log.debug('pub["tags"]={0}'.format(pub["tags"]))
            # Remove duplicates from tag list
            pub["tags"] = list(dict.fromkeys(pub["tags"]))
            if self.prefs['log_level'] in 'DEBUG':
                self.log.debug('pub["tags"]={0}'.format(pub["tags"]))
            # for attr in ("publisher", "pubdate", "comments", "series", "series_index", "tags"):
            for attr in ("publisher", "pubdate", "comments", "series", "series_index", "tags", "language", "rating"):
                if attr in pub:
                    if self.prefs['log_level'] in 'DEBUG':
                        self.log.debug('Set metadata for attribute {0}: {1}'.format(attr, pub[attr]))
                    setattr(mi, attr, pub[attr])

            # TODO: we need a test which has a title but no cover
            if pub.get("cover_url"):
                self.plugin.cache_identifier_to_cover_url(pub["isfdb"], pub["cover_url"])
                mi.has_cover = True

            mi.source_relevance = self.relevance

            # pub search gives:
            # Add match: http://www.isfdb.org/cgi-bin/pl.cgi?742977.
            # Add match: http://www.isfdb.org/cgi-bin/pl.cgi?503917.
            # Add match: http://www.isfdb.org/cgi-bin/pl.cgi?443592.
            # Add match: http://www.isfdb.org/cgi-bin/pl.cgi?492635.
            # Add match: http://www.isfdb.org/cgi-bin/pl.cgi?493580.
            # Add match: http://www.isfdb.org/cgi-bin/pl.cgi?636903.
            # title search gives:
            # Add match: http://www.isfdb.org/cgi-bin/title.cgi?2639044.
            # Add match: http://www.isfdb.org/cgi-bin/title.cgi?1477793.
            # Add match: http://www.isfdb.org/cgi-bin/title.cgi?2048538.

            # With Calibre's default behavior (merge all sources with identical titles and author(s)),
            # the following titles where displayed in calibre GUI
            # stub={'title': 'Vorwort (Zur besonderen Verwendung)', 'authors': ['K. H. Scheer'], 'url': 'http://www.isfdb.org/cgi-bin/title.cgi?2639044'}
            # stub={'title': 'Zur besonderen Verwendung', 'authors': ['K. H. Scheer'], 'url': 'http://www.isfdb.org/cgi-bin/title.cgi?1477793'}
            # stub={'title': 'Zur besonderen Verwendung (excerpt)', 'authors': ['K. H. Scheer'], 'url': 'http://www.isfdb.org/cgi-bin/title.cgi?2048538'}
            # (To be honest, only stub #2 contains really a book title. Vorwort (preface) and excerpt are not what we want)
            # And all(!) pubs are crumbled in one!

            # So, if we want not to merge metadata results on title and/or author(s) as coded alin Calibre's merge_metadata_results()

            # (See https://github.com/kovidgoyal/calibre/blob/master/src/calibre/ebooks/metadata/sources/identify.py and
            # as stated in help text for check box "more than one entry per source":
            # "Normally, the metadata download system will keep only a single result per metadata source.
            # This option will cause it to keep all results returned from every metadata source. Useful if you only use
            # one or two sources and want to select individual results from them by hand.
            # Note that result with identical title/author/identifiers are still merged."
            # See also:
            # https://www.mobileread.com/forums/showthread.php?t=224546
            # http://www.mobileread.mobi/forums/showthread.php?t=336308)

            # we have to qualify the title field with distinguish patterns before we put the metadata in the request queue.

            # Avoid Calibre's default title and/or author(s) merge behavior by distinguish titles
            if pub.get("isfdb"):
                # If title has already a 'title #' qualifier, remove it
                stripped_title = re.sub(r' \(title #[0-9]*\)', '', mi.title).strip()
                if self.prefs['log_level'] in 'DEBUG':
                    self.log.debug('mi.title={0}, stripped_title={1}'.format(mi.title, stripped_title))
                mi.title = stripped_title + ' (pub #' + str(pub.get("isfdb")) + ')'
                if self.prefs['log_level'] in 'DEBUG':
                    self.log.debug('Adding book publication id to avoid merging: {0}'.format(mi.title))

            # TODO: do we actually want / need this?
            if pub.get("isfdb") and pub.get("isbn"):
                self.plugin.cache_isbn_to_identifier(pub["isbn"], pub["isfdb"])

            self.plugin.clean_downloaded_metadata(mi)
            # self.log.info('Finally formatted metadata={0}'.format(mi))
            # self.log.info(''.join([char * 20 for char in '#']))
            # Put metadata in Calibre's result queue
            self.result_queue.put(mi)
            end = time.time()
            if self.prefs['log_level'] in 'DEBUG':
                self.log.debug('Elapsed time: {0}'.format(end - start))

        except Exception as e:
            if self.prefs['log_level'] in ('DEBUG', 'INFO', 'ERROR', 'EXCEPTION'):
                self.log.exception(_('Worker failed to fetch and parse url %r with error %r') % (self.url, e))
            # if self.prefs['log_level'] in 'DEBUG':
            #     self.log.debug('Elapsed time: {0}'.format(end - start))


if __name__ == '__main__':  # tests
    # To run these test use:
    # calibre-debug -e __init__.py
    from calibre.ebooks.metadata.sources.test import (test_identify_plugin, title_test, authors_test)

    # Test the plugin.
    # TODO: new test cases
    # by catalog id
    # by title id
    # multiple authors
    # anthology
    # with cover
    # without cover
    test_identify_plugin(ISFDB3.name,
                         [
                             (  # By ISFDB
                                 {'identifiers': {'isfdb': '262210'}},
                                 [title_test('The Silver Locusts', exact=True), authors_test(['Ray Bradbury'])]
                             ),
                             (  # By ISBN
                                 {'identifiers': {'isbn': '0330020420'}},
                                 [title_test('All Flesh Is Grass', exact=True), authors_test(['Clifford D. Simak'])]
                             ),
                             (  # By author and title
                                 {'title': 'The End of Eternity', 'authors': ['Isaac Asimov']},
                                 [title_test('The End of Eternity', exact=True), authors_test(['Isaac Asimov'])]
                             ),

                         ], fail_missing_meta=False)
