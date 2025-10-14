#!/usr/bin/env python3

import datetime
# import gettext
import re
from urllib.parse import urlencode, unquote

from lxml import etree
from lxml.html import fromstring, tostring

from calibre.library.comments import sanitize_comments_html
from calibre.utils.cleantext import clean_ascii_chars
from calibre.utils.config import JSONConfig
# import calibre_plugins.isfdb3.myglobals
# https://www.mobileread.com/forums/showthread.php?t=344649
from calibre_plugins.isfdb3.myglobals import (TYPE_TO_TAG, LANGUAGES, LOCALE_LANGUAGE_CODE, LOCALE_COUNTRY,
                                              EXTERNAL_IDS, TRANSLATION_REPLACINGS)

# Activate GETTEXT
# This works in test file:
#     import gettext
#     de = gettext.translation('gettext_test', localedir='locale', languages=['de'])
#     # This installs the function _() in Python’s builtins namespace, based on domain and localedir which are passed
#     # to the function translation().
#     de.install('gettext_test')
#     _ = de.gettext
#     print(gettext.find('gettext_test', localedir='locale', languages=['de'], all=False))
load_translations()
# _ = gettext.gettext  # is already done by load_translations()

prefs = JSONConfig('plugins/ISFDB3')

def get_language_name(search_code):
    # for language_name, language_code in myglobals.LANGUAGES.items():
    for language_name, language_code in LANGUAGES.items():
        if language_code == search_code:
            return language_name

def is_roman_numeral(numeral):
    numeral = {c for c in numeral.upper()}
    valid_roman_numerals = {c for c in "MDCLXVI"}
    return not numeral - valid_roman_numerals


# Alternate approach:
# def is_roman_numeral(numeral):
#     pattern = re.compile(r"^M{0,3}(CM|CD|D?C{0,3})?(XC|XL|L?X{0,3})?(IX|IV|V?I{0,3})?$", re.VERBOSE)
#     if re.match(pattern, numeral):
#         return True
#     return False

def roman_to_int(numeral):
    roman_symbol_map = dict(I=1, V=5, X=10, L=50, C=100, D=500, M=1000)
    numeral = numeral.upper()
    result = 0
    last_val = 0
    last_count = 0
    subtraction = False
    for symbol in numeral[::-1]:
        value = roman_symbol_map.get(symbol)
        if not value:
            return 0  # raise Exception('incorrect symbol')
        if last_val == 0:
            last_count = 1
            last_val = value
        elif last_val == value:
            last_count += 1
        else:
            result += (-1 if subtraction else 1) * last_val * last_count
            subtraction = last_val > value
            last_count = 1
            last_val = value
    return result + (-1 if subtraction else 1) * last_val * last_count

def season_to_int(name):
    season_names = ['Spring', 'Summer', 'Fall', 'Winter']
    if name in season_names:
        return 1 + season_names.index(name)
    return 0

# Kovid: No, metadata plugins run in a separate thread and have no access to the database.
# The only metadata that is made available to them is title, authors and identifiers.

def remove_node(child, keep_content=False):
    """
    Remove an XML element, preserving its tail text.

    :param child: XML element to remove
    :param keep_content: ``True`` to keep child text and sub-elements.
    """
    parent = child.getparent()
    parent_text = parent.text or u""
    prev_node = child.getprevious()
    if keep_content:
        # insert: child text
        child_text = child.text or u""
        if prev_node is None:
            parent.text = u"{0}{1}".format(parent_text, child_text) or None
        else:
            prev_tail = prev_node.tail or u""
            prev_node.tail = u"{0}{1}".format(prev_tail, child_text) or None
        # insert: child elements
        index = parent.index(child)
        parent[index:index] = child[:]
    # insert: child tail
    parent_text = parent.text or u""
    prev_node = child.getprevious()
    child_tail = child.tail or u""
    if prev_node is None:
        parent.text = u"{0}{1}".format(parent_text, child_tail) or None
    else:
        prev_tail = prev_node.tail or u""
        prev_node.tail = u"{0}{1}".format(prev_tail, child_tail) or None
    # remove: child
    parent.remove(child)


class ISFDBObject(object):

    @classmethod
    def root_from_url(cls, browser, url, timeout, log, prefs):
        if prefs['log_level'] in 'DEBUG':
            log.debug('*** Enter ISFDBObject.root_from_url().')
            log.debug('url={0}'.format(url))
        response = browser.open_novisit(url, timeout=timeout)
        location = response.geturl()  # guess url in case of redirection
        raw = response.read()
        raw = raw.decode('iso_8859_1', 'ignore')  # site encoding is iso-8859-1
        return location, fromstring(clean_ascii_chars(raw))


class SearchResults(ISFDBObject):
    # URL = 'http://www.isfdb.org/cgi-bin/adv_search_results.cgi?'  # advanced search
    URL = 'https://www.isfdb.org/cgi-bin/adv_search_results.cgi?'  # advanced search
    TYPE = None

    @classmethod
    def url_from_params(cls, params, log, loc_prefs):

        # URL = 'http://www.isfdb.org/cgi-bin/adv_search_results.cgi?'
        URL = 'https://www.isfdb.org/cgi-bin/adv_search_results.cgi?'

        if loc_prefs['log_level'] in 'DEBUG':
            log.debug("*** Enter SearchResults.url_from_params()")
            log.debug('URL={0}'.format(URL))
            log.debug('params={0}'.format(params))

        # return cls.url + urlencode(params)  # Default encoding is utf-8, but ISFDB site is on iso-8859-1 (Latin-1)
        # Example original title with german umlaut: "Überfall vom achten Planeten"
        # Default urlencode() encodes:
        # https://www.isfdb.org/cgi-bin/adv_search_results.cgi?ORDERBY=title_title&START=0&TYPE=Title&USE_1=title_title&OPERATOR_1=contains&TERM_1=%C3%9Cberfall+vom+achten+Planeten&USE_2=author_canonical&OPERATOR_2=contains&TERM_2=Staff+Caine&CONJUNCTION_1=AND
        # and leads to "No records found"
        # website has <meta http-equiv="content-type" content="text/html; charset=iso-8859-1">
        # search link should be (encoded by isfdb.org search form itself):
        # isfdb.org: https://www.isfdb.org/cgi-bin/adv_search_results.cgi?USE_1=title_title&O_1=contains&TERM_1=%DCberfall+vom+achten+Planeten&C=AND&USE_2=title_title&O_2=exact&TERM_2=&USE_3=title_title&O_3=exact&TERM_3=&USE_4=title_title&O_4=exact&TERM_4=&USE_5=title_title&O_5=exact&TERM_5=&USE_6=title_title&O_6=exact&TERM_6=&USE_7=title_title&O_7=exact&TERM_7=&USE_8=title_title&O_8=exact&TERM_8=&USE_9=title_title&O_9=exact&TERM_9=&USE_10=title_title&O_10=exact&TERM_10=&ORDERBY=title_title&ACTION=query&START=0&TYPE=Title
        # log.info("urlencode(params, encoding='iso-8859-1')={0}".format(urlencode(params, encoding='iso-8859-1')))
        try:
            # return cls.url + urlencode(params, encoding='iso-8859-1')
            return URL + urlencode(params, encoding='iso-8859-1')
        except UnicodeEncodeError as e:
            # unicode character in search string. Example: Unicode-Zeichen „’“ (U+2019, Right Single Quotation Mark)
            log.error(_('Error while encoding {0}: {1}.').format(params, e))
            encoded_params = urlencode(params, encoding='iso-8859-1', errors='replace')
            # cut the search string before the non-iso-8859-1 character (? is the encoding replae char)
            encoded_params = encoded_params.split('%3F')[0]
            log.info(_('Truncate the search string at the error position and search with the substring: {0}.').format(
                encoded_params))
            return URL + encoded_params

    @classmethod
    def simple_url_from_params(cls, params, log, prefs):

        # URL = 'http://www.isfdb.org/cgi-bin/se.cgi?'  # simple search (not logged-in user)
        URL = 'https://www.isfdb.org/cgi-bin/se.cgi?'  # simple search (not logged-in user)

        if prefs['log_level'] in 'DEBUG':
            log.debug("*** Enter SearchResults.simple_url_from_params()")
            log.debug('URL={0}'.format(URL))
            log.debug('params={0}'.format(params))

        # return cls.URL + urlencode(params)  # Default encoding is utf-8, but ISFDB site is on iso-8859-1 (Latin-1)
        # Example original title with german umlaut: "Überfall vom achten Planeten"
        # Default urlencode() encodes:
        # https://www.isfdb.org/cgi-bin/adv_search_results.cgi?ORDERBY=title_title&START=0&TYPE=Title&USE_1=title_title&OPERATOR_1=contains&TERM_1=%C3%9Cberfall+vom+achten+Planeten&USE_2=author_canonical&OPERATOR_2=contains&TERM_2=Staff+Caine&CONJUNCTION_1=AND
        # and leads to "No records found"
        # website has <meta http-equiv="content-type" content="text/html; charset=iso-8859-1">
        # search link should be (encoded by isfdb.org search form itself):
        # isfdb.org: https://www.isfdb.org/cgi-bin/adv_search_results.cgi?USE_1=title_title&O_1=contains&TERM_1=%DCberfall+vom+achten+Planeten&C=AND&USE_2=title_title&O_2=exact&TERM_2=&USE_3=title_title&O_3=exact&TERM_3=&USE_4=title_title&O_4=exact&TERM_4=&USE_5=title_title&O_5=exact&TERM_5=&USE_6=title_title&O_6=exact&TERM_6=&USE_7=title_title&O_7=exact&TERM_7=&USE_8=title_title&O_8=exact&TERM_8=&USE_9=title_title&O_9=exact&TERM_9=&USE_10=title_title&O_10=exact&TERM_10=&ORDERBY=title_title&ACTION=query&START=0&TYPE=Title
        # log.info("urlencode(params, encoding='iso-8859-1')={0}".format(urlencode(params, encoding='iso-8859-1')))
        try:
            # return cls.URL + urlencode(params, encoding='iso-8859-1')
            return URL + urlencode(params, encoding='iso-8859-1')
        except UnicodeEncodeError as e:
            # unicode character in search string. Example: Unicode-Zeichen „’“ (U+2019, Right Single Quotation Mark)
            log.error(_('Error while encoding {0}: {1}.').format(params, e))
            encoded_params = urlencode(params, encoding='iso-8859-1', errors='replace')
            # cut the search string before the non-iso-8859-1 character (? is the encoding replae char)
            encoded_params = encoded_params.split('%3F')[0]
            log.info(_('Truncate the search string at the error position and search with the substring: {0}.').format(
                encoded_params))
            return URL + encoded_params

    @classmethod
    def is_type_of(cls, url, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug("*** Enter SearchResults.is_type_of()")
            log.debug('url={0}'.format(url))

        advanced_url = 'https://www.isfdb.org/cgi-bin/adv_search_results.cgi?'
        simple_url = 'https://www.isfdb.org/cgi-bin/se.cgi?'

        advanced_url_type = url.startswith(advanced_url) and ("TYPE=%s" % cls.TYPE) in url
        simple_url_type = url.startswith(simple_url) and ("TYPE=%s" % cls.TYPE) in url
        if prefs['log_level'] in 'DEBUG':
            log.debug('advanced_url_type={0}, simple_url_type={1}'.format(advanced_url_type, simple_url_type))
        if advanced_url_type:
            return advanced_url_type
        else:
            return simple_url_type


class PublicationsList(SearchResults):
    TYPE = "Publication"

    @classmethod
    def url_from_isbn(cls, isbn, log, prefs):

        # TODO support adding price or date as a supplementary field

        params = {
            "USE_1": "pub_isbn",
            "OPERATOR_1": "exact",
            "TERM_1": isbn,
            "ORDERBY": "pub_title",
            "START": "0",
            "TYPE": cls.TYPE,
        }

        return cls.url_from_params(params, log, prefs)

    @classmethod
    def url_from_title_and_author(cls, title, author, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug("*** Enter PublicationsList.url_from_title_and_author().")
            log.debug("title={0}, author={1}".format(title, author))
            log.debug("prefs={0}".format(prefs))

        # TODO support adding price or date as a supplementary field
        # bertholdm: Metadata plugins are not able to write user defined fields.

        field = 0

        params = {
            "ORDERBY": "pub_title",  # "ORDERBY": "pub_year"
            "START": "0",
            "TYPE": cls.TYPE,
        }

        if title:
            field += 1
            # For very short titles there ist a possible marker '=' as first character in title field
            if prefs['exact_search']:
                operator = 'exact'
            else:
                operator = 'contains'
            params.update({
                "USE_%d" % field: "pub_title",
                "OPERATOR_%d" % field: operator,
                "TERM_%d" % field: title,
            })

        if author:
            field += 1
            params.update({
                "USE_%d" % field: "author_canonical",
                "OPERATOR_%d" % field: "contains",
                "TERM_%d" % field: author,
            })

        if "USE_2" in params:
            params.update({
                "CONJUNCTION_1": "AND",
            })

        url = cls.url_from_params(params, log, prefs)
        if prefs['log_level'] in 'DEBUG':
            log.debug('url={0}.'.format(url))
        return url  # cls.url_from_params(params, log)

    @classmethod
    def from_url(cls, browser, url, timeout, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug('*** Enter PublicationsList.from_url().')
            log.debug('url={0}'.format(url))

        publication_stubs = []

        location, root = cls.root_from_url(browser, url, timeout, log, prefs)

        # Get rid of tooltips
        try:
            for tooltip in root.xpath('//sup[@class="mouseover"]'):
                tooltip.getparent().remove(
                    tooltip)  # We grab the parent of the element to call the remove directly on it
            for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
                tooltip.getparent().remove(
                    tooltip)  # We grab the parent of the element to call the remove directly on it
        except Exception as e:
            log.debug('Exception ignored:{0}'.format(e))

        rows = root.xpath('//div[@id="main"]/table/tr')

        for row in rows:
            # log.info('row={0}'.format(row.xpath('.')[0].text_content()))
            if not row.xpath('td'):
                continue  # header

            publication_stubs.append(Publication.stub_from_search(row, log, prefs))

        if prefs['log_level'] in 'DEBUG':
            log.debug("Parsed publications from url %r. Found %d publications." % (url, len(publication_stubs)))
            log.debug('publication_stubs={0}'.format(publication_stubs))

        return publication_stubs

    @classmethod
    def from_publication_ids(cls, browser, pub_ids, timeout, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug('*** Enter PublicationsList.from_publication_ids().')
            log.debug('pub_ids={0}'.format(pub_ids))

        # ToDo

        publication_stubs = []

        # # url???
        # location, root = cls.root_from_url(browser, url, timeout, log, prefs)
        #
        # # Get rid of tooltips
        # try:
        #     for tooltip in root.xpath('//sup[@class="mouseover"]'):
        #         tooltip.getparent().remove(
        #             tooltip)  # We grab the parent of the element to call the remove directly on it
        #     for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
        #         tooltip.getparent().remove(
        #             tooltip)  # We grab the parent of the element to call the remove directly on it
        # except Exception as e:
        #     log.debug('Exception ignored:{0}'.format(e))
        #
        # rows = root.xpath('//div[@id="main"]/table/tr')
        #
        # for row in rows:
        #     if prefs['log_level'] in 'DEBUG':
        #         log.debug('row={0}'.format(row.xpath('.')[0].text_content()))
        #     if not row.xpath('td'):
        #         continue  # header
        #
        #     publication_stubs.append(Publication.stub_from_search(row, log, prefs))
        #
        # if prefs['log_level'] in 'DEBUG':
        #     log.debug("Parsed publications from url %r. Found %d publications." % (url, len(publication_stubs)))
        #     log.debug('publication_stubs={0}'.format(publication_stubs))

        return publication_stubs


class TitleList(SearchResults):
    # TODO: separate permissive title/author search from specific lookup of a publication
    # TODO: isbn not possible; add type to exact search?

    TYPE = "Title"

    @classmethod
    def url_from_exact_title_author_and_type(cls, title, author, ttype, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug("*** Enter TitleList.url_from_exact_title_author_and_type().")
            log.debug("title={0}, author={1}, ttype={2}".format(title, author, ttype))

        if author != '':
            params = {
                "USE_1": "title_title",
                "OPERATOR_1": "exact",
                "TERM_1": title,
                "CONJUNCTION_1": "AND",
                "USE_2": "author_canonical",
                "OPERATOR_2": "contains",  # "exact"
                "TERM_2": author,
                "CONJUNCTION_2": "AND",
                "USE_3": "title_ttype",
                "OPERATOR_3": "exact",
                "TERM_3": ttype,
                "ORDERBY": "title_title",  # "ORDERBY": "title_copyright",
                "START": "0",
                "TYPE": cls.TYPE,
            }
        else:
            params = {
                "USE_1": "title_title",
                "OPERATOR_1": "exact",
                "TERM_1": title,
                "CONJUNCTION_1": "AND",
                "USE_2": "title_ttype",
                "OPERATOR_2": "exact",
                "TERM_2": ttype,
                "ORDERBY": "title_title",  # "ORDERBY": "title_copyright",
                "START": "0",
                "TYPE": cls.TYPE,
            }

        url = cls.url_from_params(params, log, prefs)
        if prefs['log_level'] in 'DEBUG':
            log.debug('url={0}.'.format(url))
        return url  # cls.url_from_params(params, log)

    @classmethod
    def url_from_title_and_author(cls, title, author, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug("*** Enter TitleList.url_from_title_and_author().")
            log.debug("title={0}, author={1}".format(title, author))
            log.debug("cls.TYPE={0}".format(cls.TYPE))
            log.debug("prefs{0}".format(prefs))

        field = 0

        params = {
            "ORDERBY": "title_title",  # "ORDERBY": "title_copyright",
            "START": "0",
            "TYPE": cls.TYPE,
        }

        if title:
            field += 1
            # For very short titles there ist a possible marker '=' as first character in title field
            if prefs['exact_search']:
                operator = 'exact'
            else:
                operator = 'contains'
            params.update({
                "USE_%d" % field: "title_title",
                "OPERATOR_%d" % field: operator,
                "TERM_%d" % field: title,
            })

        if author:
            field += 1
            params.update({
                "USE_%d" % field: "author_canonical",
                "OPERATOR_%d" % field: "contains",
                "TERM_%d" % field: author,
            })

        if "USE_2" in params:
            params.update({
                "CONJUNCTION_1": "AND",
            })

        url = cls.url_from_params(params, log, prefs)
        if prefs['log_level'] in 'DEBUG':
            log.debug('url={0}.'.format(url))
        return url  # cls.url_from_params(params, log)

    @classmethod
    def simple_url_from_title(cls, title, author, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug("*** Enter TitleList.simple_url_from_title().")
            log.debug("title={0}, author={1}".format(title, author))
            log.debug("prefs={0}".format(prefs))

        field = 0

        # https://www.isfdb.org/cgi-bin/se.cgi?arg=project+saturn&type=All+Titles
        params = {
            "TYPE": 'All Titles',  # cls.TYPE
        }

        if title:
            field += 1
            # For very short titles there ist a possible marker '=' as the first character in title field
            if prefs['exact_search']:
                operator = 'exact'
            else:
                operator = 'contains'
            params.update({
                "USE_%d" % field: "title_title",
                "OPERATOR_%d" % field: operator,
                "ARG": title,
            })

        if prefs['log_level'] in 'DEBUG':
            log.debug('params={0}.'.format(params))

        url = cls.simple_url_from_params(params, log, prefs)
        if prefs['log_level'] in 'DEBUG':
            log.debug('url={0}.'.format(url))
        return url  # cls.simple_url_from_params(params, log)

    @classmethod
    def url_from_title_with_keywords(cls, title_with_keywords, keyword_list, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug("*** Enter TitleList.url_from_title_with_keywords().")
            log.debug("title_with_keywords={0}".format(title_with_keywords))
            log.debug("keyword_list={0}".format(keyword_list))
            log.debug("prefs={0}".format(prefs))

        field = 0

        # https://www.isfdb.org/cgi-bin/se.cgi?arg=project+saturn&type=All+Titles
        params = {
            "TYPE": 'All Titles',  # cls.TYPE
        }

        # Extract title from keyword "Title:"
        # 1) Make a list of start pos for each keyword
        keyword_start_list = []
        for keyword in keyword_list:
            keyword_start_list.append(title_with_keywords.find(keyword))
        keyword_start_list.append(len(title_with_keywords))
        log.debug("keyword_start_list={0}".format(keyword_start_list))
        title_dict = {}
        list_index = 0
        for keyword in keyword_list:
            title_dict[keyword] = \
                title_with_keywords[keyword_start_list[list_index] + len(keyword):keyword_start_list[list_index + 1]] \
                    .strip()
            list_index = list_index + 1
        if prefs['log_level'] in 'DEBUG':
            log.debug("title_dict={0}".format(title_dict))

        title = title_dict['Title:']
        year = title_dict['Year:']

        if title:
            field += 1
            # For very short titles there ist a possible marker '=' as the first character in title field
            if prefs['exact_search']:
                operator = 'exact'
            else:
                operator = 'contains'
            params.update({
                "USE_%d" % field: "title_title",
                "OPERATOR_%d" % field: operator,
                "ARG": title + ' - ' + year,
            })

        # https://www.isfdb.org/cgi-bin/se.cgi?arg=The+Magazine+of+Fantasy+and+Science+Fiction&type=Magazine
        # -> Series: The Magazine of Fantasy and Science Fiction
        # https://www.isfdb.org/cgi-bin/se.cgi?arg=The+Magazine+of+Fantasy+and+Science+Fiction+&type=Series
        # -> Series: The Magazine of Fantasy and Science Fiction

        # ToDo: Find correct url for simple search for all titles

        url = cls.simple_url_from_params(params, log, prefs)
        if prefs['log_level'] in 'DEBUG':
            log.debug('url={0}.'.format(url))
        return url  # cls.simple_url_from_params(params, log)

    @classmethod
    def from_url(cls, browser, url, timeout, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug('*** Enter TitleList.from_url().')
            log.debug('url={0}'.format(url))
            # https://www.isfdb.org/cgi-bin/adv_search_results.cgi?ORDERBY=title_title&START=0&TYPE=Title&USE_1=title_title&OPERATOR_1=contains&TERM_1=In+The+Vault&USE_2=author_canonical&OPERATOR_2=contains&TERM_2=H.+P.+Lovecraft&CONJUNCTION_1=AND

        title_stubs = []
        simple_search_url = None

        location, root = cls.root_from_url(browser, url, timeout, log, prefs)  # site encoding is iso-8859-1
        if not root:
            log.debug('No root found with this url!. Abort.')
            abort = True
            return []

        # Get rid of tooltips
        try:
            for tooltip in root.xpath('//sup[@class="mouseover"]'):
                tooltip.getparent().remove(
                    tooltip)  # We grab the parent of the element to call the remove directly on it
            for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
                # We grab the parent of the element to call the remove directly on it
                tooltip.getparent().remove(tooltip)
        except Exception as e:
            log.debug('Exception ignored:{0}'.format(e))

        rows = root.xpath('//div[@id="main"]/form/table/tr')
        # rows = root.xpath('//div[@id="main"]/form/table/tr[@class="table1"]')
        if not rows:
            # New message in May 2022: "For performance reasons, Advanced Searches are currently restricted to registered users."
            # tostring() produces a byte object!, so decode
            root_str = etree.tostring(root, encoding='utf8', method='xml').decode()
            if 'For performance reasons, Advanced Searches are currently restricted to registered users.' in root_str:
                log.debug(_('Advanced search not allowed for not logged in users. Trying a simple search.'))
                # Simple search works:
                # https://www.isfdb.org/cgi-bin/se.cgi?arg=under+the+green+star&type=All+Titles
                # https://www.isfdb.org/cgi-bin/se.cgi?arg=Lin+Carter&type=Name
                # Fall back to simple search:
                # Find title in url. Switch
                # From:
                # https://www.isfdb.org/cgibin/adv_search_results.cgi?ORDERBY=title_title&START=0&TYPE=Title
                # &USE_1=title_title&OPERATOR_1=contains&TERM_1=In+The+Vault&USE_2=author_canonical
                # &OPERATOR_2=contains&TERM_2=H.+P.+Lovecraft&CONJUNCTION_1=AND
                # To:
                # # http://www.isfdb.org/cgi-bin/se.cgi?arg=under+the+green+star&type=All+Titles
                # simple_search_url = url[:29]
                # # https://www.isfdb.org/cgi-bin/se.cgi?arg=under+the+green+star&type=All+Titles
                simple_search_url = url[:30]
                simple_search_url = simple_search_url + "se.cgi?arg="
                # url=https://www.isfdb.org/cgi-bin/adv_search_results.cgi?ORDERBY=title_title&START=0&TYPE=Title&USE_1=title_title&OPERATOR_1=contains&TERM_1=Ring+of+Destiny
                simple_search_url = simple_search_url + re.search('&TERM_1=(.*)?(&|$)', url).group(1)
                simple_search_url = simple_search_url + "&type=All+Titles"
                if prefs['exact_search']:
                    simple_search_url = simple_search_url.replace('contains', 'exact')  # ToDo: Exact search only for title???
                log.debug('simple_search_url={0}'.format(simple_search_url))
                # https://www.isfdb.org/cgi-bin/se.cgi?arg=STONE&USE_2=author_canonical&OPERATOR_2=exact&TERM_2=Edward+Bryant&CONJUNCTION_1=AND&type=All+Titles
                # In simple search all params except 'arg' and 'type' are ignored: https://www.isfdb.org/cgi-bin/se.cgi?arg=STONE&type=Fiction+Titles
                # A search for 'STONE' found 3720 matches.
                # The first 300 matches are displayed below. Use Advanced Title Search to see more matches.
                # For simple search, max_results and max_covers must be increased to get all possible results
                prefs['max_results'] = 300
                prefs['max_covers'] = 300
                location, root = cls.root_from_url(browser, simple_search_url, timeout, log,
                                                   prefs)  # site encoding is iso-8859-1
                # If still no results, debug:
                if not root:
                    log.debug(_('No root found, neither with advanced or simple search. HTML output follows. Abort.'))
                    abort = True
                    return []

                # Show number of result records
                result_records = root.xpath('//*[@id="main"]/p[1]/b/text()[1]')
                log.debug('{0}'.format(result_records))

                # Get rid of tooltips
                try:
                    for tooltip in root.xpath('//sup[@class="mouseover"]'):
                        tooltip.getparent().remove(
                            tooltip)  # We grab the parent of the element to call the remove directly on it
                    for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
                        tooltip.getparent().remove(
                            tooltip)  # We grab the parent of the element to call the remove directly on it
                except Exception as e:
                    log.debug('Exception ignored:{0}'.format(e))

                # //*[@id="main"]/table
                rows = root.xpath('//div[@id="main"]/table/tr')

                if not rows:
                    # Has ISFDB performed a immediate redirection to a title detail page?
                    # https://www.isfdb.org/cgi-bin/title.cgi?57407
                    # <div id="content">
                    # <div class="ContentBox">
                    # <b>Title:</b> The War Beneath the Tree
                    # <span class="recordID"><b>Title Record # </b>57407</span>
                    root_str = etree.tostring(root, encoding='utf8', method='xml').decode()

                    if '<span class="recordID"><b>Title Record #' in root_str:
                        log.debug(
                            _('ISFDB webpage has redirected to a title page (only one title found), located at: {0}.'.format(
                                location)))
                        log.debug(root_str[:800])

                        # Das haben wir:

                        # <div id="content">
                        # <div class="ContentBox">
                        # <b>Title:</b> The War Beneath the Tree
                        # <span class="recordID"><b>Title Record # </b>57407</span>
                        # <br/><b>Author:</b>
                        # <a href="https://www.isfdb.org/cgi-bin/ea.cgi?171" dir="ltr">Gene Wolfe</a>
                        # <br/>
                        # <b>Date:</b>  1979-12-00
                        # <br/>
                        # <b>Variant Title of:</b> <a href="https://www.isfdb.org/cgi-bin/title.cgi?1047800" dir="ltr">War Beneath the Tree</a>
                        #  [may list more publications, awards, reviews, votes and covers]
                        # <br/>
                        # <b>Type:</b> SHORTFICTION
                        # <br/>
                        # <b>Length:</b>
                        # short story
                        # <br/><b>Language:</b> English
                        # <br/>
                        # <b>User Rating:</b>
                        # This title has no votes.
                        # <a class="inverted" href="https://www.isfdb.org/cgi-bin/edit/vote.cgi?57407" dir="ltr"><b>VOTE</b></a>
                        # <br/>
                        # <b>Current Tags:</b>
                        # None
                        # </div>

                        # So soll's werden:

                        # [{'title': 'The War Beneath the Tree', 'url': 'https://www.isfdb.org/cgi-bin/title.cgi?57407', 'authors': ['Gene Wolfe']}]

                        properties = {}
                        properties["url"] = location
                        title = re.search(r'<title>Title: (.*)</title>', root_str).group(1).strip()
                        title = re.sub('<.*?>', '', title)  # Get rid of html tags
                        title = title.replace('Title:', '').strip()
                        properties["title"] = [title]
                        properties["date"] = datetime.date
                        try:
                            properties["author"] = [re.search(r'<b>Author:</b>(.*)\\r\\n<br><b>Date:</b>', root_str,
                                                              re.MULTILINE).group(1).strip()]
                            properties["author"] = [re.sub('<.*?>', '', properties["author"])]  # Get rid of html tags
                        except AttributeError:
                            properties["author"] = []
                        # content_box = root.xpath('//*[@id="content"]/div[1])')
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('properties["title"]={0}, properties["url"]={1}.'.format(properties["title"],
                                                                                               properties["url"]))
                        title_stubs = [{'title': properties["title"], 'url': properties["url"],
                                        'authors': properties["author"], 'date': properties["date"]}]

                        return title_stubs

                    log.debug('No rows found, neither with advanced or simple search. HTML output follows. Abort.')
                    log.debug(etree.tostring(root, pretty_print=True))
                    abort = True
                    return []

        for row in rows:
            if prefs['log_level'] in 'DEBUG':
                log.debug('row={0}'.format(row.xpath('.')[0].text_content()))

            if not row.xpath('td'):
                if prefs['log_level'] in 'DEBUG':
                    log.debug('Table header ignored.')
                continue  # ignore header cols

            if simple_search_url:
                # If simple search: Filter text titles (NOVEL etc.)
                if row.xpath('td[2]')[0].text_content() not in ('ANTHOLOGY', 'CHAPBOOK', 'COLLECTION', 'ESSAY',
                                                                'MAGAZINE', 'NONFICTION', 'NOVEL', 'OMNIBUS', 'POEM',
                                                                'SHORTFICTION'):
                    if prefs['log_level'] in 'DEBUG':
                        log.debug('Type ignored.')
                    continue
                # Filter languages
                if prefs['log_level'] in 'DEBUG':
                    log.debug('loc_prefs[languages]={0}'.format(prefs['languages']))
                # Get the content of the languages field in calibre meta data
                if row.xpath('td[3]')[0].text_content() not in ('English', get_language_name(prefs['languages'])):
                    if prefs['log_level'] in 'DEBUG':
                        log.debug('Language ignored.')
                    continue  # ignore language
                if prefs['log_level'] in 'DEBUG':
                    log.debug('td[5]={0}'.format(row.xpath('td[5]')[0].text_content()))
                # https://www.isfdb.org/cgi-bin/adv_search_results.cgi?ORDERBY=title_title&START=0&TYPE=Title
                # &USE_1=title_title&OPERATOR_1=exact&TERM_1=Sph%E4renkl%E4nge
                # or:
                # https://www.isfdb.org/cgi-bin/adv_search_results.cgi?ORDERBY=title_title&START=0&TYPE=Title&
                # USE_1=title_title&OPERATOR_1=exact&TERM_1=Endzeit&USE_2=author_canonical&OPERATOR_2=contains&
                # TERM_2=Herbert+W.+Franke&CONJUNCTION_1=AND
                if prefs['exact_search']:
                    # TERM_1=Sph%E4renkl%E4nge
                    title = re.search('TERM_1=(.+?)$', url)  # test case 1
                    if title:
                        title_str = str(title.group(1))
                        if '&' in title_str:  # case 2
                            title = re.search('TERM_1=(.+?)&', url)
                            title_str = str(title.group(1))
                        title_str = title_str.replace('+', ' ')
                        title_str = title_str.lower()
                        title_str = unquote(title_str, encoding='iso-8859-1', errors='replace')
                        log.debug('Title to find is "{0}", Title in page is "{1}"'.
                                  format(title_str, row.xpath('td[4]')[0].text_content()))
                        if not title_str == row.xpath('td[4]')[0].text_content().lower():
                            if prefs['log_level'] in 'DEBUG':
                                log.debug('Title ignored because "exact search" is set.')
                            continue  # ignore title
                    else:
                        log.debug('Title not found in url???')
                # If simple search: Filter authors from title list)
                # TERM_2=Gene+Wolfe&
                author = re.search('TERM_2=(.+?)&', url)
                if author:
                    author_str = str(author.group(1))
                    author_str = author_str.replace('+', ' ')
                    author_str = author_str.lower()
                    # author_str comes from url, so convert percent encoded characters back
                    author_str = unquote(author_str, encoding='iso-8859-1', errors='replace')
                    if prefs['log_level'] in 'DEBUG':
                        log.debug('author_str={0}'.format(author_str))
                    if author_str not in row.xpath('td[5]')[0].text_content().lower():
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('Author ignored.')
                        continue  # ignore author

                # A url is found, line: https://www.isfdb.org/cgi-bin/title.cgi?59104
                title_stubs.append(Title.stub_from_simple_search(row, log, prefs))
            else:
                # Filter languages
                if row.xpath('td[5]')[0].text_content() not in ('English', get_language_name(prefs['languages'])):
                    if prefs['log_level'] in 'DEBUG':
                        log.debug('Language ignored.')
                    continue  # ignore language
                title_stubs.append(Title.stub_from_search(row, log, prefs))

        if prefs['log_level'] in 'DEBUG':
            if simple_search_url is None:
                log.debug("Parsing titles from url %r. Found %d titles." % (url, len(title_stubs)))
            else:
                log.debug("Parsing titles from url %r. Found %d titles." % (simple_search_url, len(title_stubs)))
            log.debug('title_stubs={0}'.format(title_stubs))
            # [{'title': 'In the Vault', 'url': 'https://www.isfdb.org/cgi-bin/title.cgi?41896', 'authors': ['H. P. Lovecraft']},
            # {'title': 'In the Vault', 'url': 'https://www.isfdb.org/cgi-bin/title.cgi?2946687', 'authors': ['H. P. Lovecraft']}]

        return title_stubs


class Record(ISFDBObject):

    URL = None  # Is set in the sub-classes Publication and Title

    @classmethod
    # Which record type (title or publication) is the actual page
    def is_type_of(cls, url, log, prefs):
        if prefs['log_level'] in 'DEBUG':
            log.debug('*** Enter Record(ISFDBObject).is_type_of().')
            log.debug('cls.URL={0}'.format(cls.URL))
        type =  url.startswith(cls.URL)
        if prefs['log_level'] in 'DEBUG':
            log.debug('type={0}'.format(type))
        return type

class Publication(Record):
    # URL = 'http://www.isfdb.org/cgi-bin/pl.cgi?'
    URL = 'https://www.isfdb.org/cgi-bin/pl.cgi?'

    @classmethod
    def url_from_id(cls, isfdb_id):
        return cls.URL + isfdb_id

    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).group(1)

    @classmethod
    def stub_from_search(cls, row, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug('*** Enter Publication.stub_from_search().')
            log.debug('row={0}'.format(etree.tostring(row)))

        properties = {}

        try:
            properties["title"] = row.xpath('td[1]/a')[0].text_content()  # If title is linked
            properties["url"] = row.xpath('td[1]/a/@href')[0]
        except IndexError:
            try:
                properties["title"] = row.xpath('td[1]/div/a')[0].text_content()  # If title is in tooltip div
                properties["url"] = row.xpath('td[1]/div/a/@href')[0]
            except IndexError:
                properties["title"] = row.xpath('td[1]')[0].text_content()  # If title is not linked
                properties["url"] = None

        properties["authors"] = [a.text_content() for a in row.xpath('td[3]/a')]
        # Display publications in Calibre GUI in ascending order by date
        properties["pub_year"] = row.xpath('td[2]')[0].text_content().strip()[:4]

        if prefs['log_level'] in 'DEBUG':
            log.debug('properties={0}'.format(properties))

        return properties

    @classmethod
    def from_url(cls, browser, url, timeout, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug('*** Enter Publication.from_url().')
            log.debug('url={0}'.format(url))

        # To distinguish series_index quality. Authoritative is the contenht of the field "Pub. Series #"
        series_index_is_authoritative = None

        properties = {"isfdb": cls.id_from_url(url)}

        location, root = cls.root_from_url(browser, url, timeout, log, prefs)

        # Get rid of tooltips
        for tooltip in root.xpath('//sup[@class="mouseover"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it
        for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it

        # Records with a cover image (most pages)
        # //*[@id="content"]/div[1]/table/tr/td[2]/ul
        detail_nodes = root.xpath('//div[@id="content"]//td[@class="pubheader"]/ul/li')
        # Records without a cover image (a few pages)
        # //*[@id="content"]/div[1]/ul
        if not detail_nodes:
            if prefs['log_level'] in 'DEBUG':
                log.debug('This is a pub page without cover.')
            detail_nodes = root.xpath(
                '//div[@id="content"]/div[@class="ContentBox"]/ul/li')  # no table present in records with no image
            # More than one ContenBox possible!

        if not detail_nodes:
            if prefs['log_level'] in ('DEBUG', 'INFO'):
                log.debug('Still no content found.')

        # Publication: R. U. R. (Rossum's Universal Robots): A Play in Three Acts and an EpiloguePublication Record # 622668 [Edit] [Edit History]
        # Author: Karel Čapek?
        # Date: 1923-00-00
        # Publisher: Oxford University Press
        # Price: 2/6
        # Pages: 102
        # Format: tp?
        # Type: CHAPBOOK
        # Notes:
        # Price from The British Science-Fiction Bibliography, 1937.
        # External IDs:
        # Bleiler Early Years: 358
        # OCLC/WorldCat: 312705060

        for detail_node in detail_nodes:
            if prefs['log_level'] in 'DEBUG':
                log.debug('detail_node={0}'.format(etree.tostring(detail_node)))
            section = detail_node[0].text_content().strip().rstrip(':')
            if section[:7] == 'Notes: ':  # if accidentally stripped in notes itself
                section = section[:5]
            if prefs['log_level'] in 'DEBUG':
                log.debug('section={0}'.format(section))

            date_text = ''  # Memorize, to build series index from pubdate, if not expicitly given

            try:
                if section == 'Publication':
                    properties["title"] = detail_node[0].tail.strip()
                    if not properties["title"]:
                        # assume an extra span with a transliterated title tooltip
                        properties["title"] = detail_node[1].text_content().strip()
                    # Todo: Get series and series index from pub line, if not otherwise indicated:
                    # Publication: New Worlds,#192 July 1969
                    # Publication: Epic Illustrated, February 1986
                    # Publication: Vargo Statten British Science Fiction Magazine, Vol 1 No 4

                elif section in ('Author', 'Authors', 'Editor', 'Editors'):
                    properties["authors"] = []
                    for a in detail_node.xpath('.//a'):
                        author = a.text_content().strip()
                        if author != 'uncredited':
                            # For looking up the corresponding title.
                            # We can only use the first author because the search is broken.
                            if "author_string" not in properties:
                                properties["author_string"] = author  # Why?
                            if section.startswith('Editor'):
                                if prefs["translate_isfdb"]:
                                    properties["authors"].append(author + _(' (Editor)'))
                                else:
                                    properties["authors"].append(author + ' (Editor)')
                            else:
                                properties["authors"].append(author)

                elif section == 'Date':
                    date_text = detail_node[0].tail.strip()
                    if date_text in ['date unknown', 'unknown', 'unpublished']:
                        properties["pubdate"] = None  # Warning ignored
                    else:
                        # We use this instead of strptime to handle dummy days and months
                        # E.g. 1965-00-00
                        year, month, day = [int(p) for p in date_text.split("-")]
                        month = month or 1
                        day = day or 1
                        # Correct datetime result for day = 0: Set hour to 2 UTC
                        # (if not, datetime goes back to the last month and, in january, even to december last year)
                        # ToDo: set hour to publisher's timezone?
                        # properties["pubdate"] = datetime.datetime(year, month, day)
                        properties["pubdate"] = datetime.datetime(year, month, day, 2, 0, 0)

                elif section == 'Publisher':
                    try:
                        properties["publisher"] = detail_node.xpath('a')[0].text_content().strip()
                    except IndexError:
                        properties["publisher"] = detail_node.xpath('div/a')[0].text_content().strip()  # toolötip div

                elif section == 'Format':
                    properties["format"] = detail_node[0].tail.strip()

                elif section == 'Type':
                    properties["type"] = detail_node[0].tail.strip()
                    # Copy publication type to tags
                    if "tags" not in properties:
                        properties["tags"] = []
                    try:
                        tags = TYPE_TO_TAG[properties["type"]]
                        if prefs["translate_isfdb"]:
                            # ToDo: Loop thru tags in list and translate them
                            tags = _(tags)
                        properties["tags"].extend([t.strip() for t in tags.split(",")])
                    except KeyError:
                        pass

                elif section == 'Cover':
                    properties["cover"] = ' '.join([x for x in detail_node.itertext()]).strip().replace('\n', '')
                    properties["cover"] = properties["cover"].replace('  ', ' ')
                    if prefs["translate_isfdb"]:
                        properties["cover"] = properties["cover"].replace('variant of', _('variant of'))
                        properties["cover"] = properties["cover"].replace(' by ', _(' by '))

                elif section == 'Pub. Series':
                    # If series is a url, open series page and search for "Sub-series of:"
                    # https://www.isfdb.org/cgi-bin/pe.cgi?45706
                    properties["series"] = ''
                    properties["series_index"] = 0.0
                    # if ISFDB3.loc_prefs["combine_series"]:
                    # url = detail_node[1].xpath('//a[contains(text(), "' + detail_node[1].text_content().strip() + '")]/@href')  # get all urs
                    try:
                        # In most cases, the series name is a link
                        # b'<li>\n  <b>Pub. Series:</b> <a href="https://www.isfdb.org/cgi-bin/pubseries.cgi?9408" dir="ltr">World\'s Best Science Fiction</a>\n</li>'
                        # //*[@id="content"]/div[1]/table/tbody/tr/td[2]/ul/li[6]/a
                        series_url = detail_node.xpath('./a/@href')[0]
                    except IndexError:
                        # url is embedded in a tooltip div:  //*[@id="content"]/div[1]/ul/li[5]/div/a
                        series_url = detail_node.xpath('./div/a/@href')[0]
                    if prefs['log_level'] in 'DEBUG':
                        log.debug('series_url={0}'.format(series_url))
                    # Scan series record
                    properties["series"] = Series.from_url(browser, series_url, timeout, log, prefs)
                    if properties["series"] == '':
                        properties["series"] = detail_node.xpath('a')[0].text_content().strip()  # Fallback

                elif section == 'Pub. Series #':
                    if properties["series"] != '':
                        if prefs['log_level'] in ('DEBUG', 'INFO'):
                            log.info(
                                _('Series is: "{0}". Now searching series index in "{1}"'.format(properties["series"],
                                                                                                 detail_node[
                                                                                                     0].tail.strip())))
                        if detail_node[0].tail.strip() == '':
                            properties["series_index"] = 0.0
                        elif '/' in detail_node[0].tail:
                            # Calibre accepts only float format compatible numbers, not e. g. "61/62"
                            series_index_list = detail_node[0].tail.split('/')
                            properties["series_index"] = int("".join(filter(str.isdigit, series_index_list[0])).strip())
                            properties["series_number_notes"] = \
                                _("Reported number was {0} and was reduced to a Calibre compatible format.<br />"). \
                                    format(detail_node[0].tail)
                            series_index_is_authoritative = True
                        elif is_roman_numeral(detail_node[0].tail.strip()):
                            if prefs['log_level'] in 'DEBUG':
                                log.debug('Roman literal found:{0}'.format(detail_node[0].tail.strip()))
                            # Calibre accepts only float format compatible arabic numbers, not roman numerals e. g. "IV"
                            # https://www.isfdb.org/cgi-bin/pl.cgi?243949
                            properties["series_index"] = roman_to_int(detail_node[0].tail.strip())
                            properties["series_number_notes"] = \
                                _("Reported number was the roman numeral {0} and was converted to a Calibre compatible format.<br />"). \
                                    format(detail_node[0].tail.strip())
                            series_index_is_authoritative = True
                        else:
                            try:
                                properties["series_index"] = int(
                                    "".join(filter(str.isdigit, detail_node[0].tail.strip())))
                                series_index_is_authoritative = True
                            except ValueError:
                                properties["series_number_notes"] = \
                                    _("Could not convert {0} to a Calibre compatible format.<br />"). \
                                        format(detail_node[0].tail.strip())
                                properties["series_index"] = 0.0
                        # log.info('properties["series_index"]={0}'.format(properties["series_index"]))

                elif section == 'Notes':
                    # notes_nodes = detail_node.xpath('./div[@class="notes"]/ul')  # /li
                    # notes = detail_node[0].tail.strip()
                    notes = ' '.join([x for x in detail_node.itertext()]).strip().replace('\n', '')
                    if prefs['log_level'] in ['DEBUG']:
                        log.debug('notes={0}'.format(notes))
                    if notes != '':
                        notes_nodes = detail_node.xpath('./div[@class="notes"]')
                        # Notes:
                        # or
                        # Notes: Vol. 17, No. 5
                        # or
                        # Notes:
                        # • Vol 6 No 12. Edited by ...
                        # • Fiction Editor: Ellen Datlow
                        #  etc.
                        # Code:
                        # <div class="notes"><b>Notes:</b>
                        # <ul>
                        # <li>"Some ...</li>
                        # <li>Cover artist ...</li>
                        # </ul>
                        # </div>
                        # and even this:
                        # Notes:
                        # • Vol. 4, No. 3. Issue 22.
                        if notes_nodes and not series_index_is_authoritative:
                            # Special treatment for publication series:
                            # Vol 1, No 5. Donald A. Wollheim is credited...
                            # or:
                            # Volume 41, No 3, Whole No. 244
                            # or:
                            # Vol. II No. 8
                            # Whole No. at the moment ignored
                            # or:
                            # #57Note that Terry Boren's story is [...]
                            # or:
                            # Vol 46, No 3, Whole No 274 [...]
                            # or:
                            # Summer 1950 (May-July), Vol 4., No. 11.
                            # or:
                            # Vol.1, No.11
                            # or:
                            # Volume 1, Number 1
                            match = re.search('.*(?:Volume\s|Vol\.\s|Vol\s|Vol\.)([0-9]+|[MDCLXVI]+)(?:.,\s|,\s| *)'
                                              '(?:No\.|No\.\s|No\s|Number\s)([0-9]+)(\.\sIssue\s)?([0-9]+)?.*|#([0-9]+)',
                                              notes, re.IGNORECASE)
                            if match:
                                volume = number = issue_number = 0
                                if match.group(1):
                                    # Check if volume is indicated in roman digits
                                    volume_text = str(match.group(1))
                                    if is_roman_numeral(volume_text):
                                        if prefs['log_level'] in 'DEBUG':
                                            log.debug('Roman literal found:{0}'.format(volume_text))
                                        # Calibre accepts only float format compatible arabic numbers,
                                        # not roman numerals e. g. "IV"
                                        # https://www.isfdb.org/cgi-bin/pl.cgi?243949
                                        volume = roman_to_int(volume_text)
                                        properties["series_number_notes"] = \
                                            _("Reported number was the roman numeral {0} and was converted to "
                                              "a Calibre compatible format.<br />").format(volume_text)
                                    else:
                                        volume = int(str(volume_text))
                                if match.group(2):
                                    number = int(str(match.group(2)))
                                if match.group(3) and match.group(4):
                                    issue_number = int(str(match.group(4)))
                                    prefs["series_index_options"] = 'issue_no_only'
                                if match.group(5):
                                    volume = int(str(match.group(5)))
                                if prefs['log_level'] in ['DEBUG']:
                                    log.debug('series_index_options={0}'.format(prefs["series_index_options"]))
                                    log.debug('volume={0}, number={1}, issue_number={2}'.
                                              format(volume, number, issue_number))
                                if prefs["series_index_options"] == 'vol_and_no':
                                    if number < 100:
                                        properties["series_index"] = float(volume) + float(number) * .01
                                    else:
                                        properties["series_index"] = float(volume) + 0.99
                                elif prefs["series_index_options"] == 'issue_no_only':
                                    properties["series_index"] = float(issue_number) + .0
                                else:
                                    log.debug('Unknown series index option.')
                                if prefs['log_level'] in ['DEBUG', 'INFO']:
                                    log.debug('Build Series Index from Notes={0}'.format(properties["series_index"]))

                            # Is there a more precise pub date in Notes when only year is given in pub date?
                            # Summer 1950 (May-July), Vol 4., No. 11.
                            month_number_from_season = 1
                            month_number_from_monthname = 1
                            month_number = 1
                            match = re.search('(Spring|Summer|Autumn|Winter)', notes, re.IGNORECASE)
                            if match:
                                if match.group(1):
                                    season_name = str(match.group(1))
                                    season_names = ['Spring', 'Summer' , 'Autumn', 'Winter']
                                    season_begins = [2, 5, 8, 11]
                                    season_number = season_names.index(season_name)
                                    month_number_from_season = season_begins[season_number]
                                    if prefs['log_level'] in 'DEBUG':
                                        log.debug('month_number_from_season={0}'.format(month_number_from_season))
                            match = re.search('\((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec).*-.*\)', notes, re.IGNORECASE)
                            if match:
                                if match.group(1):
                                    month_name = str(match.group(1))
                                    # Does not work with non-english locale!
                                    # month_number = datetime.datetime.strptime(month_name, '%B').month
                                    month_names = \
                                        ['Jan', 'Feb' , 'Mar', 'Apr', 'May', 'Jun',
                                         'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
                                    month_number_from_monthname = month_names.index(month_name) + 1
                                    if prefs['log_level'] in 'DEBUG':
                                        log.debug('month_number_from_monthname={0}'.format(month_number_from_monthname))
                            if month_number_from_season <= month_number_from_monthname:
                                month_number = month_number_from_monthname
                            else:
                                month_number = month_number_from_season
                            if properties["pubdate"].month == 1 and properties["pubdate"].day == 1:
                                properties["pubdate"] = (
                                    datetime.datetime(properties["pubdate"].year,
                                                      month_number,
                                                      1,
                                                      2, 0, 0))

                            # Output Notes as is (including html)
                            if "notes" not in properties:
                                properties["notes"] = sanitize_comments_html(tostring(notes_nodes[0], method='html'))
                            else:
                                properties["notes"] = properties["notes"] + '<br />' + \
                                                      sanitize_comments_html(tostring(notes_nodes[0], method='html'))
                            if prefs["translate_isfdb"]:
                                for term in TRANSLATION_REPLACINGS:
                                    # log.debug('term, msgtext='.format(term, _(term)))
                                    properties["notes"] = properties["notes"].replace(term, _(term))
                            if prefs['log_level'] in 'DEBUG':
                                log.debug('properties["notes"]={0}'.format(properties["notes"]))

                elif section == 'ISBN':
                    # Possible formats:
                    # 978-1-368-02083-1 [1-368-02083-6] (ISBN-13 first) or
                    # 0-451-14894-0 [978-0-451-14894-0] (ISBN-10 first
                    # From urls_from_identifiers(): isbn = identifiers.get('isbn', None)
                    isbn1 = ''
                    isbn2 = ''
                    if 'identifiers' not in properties:
                        properties["identifiers"] = {}
                    # detail_node=b'<li><b>ISBN:</b> 978-1-61287-013-7 [<small>1-61287-013-9</small>]\n</li>'
                    if prefs['log_level'] in 'DEBUG':
                        log.debug('detail_node.text_content()={0}'.format(detail_node.text_content()))
                    match = re.search('([0-9X\-]+) \[([0-9X\-]+)\]', detail_node.text_content(), re.IGNORECASE)
                    if match:
                        if match.group(1):
                            isbn1 = match.group(1)
                            isbn1 = ''.join([c.replace('-', '') for c in isbn1])  # Get rid of dashes
                        if match.group(2):
                            isbn2 = match.group(2)
                            isbn2 = ''.join([c.replace('-', '') for c in isbn2])  # Get rid of dashes
                        # Fetch both ISBN 10 and 13
                        if len(isbn1) == 10:
                            properties["identifiers"].update({'isbn-10': isbn1})
                        elif len(isbn1) == 13:
                            properties["identifiers"].update({'isbn-13': isbn1})
                        if len(isbn2) == 10:
                            properties["identifiers"].update({'isbn-10': isbn2})
                        elif len(isbn2) == 13:
                            properties["identifiers"].update({'isbn-13': isbn2})
                        # Preferred ISBN is ISBN-13
                        if len(isbn1) > 0 and len(isbn1) > len(isbn2):
                            properties["identifiers"].update({'isbn': isbn1})
                        if len(isbn2) > 0 and len(isbn2) > len(isbn1):
                            properties["identifiers"].update({'isbn': isbn2})
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('properties["identifiers"]={0}'.format(properties["identifiers"]))
                    else:
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('No ISBN found.')

                elif section == 'External IDs':
                    # <li>
                    #   <b>External IDs:</b>
                    #   <ul class="noindent">
                    # <li> <abbr class="template" title="Online Computer Library Center">OCLC/WorldCat</abbr>:  <a href="https://www.worldcat.org/oclc/16391906" target="_blank">16391906</a></li>
                    # <li> <abbr class="template" title="Robert Reginald. Science Fiction and Fantasy Literature, 1975-1991: A Bibliography of Science Fiction, Fantasy, and Horror Fiction Books and Nonfiction Monographs. Gale Research Inc., 1992, 1512 p.">Reginald-3</abbr>: 15985</li>
                    # </ul>
                    # </li>
                    if 'identifiers' not in properties:
                        properties["identifiers"] = {}
                    external_id_nodes = detail_node.xpath('ul/li')
                    for external_id_node in external_id_nodes:  # walk thru external id(s)
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('external_id_node={0}'.format(etree.tostring(external_id_node)))
                            # b'<li>
                            # <abbr class="template" title="Goodreads social cataloging site">Goodreads</abbr>:
                            # <a href="https://www.goodreads.com/book/show/27598449" target="_blank">27598449</a>\n
                            # </li>'
                        catalog_name = external_id_node.xpath('./abbr/text()')
                        catalog_link = external_id_node.xpath('./a/@href')
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('catalog_name={0}'.format(catalog_name))
                            log.debug('catalog_link={0}'.format(catalog_link))
                        if len(catalog_link) == 0:  # Catalog number without link
                            if prefs['log_level'] in 'DEBUG':
                                log.debug('catalog number is not linked.')
                            catalog_number = external_id_node.xpath('./text()[normalize-space()]')
                            # catalog_number=[' ', ': 15985\n  ']
                            catalog_number = [catalog_number[0][2:].strip()]
                            catalog_link = ['']  # To make it clear
                        elif len(catalog_link) == 1:  # Single catalog number with link:
                            catalog_number = external_id_node.xpath('./a/text()')
                        else:  # catalog number with more than one link
                            if catalog_name[0] == 'ASIN':
                                # One link per national website. The list of country abbreviations is in catalog_number
                                # ['AU', 'BR', 'CA', 'CN', 'DE', 'ES', 'FR', 'IN', 'IT', 'JP', 'MX', 'NL', 'TR', 'UAE', 'UK', 'US']
                                # The list of corresponding links is in catalog_link:
                                # ['https://www.amazon.com.au/dp/B00PUKJ5TC', 'https://www.amazon.com.br/dp/B00PUKJ5TC', 'https://www.amazon.ca/dp/B00PUKJ5TC', 'https://www.amazon.cn/dp/B00PUKJ5TC', 'https://www.amazon.de/dp/B00PUKJ5TC', 'https://www.amazon.es/dp/B00PUKJ5TC', 'https://www.amazon.fr/dp/B00PUKJ5TC', 'https://www.amazon.in/dp/B00PUKJ5TC', 'https://www.amazon.it/dp/B00PUKJ5TC', 'https://www.amazon.co.jp/dp/B00PUKJ5TC', 'https://www.amazon.com.mx/dp/B00PUKJ5TC', 'https://www.amazon.nl/dp/B00PUKJ5TC', 'https://www.amazon.com.tr/dp/B00PUKJ5TC', 'https://www.amazon.ae/dp/B00PUKJ5TC', 'https://www.amazon.co.uk/dp/B00PUKJ5TC?ie=UTF8&tag=isfdb-21', 'https://www.amazon.com/dp/B00PUKJ5TC?ie=UTF8&tag=isfdb-20&linkCode=as2&camp=1789&creative=9325']
                                catalog_countries = external_id_node.xpath('./a/text()')  # Get the country list
                                if prefs['log_level'] in 'DEBUG':
                                    log.debug('catalog_countries={0}'.format(catalog_countries))
                                catalog_number = [
                                    catalog_link[0][-10:]]  # Extract the ASIN (always) 10 chars) from link
                                # Choose the appropriate link depending on user language
                                catalog_link_full = catalog_link
                                catalog_link = ['']
                                country_no = catalog_countries.index(LOCALE_COUNTRY)
                                if prefs['log_level'] in 'DEBUG':
                                    log.debug('LOCALE_COUNTRY={0}, country_no={1}'.format(LOCALE_COUNTRY, country_no))
                                try:
                                    catalog_link = [catalog_link_full[country_no]]
                                except ValueError:
                                    try:
                                        country_no = catalog_countries.index('US')
                                        catalog_link = [catalog_link_full[country_no]]
                                    except ValueError:
                                        catalog_link = [catalog_link_full[0]]  # Take the first one
                            else:
                                catalog_number = external_id_node.xpath('./a/text()')
                                catalog_link = ['']
                                log.debug(_('Unknown catalog with more than one link.'))
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('catalog_name={0}'.format(catalog_name))
                            log.debug('catalog_number={0}'.format(catalog_number))
                            log.debug('catalog_link={0}'.format(catalog_link))
                        if catalog_name[0] in EXTERNAL_IDS:
                            calibre_identifier_type = EXTERNAL_IDS[catalog_name[0]][0]
                        else:
                            calibre_identifier_type = catalog_name[0].lower()
                            for char in [' ', '/', '.']:
                                # replace() "returns" an altered string
                                calibre_identifier_type = calibre_identifier_type.replace(char, "-")
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('calibre_identifier_type={0}'.format(calibre_identifier_type))
                        # ToDo: save link for calibre book info window (direct access to metadata source)?
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('catalog_number={0}'.format(catalog_number))
                        properties["identifiers"].update({calibre_identifier_type: catalog_number[0]})
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('properties["identifiers"]={0}'.format(properties["identifiers"]))

                elif section == 'Catalog ID':
                    properties["isfdb-catalog"] = detail_node[0].tail.strip()

                elif section == 'Container Title':
                    title_url = detail_nodes[9].xpath('a')[0].attrib.get('href')
                    properties["isfdb-title"] = Title.id_from_url(title_url)

                # If we have a series name, but no series index, try to build the index from the pub date
                if "series" in properties:
                    if properties["series"] != '':
                        if properties["series_index"] == 0.0:
                            if date_text != '':
                                year, month, day = [int(p) for p in date_text.split("-")]
                                properties["series_index"] = float(year) + float(month) * 0.01
                                if prefs['log_level'] in 'DEBUG':
                                    log.debug('properties["series_index"], taken from pubdate={0}'
                                              .format(properties["series_index"]))
                # ToDo: ? Pub year, but spring, summer, ...

            except Exception as e:
                log.exception(_('Error parsing section %r for url: %r. Error: %r') % (section, url, e))

        # The second content box, if present, contains the pub title (extended) and the table of contents
        try:
            # Get rid of tooltips
            for tooltip in root.xpath('//sup[@class="mouseover"]'):
                # We grab the parent of the element to call the remove directly on it
                tooltip.getparent().remove(tooltip)
            for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
                # We grab the parent of the element to call the remove directly on it
                tooltip.getparent().remove(tooltip)
            for tooltip in root.xpath('//div[@class="tooltip tooltipright"]'):
                # We grab the parent of the element to call the remove directly on it
                remove_node(tooltip, keep_content=True)  # but save the author's name
            # contents_node = root.xpath('//div[@class="ContentBox"][2]/ul')
            # Contents (view Concise Listing)
            number_of_content_boxes = len(root.findall('.//div[@class="ContentBox"]'))
            if prefs['log_level'] in 'DEBUG':
                log.debug('number_of_content_boxes={0}'.format(number_of_content_boxes))
            if number_of_content_boxes > 1:
                contents_node = root.xpath('//div[@class="ContentBox"][2]')
            else:
                contents_node = []
            if number_of_content_boxes > 1:
                # xyz = _(contents_node[1].text_content().strip())
                if prefs['log_level'] in 'DEBUG':
                    for contents_node_line in contents_node:
                        contents_node_line_str = etree.tostring(contents_node_line)
                        log.debug('contents_node_line={0}'.format(contents_node_line_str))
                title_node = root.xpath('//div[@class="ContentBox"][2]/ul/li//a[1]/@href')
                if prefs['log_level'] in 'DEBUG':
                    log.debug('title_node={0}'.format(title_node))
                title_id = title_node[0][title_node[0].index('?') + 1:]
                properties["isfdb-title"] = title_id
                properties["comments"] = sanitize_comments_html(tostring(contents_node[0], method='html'))
                if prefs["translate_isfdb"]:
                    for term in TRANSLATION_REPLACINGS:
                        # log.debug('term, msgtext='.format(term, _(term)))
                        properties["comments"] = properties["comments"].replace(term, _(term))
            else:
                if prefs['log_level'] in ['INFO', 'DEBUG']:
                    log.debug('No second content box found!')
        except Exception as e:
            log.exception(_('Error parsing the second content box for url: %r. Error: %r') % (url, e))

        combined_comments = ''
        for k in sorted(properties):
            if k in ['synopsis', 'comments', 'notes', 'series_notes', 'series_number_notes', 'user_rating', 'webpage',
                     'series_webpages', 'cover']:
                combined_comments = combined_comments + properties[k] + '<br />'
        properties["comments"] = combined_comments + _('Source for publication metadata: ') + url

        # no series info was found in ContentBox #1, so look in ContenBox #2:
        # ToDo: See series search in title class

        if "series" not in properties:
            log.info(_('No series found so far. Looking further.'))
            # <span class="containertitle">Editor Title:</span>
            # <a href="https://www.isfdb.org/cgi-bin/title.cgi?2595721" dir="ltr">Utopia-Science-Fiction-Magazin - 1958</a>
            # <a href="https://www.isfdb.org/cgi-bin/pe.cgi?48353" dir="ltr">Utopia-Science-Fiction-Magazin</a>
            # <a href="https://www.isfdb.org/cgi-bin/ea.cgi?302325" dir="ltr">Bert Horsley</a>
            # Scan series record

            # ToDo: This makes unwanted series entries (series name = author name)?

            properties["series"] = ''
            try:
                # if ISFDB3.loc_prefs["combine_series"]:
                # If series is an url, open series page and search for "Sub-series of:"
                series_url = str(root.xpath('//*[@id="content"]/div[2]/a[2]/@href')[0])
                if prefs['log_level'] in 'DEBUG':
                    log.debug('url={0}'.format(series_url))
                # https://www.isfdb.org/cgi-bin/ea.cgi?249
                if '/ea.cgi?' in series_url:
                    raise KeyError  # url leads to an author page
                properties["series"] = Series.from_url(browser, series_url, timeout, log, prefs)
                if properties["series"] == '':
                    properties["series"] = root.xpath('//*[@id="content"]/div[2]/a[2]')[0].text_content().strip()
                if prefs['log_level'] in 'DEBUG':
                    log.debug('properties["series"]={0}'.format(properties["series"]))
                if '#' in properties["title"]:
                    match = re.search('#(\d+)', properties["title"], re.IGNORECASE)
                    if match:
                        # properties["series_index"] = float(int("".join(filter(match.group(1).isdigit, match.group(1)))))
                        properties["series_index"] = float(match.group(1))
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('properties["series_index"]={0}'.format(properties["series_index"]))
                else:
                    # Check next content box for series index
                    # /html/body/div/div[3]/div[2]
                    # #content > div:nth-child(2)
                    # //*[@id="content"]/div[2]
                    # issues = root.xpath('//*[@id="content"]/div[2]/ul/li')
                    # for issue in issues:
                    #     log.debug('issue={0}'.format(issue))
                    #     #.text_content().strip()
                    pass  # ToDo

                properties["comments"] = properties["comments"] + '<br />' + _('Source for series metadata: ') + series_url
            except (IndexError, KeyError):
                if prefs['log_level'] in ('DEBUG', 'INFO'):
                    log.info(_('No series found at all.'))

        try:
            img_src = root.xpath('//div[@id="content"]//table/tr[1]/td[1]/a/img/@src')
            if img_src:
                properties["cover_url"] = img_src[0]
        except Exception as e:
            log.exception(_('Error parsing cover for url: %r. Error: %r') % (url, e))

        # Workaround to avoid merging publications with eeh same title and author(s) by Calibre's default behavior
        # Publication.BOOK_PUB_NO = Publication.BOOK_PUB_NO + 1
        # properties['book_publication'] = Publication.BOOK_PUB_NO

        return properties


class TitleCovers(Record):
    # URL = 'http://www.isfdb.org/cgi-bin/titlecovers.cgi?'
    URL = 'https://www.isfdb.org/cgi-bin/titlecovers.cgi?'

    @classmethod
    def url_from_id(cls, title_id):
        return cls.URL + title_id

    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).group(1)

    @classmethod
    def from_url(cls, browser, url, timeout, log, prefs):
        covers = []
        location, root = cls.root_from_url(browser, url, timeout, log, prefs)

        # Get rid of tooltips
        for tooltip in root.xpath('//sup[@class="mouseover"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it
        for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it

        covers = root.xpath('//div[@id="main"]/a/img/@src')
        if prefs['log_level'] in 'DEBUG':
            log.debug("Parsed covers from url %r. Found %d covers." % (url, len(covers)))
        return covers


class Title(Record):
    # title record -> publication record(s) (m:n)

    # URL = 'http://www.isfdb.org/cgi-bin/title.cgi?'
    URL = 'https://www.isfdb.org/cgi-bin/title.cgi?'
    # 'https://www.isfdb.org/cgi-bin/title.cgi?57736'

    @classmethod
    def url_from_id(cls, isfdb_title_id):
        return cls.URL + isfdb_title_id

    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).group(1)

    @classmethod
    def stub_from_search(cls, row, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug('*** Enter Title.stub_from_search().')
            log.debug('row={0}'.format(row.xpath('.')[0].text_content()))

        properties = {}

        if row is None:
            if prefs['log_level'] in ('DEBUG', 'INFO', 'ERROR'):
                log.error(_('Title.stub_from_search(): row is None.'))
            return properties

        try:
            # #main > form > table > tbody > tr.table1 > td:nth-child(5)
            properties["title"] = row.xpath('td[5]/a')[0].text_content()
            properties["url"] = row.xpath('td[5]/a/@href')[0]
            properties["date"] = row.xpath('td[1]')[0].text_content()
        except IndexError:
            # Handling Tooltip in div
            # //*[@id="main"]/form/table/tbody/tr[3]/td[5]/div
            properties["title"] = row.xpath('td[5]/div/a/text()')[0]
            properties["url"] = row.xpath('td[5]/div/a/@href')[0]
            properties["date"] = row.xpath('td[1]')[0].text_content()
        if prefs['log_level'] in 'DEBUG':
            log.debug('properties["title"]={0}, properties["url"]={1}.'.format(properties["title"], properties["url"]))

        try:
            properties["authors"] = [a.text_content() for a in row.xpath('td[6]/a')]
        except IndexError:
            # Handling Tooltip in div
            properties["authors"] = [a.text_content() for a in row.xpath('td[6]/div/a/text()')]

        # Workaround to avoid merging titles with eeh same title and author(s) by Calibre's default behavior
        # Title.BOOK_TITLE_NO = Title.BOOK_TITLE_NO + 1
        # properties['book_title'] = Title.BOOK_TITLE_NO

        if prefs['log_level'] in 'DEBUG':
            log.debug('properties={0}'.format(properties))

        return properties

    @classmethod
    def stub_from_simple_search(cls, row, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug('*** Enter Title.stub_from_simple_search().')
            log.debug('row={0}'.format(row.xpath('.')[0].text_content()))

        properties = {}

        if row is None:
            if prefs['log_level'] in ('DEBUG', 'INFO', 'ERROR'):
                log.error(_('Title.stub_from_simple_search(): row is None.'))
            return properties

        try:
            # #main > form > table > tbody > tr.table1 > td:nth-child(5)
            properties["title"] = row.xpath('td[4]/a')[0].text_content()
            properties["url"] = row.xpath('td[4]/a/@href')[0]
            properties["date"] = row.xpath('td[1]')[0].text_content()
        except IndexError:
            # Handling Tooltip in div
            # //*[@id="main"]/form/table/tbody/tr[3]/td[5]/div
            properties["title"] = row.xpath('td[4]/div/a/text()')[0]
            properties["url"] = row.xpath('td[4]/div/a/@href')[0]
            properties["date"] = row.xpath('td[1]')[0].text_content()
        if prefs['log_level'] in 'DEBUG':
            log.debug('properties["title"]={0}, properties["url"]={1}.'.format(properties["title"], properties["url"]))

        try:
            properties["authors"] = [a.text_content() for a in row.xpath('td[5]/a')]
        except IndexError:
            # Handling Tooltip in div
            properties["authors"] = [a.text_content() for a in row.xpath('td[5]/div/a/text()')]

        # Workaround to avoid merging titles with eeh same title and author(s) by Calibre's default behavior
        # Title.BOOK_TITLE_NO = Title.BOOK_TITLE_NO + 1
        # properties['book_title'] = Title.BOOK_TITLE_NO

        if prefs['log_level'] in 'DEBUG':
            log.debug('properties={0}'.format(properties))
        return properties

    @classmethod
    def from_url(cls, browser, url, timeout, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug('*** Enter Title.from_url().')
            log.debug('url={0}'.format(url))

        title_url = url  # Save url for comments

        properties = {"isfdb-title": cls.id_from_url(url)}

        location, root = cls.root_from_url(browser, url, timeout, log, prefs)

        # Get rid of tooltips
        for tooltip in root.xpath('//sup[@class="mouseover"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it
        for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it

        detail_div = root.xpath('//div[@class="ContentBox"]')[0]

        detail_nodes = []
        detail_node = []
        for e in detail_div:
            if e.tag in ['br', '/div']:
                detail_nodes.append(detail_node)
                detail_node = []
            else:
                detail_node.append(e)
        detail_nodes.append(detail_node)

        for detail_node in detail_nodes:
            if prefs['log_level'] in 'DEBUG':
                if len(detail_node) > 0:
                    for ni in range(len(detail_node) - 1):
                        log.debug('detail_node={0}'.format(etree.tostring(detail_node[ni])))
                else:
                    log.debug('detail_node={0}'.format(etree.tostring(detail_node)))
            section = detail_node[0].text_content().strip().rstrip(':')
            if prefs['log_level'] in 'DEBUG':
                log.debug('section={0}'.format(section))
            section_text_content = detail_node[0].tail.strip()
            if section_text_content == '':
                try:
                    section_text_content = detail_node[1].xpath('text()')  # extract link text
                except Exception as e:
                    if prefs['log_level'] in ('DEBUG', 'INFO', 'ERROR'):
                        log.error('Error: {0}.'.format(e))
            if prefs['log_level'] in 'DEBUG':
                log.debug('section={0}, section_text_content={1}.'.format(section, section_text_content))

            date_text = ''  # Fallback vor series index construction

            try:

                if section == 'Title':
                    properties["title"] = detail_node[0].tail.strip()
                    if not properties["title"]:
                        # assume an extra span with a transliterated title tooltip
                        properties["title"] = detail_node[1].text_content().split('?')[0].strip()

                elif section in ('Author', 'Authors', 'Editor', 'Editors'):
                    properties["authors"] = []
                    author_links = [e for e in detail_node if e.tag == 'a']
                    for a in author_links:
                        author = a.text_content().strip()
                        if author != 'uncredited':
                            if section.startswith('Editor'):
                                if prefs["translate_isfdb"]:
                                    properties["authors"].append(author + _(' (Editor)'))
                                else:
                                    properties["authors"].append(author + ' (Editor)')
                            else:
                                properties["authors"].append(author)

                elif section == 'Type':
                    properties["type"] = detail_node[0].tail.strip()
                    # Copy title type to tags
                    if "tags" not in properties:
                        properties["tags"] = []
                    try:
                        tags = TYPE_TO_TAG[properties["type"]]
                        if prefs["translate_isfdb"]:
                            # ToDo: Loop thru tags in list and translate them
                            tags = _(tags)
                        properties["tags"].extend([t.strip() for t in tags.split(",")])
                    except KeyError:
                        pass

                elif section == 'Length':
                    properties["length"] = detail_node[0].tail.strip()
                    if "tags" not in properties:
                        properties["tags"] = []
                    properties["tags"].append(properties["length"])

                elif section == 'Date':
                    # In a title record, the date points always to the first publishing date (copyright)
                    date_text = detail_node[0].tail.strip()
                    # Make sure if date text is suitable to build a date object (empty string or "date unknown" etc)
                    try:
                        # We use this instead of strptime to handle dummy days and months
                        # E.g. 1965-00-00
                        year, month, day = [int(p) for p in date_text.split("-")]
                        month = month or 1
                        day = day or 1
                        # Correct datetime result for day = 0: Set hour to 2 UTC
                        # (if not, datetime goes back to the last month and, in january, even to december last year)
                        properties["pubdate"] = datetime.datetime(year, month, day, 2, 0, 0)
                    except:
                        pass

                elif section == 'Series':
                    if prefs['log_level'] in 'DEBUG':
                        log.debug('Section "Series" found: {0}'.format(detail_node[0].tail.strip()))
                        log.debug('Section "Series" found: {0}'.format(detail_node[1].text_content().strip()))
                    # If series is an url, open series page and search for "Sub-series of:"
                    # https://www.isfdb.org/cgi-bin/pe.cgi?45706
                    # Scan series record
                    # Testen: Titel:War of the Maelstrom (Pub #2)Autoren:Jack L. Chalker
                    properties["series"] = detail_node[0].tail.strip()
                    if properties["series"] == '':
                        properties["series"] = detail_node[1].text_content().strip()
                        url = str(detail_node[1].xpath('./@href')[0])
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('Properties "Series" is a url: {0} - {1}'.format(properties["series"], url))
                        properties["series"] = Series.from_url(browser, url, timeout, log, prefs)
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('Properties "Series"={0}'.format(properties["series"]))

                    if prefs['log_level'] in 'DEBUG':
                        log.debug('Properties "Series"={0}'.format(properties["series"]))
                    if properties["series"] == '':
                        properties["series"] = detail_node[1].text_content().strip()
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('Properties "Series"={0}'.format(properties["series"]))

                elif section == 'Series Number':
                    if prefs['log_level'] in 'DEBUG':
                        log.debug('Section "Series Number" found: {0}'.format(detail_node[0].tail.strip()))
                    if properties["series"] != '':
                        if prefs['log_level'] in ('DEBUG', 'INFO'):
                            log.info(
                                _('Series is: "{0}". Now searching series index in "{1}"'.
                                  format(properties["series"], detail_node[0].tail.strip())))
                        if detail_node[0].tail.strip() == '':
                            properties["series_index"] = 0.0
                        elif '/' in detail_node[0].tail:
                            # Calibre accepts only float format compatible numbers, not e. g. "61/62"
                            series_index_list = detail_node[0].tail.split('/')
                            # properties["series_index"] = float(series_index_list[0].strip())
                            properties["series_index"] = float(int("".join(filter(str.isdigit, series_index_list[0])).strip()))
                            properties["series_number_notes"] = \
                                _("Reported number was {0} and was reduced to a Calibre compatible format."). \
                                    format(detail_node[0].tail)
                        elif is_roman_numeral(detail_node[0].tail.strip()):
                            if prefs['log_level'] in 'DEBUG':
                                log.debug('Roman literal found:{0}'.format(detail_node[0].tail.strip()))
                            # Calibre accepts only float format compatible arabic numbers, not roman numerals e. g. "IV"
                            # https://www.isfdb.org/cgi-bin/pl.cgi?243949
                            properties["series_index"] = float(roman_to_int(detail_node[0].tail.strip()))
                            properties["series_number_notes"] = \
                                _("Reported number was the roman numeral {0} and was converted to a Calibre compatible format.<br />"). \
                                    format(detail_node[0].tail.strip())
                        else:
                            try:
                                properties["series_index"] = float(int(
                                    "".join(filter(str.isdigit, detail_node[0].tail.strip()))))
                            except ValueError:
                                properties["series_number_notes"] = \
                                    _("Could not convert {0} to a Calibre compatible format.<br />"). \
                                        format(detail_node[0].tail.strip())
                                properties["series_index"] = 0.0
                                if prefs['log_level'] in ('DEBUG', 'INFO', 'ERROR'):
                                    log.error('"Could not convert {0} to a Calibre compatible format.<br />"'.format(
                                        detail_node[0].tail.strip()))
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('properties["series_index"]={0}'.format(properties["series_index"]))

                elif section == 'Webpages':
                    properties["webpages"] = str(detail_node[1].xpath('./@href')[0])
                    if prefs['log_level'] in 'DEBUG':
                        log.debug('properties["webpages"]={0}'.format(properties["webpages"]))

                elif section == 'Language':
                    properties["language"] = detail_node[0].tail.strip()
                    # For calibre, the strings must be in the language of the current locale
                    # Both Calibre and ISFDB use ISO 639-2 language codes,
                    # but in the ISFDB web page only the language names are shown
                    try:
                        # properties["language"] = myglobals.LANGUAGES[properties["language"]]
                        properties["language"] = LANGUAGES[properties["language"]]
                    except KeyError:
                        pass

                elif section == 'Synopsis':
                    properties["synopsis"] = detail_node[0].tail.strip()

                elif section == 'Note':
                    if "notes" not in properties:
                        properties["notes"] = detail_node[0].tail.strip()
                    else:
                        properties["notes"] = properties["notes"] + '<br />' + detail_node[0].tail.strip()

                # Test with: https://www.isfdb.org/cgi-bin/title.cgi?1360234
                # ISFDB: user rating is float between 1 and 10. Meanings are:
                # 1 - Extremely poor. One of the worst titles ever written. Couldn't be any worse.
                # 2 - Very bad, with minor redeeming characteristics.
                # 3 - Bad.
                # 4 - Below average.
                # 5 - Slightly below average.
                # 6 - Slightly above average.
                # 7 - Above average.
                # 8 - Good; recommended.
                # 9 - Very good, but not quite perfect.
                # 10 - Excellent. One of the best titles ever written. Couldn't be any better.
                # Calibre: In GUI, ratings going from one to five stars, internal values are float between 1 and 10.
                # (see https://www.mobileread.com/forums/showthread.php?t=289594)
                # Title: Etaoin ShrdluTitle Record # 41652 [Edit] [Edit History]
                # Author: Fredric Brown
                # User Rating: 5.60 (5 votes) Your vote: Not cast VOTE
                elif section == 'User Rating':
                    if 'This title has no votes' not in detail_node[0].tail.strip():
                        # 9.49 (45 votes)
                        # Number of votes don't exist in Calibre, so put it in comments.
                        properties["user_rating"] = detail_node[0].tail.strip()
                        rating = properties["user_rating"]
                        rating = float(re.search('(\d+\.\d+)', rating).group(1)) * 0.5  # Convert to five-star system
                        properties["rating"] = rating  # Calibre rating field

                elif section == 'Current Tags':
                    # Current Tags: None
                    if detail_node[0].tail.strip() != 'None':
                        if "tags" not in properties:
                            properties["tags"] = []
                        # Current Tags: enhanced intelligence (1), genetics (1), Daniel Keyes (1)
                        tag_links = [e for e in detail_node if e.tag == 'a']
                        for a in tag_links:
                            tag = a.text_content().strip()
                            if tag != "Add Tags":
                                properties["tags"].append(tag)
                                if prefs['log_level'] in 'DEBUG':
                                    log.debug('tag "{0}" added.'.format(tag))

                elif section == 'Variant Title of':
                    if "notes" not in properties:
                        properties["notes"] = 'Variant Title of ' + detail_node[0].tail.strip()
                    else:
                        properties["notes"] = properties["notes"] + '<br />' + 'Variant Title of ' + detail_node[
                            0].tail.strip()

            except Exception as e:
                log.exception(_('Error parsing section {0} for url: {1}. Error: {2}').format(section, url, e))

        if 'comments' in properties:
            properties["comments"] = properties["comments"] + '<br />' + _('Source for title metadata: ') + title_url
        else:
            properties["comments"] = '<br />' + _('Source for title metadata: ') + title_url

        # Save all publication ids for this title
        publication_links = root.xpath('//a[contains(@href, "/pl.cgi?")]/@href')
        properties["publications"] = [Publication.id_from_url(l) for l in publication_links]

        # If the title date is in pub list, set the publication text and link in comment as "First published in: ..."
        if 'pubdate' in properties:
            title_date = properties["pubdate"].isoformat()[:10]
            if prefs['log_level'] in 'DEBUG':
                log.debug('title date={0}'.format(title_date))
            pubrows = root.xpath('//table[@class="publications"]/tr')
            for pubrow in pubrows:
                pub_date = ''.join(pubrow.xpath('./td[2]/text()')).strip()
                if pub_date != '':
                    if prefs['log_level'] in 'DEBUG':
                        log.debug('pub_date={0}'.format(pub_date))
                    # Ignore day if day in pubdate is zero
                    if pub_date[-2:] == '00':
                        pub_date = pub_date[:-2] + title_date[-2:]
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('pub_date={0}'.format(pub_date))
                    if pub_date == title_date:
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('pub_date found in pub table.')
                        # Extracting the text content of the first two cells (pub title and link, pubdate)
                        pub_title = ''.join(pubrow.xpath('./td[1]/a/text()'))
                        pub_link = ''.join(pubrow.xpath('./td[1]/a/@href'))
                        pub_info = pub_title + ' (' + pub_link + ').'
                        if prefs['log_level'] in 'DEBUG':
                            log.debug('pub_info={0}'.format(pub_info))
                        if 'comments' in properties:
                            properties["comments"] = properties["comments"] + '<br />' + _('First published in: ') + pub_info
                        else:
                            properties["comments"] = '<br />' + _('First published in: ') + pub_info
                        break

        return properties


class Series(Record):
    # URL = 'http://www.isfdb.org/cgi-bin/pe.cgi?'
    URL = 'https://www.isfdb.org/cgi-bin/pe.cgi?'

    @classmethod
    def root_from_url(cls, browser, url, timeout, log, prefs):
        if prefs['log_level'] in 'DEBUG':
            log.debug('*** Enter Series.root_from_url().')
            log.debug('url={0}'.format(url))
        response = browser.open_novisit(url, timeout=timeout)
        location = response.geturl()  # guess url in case of redirection
        raw = response.read()
        # Parses an XML document or fragment from a string. Returns the root node (or the result returned by a parser target).
        # To override the default parser with a different parser you can pass it to the parser keyword argument.
        # The base_url keyword argument allows to set the original base URL of the document to support relative Paths
        # when looking up external entities (DTD, XInclude, ...).
        return fromstring(clean_ascii_chars(raw))

    @classmethod
    def url_from_id(cls, title_id):
        return cls.URL + title_id

    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).group(1)

    @classmethod
    def from_url(cls, browser, url, timeout, log, prefs):

        if prefs['log_level'] in 'DEBUG':
            log.debug('*** Enter Series.from_url().')
            log.debug('url={0}'.format(url))

        properties = {"series": '', "main_series": '', "series_tags": list(''), "series_notes": '',
                      "series_webpages": ''}
        # ToDo: if series in properties:
        # properties["sub_series"] = ''
        series_candidate = ''
        full_series = ''

        location, root = Series.root_from_url(browser, url, timeout, log, prefs)

        # Is this an author record?
        if 'Author Record #' in etree.tostring(root, encoding='utf8', method='xml').decode():
            if prefs['log_level'] in 'DEBUG':
                log.debug('This is a author record page, no series page. Quit.')
            return ''

        # Get rid of tooltips
        for tooltip in root.xpath('//sup[@class="mouseover"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it
        for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it

        detail_nodes = root.xpath('//div[@id="content"]/div[@class="ContentBox"][1]/ul/li')
        if prefs['log_level'] in 'DEBUG':
            log.debug('Found {0} detail_nodes.'.format(len(detail_nodes)))

        # Series record of title records looks like:
        # Series: Discworld                    Series Record # 186
        # Webpages: Wikipedia-EN
        # Note: Series in German called 'Scheibenwelt'.
        # Series Tags: humorous fantasy (50), fantasy (15), young-adult (15), magic school (12), into-tv (6), Young Adult (4), witches (3), death personified (3), monsters (2), Fantasy: The 100 Best Books (2), endless war (2), quiz book (2), Inventions (1), China-inspired fantasy (1), music (1), elves (1), ancient-Egypt-inspired (1), pyramids (1), fairy tale inspiration (1), pantheon (1) and 56 additional tags.
        # or:
        # Series: Classic-Zyklus                              Series Record # 45706
        # Sub-series of: Ren Dhark Universe
        # or:
        # Series: Krieg zwischen den Milchstraßen             Series Record # 38399
        # or:
        # Series: Utopia-Science-Fiction-Magazin              Series Record # 48353
        # Sub-series of: Utopia-Sonderband / Science Fiction-Magazin

        # Series record of publication records looks like:
        # Publication Series: Terra                           Pub. Series Record # 1094
        # Webpages: Wikipedia-EN
        # Note: Series run from 1957 until 1968 and counts 555 issues. It was continued by Terra Nova.

        # ToDo:
        # Problem: Pub Record without title record give no series info:
        # Series: Utopia-Science-Fiction-MagazinSeries Record # 48353
        # Sub-series of: Utopia-Sonderband / Science Fiction-Magazin
        # Utopia-Sonderband / Science Fiction-Magazin (View Issue Grid)
        # 1 Utopia-Sonderband (View Issue Grid)
        #   Utopia-Sonderband - 1955 (1955) [ED] by Clark Darlton [only as by Walter Ernsting]
        #   Utopia-Sonderband - 1956 (1956) [ED] by Clark Darlton [only as by Walter Ernsting]
        # 2 Utopia-Science-Fiction-Magazin (View Issue Grid)
        #   Utopia-Science-Fiction-Magazin - 1956 (1956) [ED] by Clark Darlton [only as by Walter Ernsting]
        #   Utopia-Science-Fiction-Magazin - 1957 (1957) [ED] by Clark Darlton [only as by Walter Ernsting]
        #   Utopia-Science-Fiction-Magazin - 1958 (1958) [ED] by Bert Horsley
        #   Utopia-Science-Fiction-Magazin - 1958 (1958) [ED] by Bert Koeppen
        #   Utopia-Science-Fiction-Magazin - 1959 (1959) [ED] by Bert Koeppen

        # Title: Utopia-Science-Fiction-Magazin - 1958Title Record # 2595721
        # Editor: Bert Horsley
        # Date: 1958-04-00
        # Type: EDITOR
        # Series: Utopia-Science-Fiction-Magazin
        # Language: German
        # User Rating: This title has no votes. VOTE
        # Current Tags: None
        # Add quick tag:
        # select a value
        #   or manage Tags
        # Publications
        # Title	Date	Author/Editor	Publisher/Pub. Series	ISBN/Catalog ID	Price	Pages	Format	Type	Cover Artist	Verif
        # Utopia-Science-Fiction-Magazin, #10	1958-04-07	ed. uncredited	Pabel	USFM10	DM 1.00	96	digest?	mag	Emsh	Checkmark
        # Utopia-Science-Fiction-Magazin, #11	1958-05-05	ed. uncredited	Pa

        for detail_node in detail_nodes:
            html_line = detail_node.text_content()
            if prefs['log_level'] in 'DEBUG':
                log.debug('html_line={0}'.format(html_line))
            series_captions = ['Publication Series:', 'Series:']
            series_record_captions = ['Pub. Series Record #', 'Series Record #']
            for series_caption in series_captions:
                if series_caption in html_line:
                    series_candidate = html_line.split(series_caption, 1)[1].strip()
                    idx = series_captions.index(series_caption)
                    properties["series"] = series_candidate.split(series_record_captions[idx], 1)[0].strip()
                    if prefs['log_level'] in 'DEBUG':
                        log.debug('properties["series"]={0}'.format(properties["series"]))
                    # series_candidate = html_line.split(series_caption, 1)[1].strip()
                    # idx = series_captions.index(series_caption)
                    # series_candidate = series_candidate.split(series_record_captions[idx], 1)[0].strip()
                    # log.info('series_candidate={0}'.format(series_candidate))
                    # if properties["series"] != '':
                    #     properties["sub_series"] = series_candidate
                    #     break
                    # else:
                    #     properties["series"] = series_candidate
                    #     break
                    break
            if 'Sub-series of:' in html_line:  # check for main series, if any
                properties["main_series"] = html_line.split("Sub-series of:", 1)[1].strip()
                if prefs['log_level'] in 'DEBUG':
                    log.debug('properties["main_series"]={0}'.format(properties["main_series"]))
                break
            if 'Series Tags:' in html_line:  # check for series tags, if any
                series_tags = html_line.split("Series Tags:", 1)[1].strip()
                if prefs['log_level'] in 'DEBUG':
                    log.debug('series_tags={0}'.format(series_tags))
                # fantasy (3), horror (3), necromancers (1), sword and sorcery (1), heroic fantasy (1)
                series_tags_clean = re.sub('\([0-9]*\)]', '', series_tags)
                properties["series_tags"] = [x.strip() for x in series_tags_clean.split(',')]
                if prefs['log_level'] in 'DEBUG':
                    log.debug('properties["series_tags"]={0}'.format(properties["series_tags"]))
                if "tags" in properties:
                    properties["tags"].append(properties["series_tags"])
                else:
                    properties["tags"] = properties["series_tags"]
                break
            if 'Notes:' in html_line:  # check for series notes, if any
                properties["series_notes"] = html_line.split("Notes:", 1)[1].strip()
                if prefs['log_level'] in 'DEBUG':
                    log.debug('properties["series_notes"]={0}'.format(properties["series_notes"]))
                break
            if 'Webpages:' in html_line:  # check for series webpages, if any
                properties["series_webpages"] = html_line.split("Webpages:", 1)[1].strip()
                if prefs['log_level'] in 'DEBUG':
                    log.debug('properties["series_webpages"]={0}'.format(properties["series_webpages"]))
                # ToDo: Extract URL
                break

        if properties["main_series"] == '':
            full_series = properties["series"]
        else:
            # Managing calibre sub-groups: https://manual.calibre-ebook.com/de/sub_groups.html
            if prefs["combine_series"]:
                full_series = properties["main_series"] + prefs["combine_series_with"] + properties["series"]
            else:
                full_series = properties["main_series"]
        if prefs['log_level'] in 'DEBUG':
            log.debug('full_series={0}'.format(full_series))
        return full_series


class ISFDBWebAPI(object):
    # Not yet in use by ISFDB3 plugin

    # Ref: https://www.isfdb.org/wiki/index.php/Web_API

    # Publication Lookups
    # At this time there are two ways to retrieve publication data from the ISFDB database: by ISBN (getpub.cgi) and by
    # External ID (getpub_by_ID.cgi). The XML data returned by these two APIs is identical. A license key is not
    # required to use them. A valid query returns an XML payload which includes the following:
    # the Records tag which indicates the number of records found
    # zero or more Publication records containing the metadata for matching ISFDB publication record(s)

    host = "www.isfdb.org"

    # @classmethod
    # def root_from_url(cls, browser, url, timeout, log):
    #     log.info('*** Enter ISFDBWebAPI.root_from_url().')
    #     log.info('url={0}'.format(url))
    #     response = browser.open_novisit(url, timeout=timeout)
    #     raw = response.read()
    #     raw = raw.decode('iso_8859_1', 'ignore')
    #     # .encode(encoding='utf-8',errors='ignore')  # site encoding is iso-8859-1!
    #     # re-encode germans umlauts in an iso-8859-1 page to utf-8
    #     # properties["title"] = row.xpath('td[5]/a')[0].text_content().encode(encoding='UTF-8',errors='ignore')
    #     return fromstring(clean_ascii_chars(raw))

    # def GetXml(isbn):
    #     webservice = httpclient.HTTPConnection(host)
    #     command = '/cgi-bin/rest/getpub.cgi?%s' % isbn
    #     webservice.putrequest("GET", command)
    #     webservice.putheader("Host", host)
    #     webservice.putheader("User-Agent", "Wget/1.9+cvs-stable (Red Hat modified)")
    #     webservice.endheaders()
    #     errcode, errmsg, headers = webservice.getreply()
    #     if errcode != 200:
    #         resp = webservice.getfile()
    #         print("Error:", errmsg)
    #         print("Resp:", resp.read())
    #         resp.close()
    #         return ''
    #     else:
    #         resp = webservice.getfile()
    #         raw = resp.read()
    #         resp.close()
    #         index = raw.find('<?xml')
    #         return raw[index:]

    # Error Conditions
    # If no matching publication records are found, getpub.cgi and getpub_by_ID.cgi will return an XML structure
    # with the number of records set to zero:
    #
    # <?xml version="1.0" encoding="iso-8859-1" ?>
    # <ISFDB>
    #   <Records>0</Records>
    #   <Publications>
    #   </Publications>
    # </ISFDB>

    # <?xml version="1.0" encoding="iso-8859-1" ?>
    # <ISFDB>
    #  <Records>1</Records>
    #  <Publications>
    #    <Publication>
    #      <Record>325837</Record>
    #      <Title>The Winchester Horror</Title>
    #      <Authors>
    #        <Author>William F. Nolan</Author>
    #      </Authors>
    #      <Year>1998-00-00</Year>
    #      <Isbn>1881475530</Isbn>
    #      <Publisher>Cemetery Dance Publications</Publisher>
    #      <PubSeries>Cemetery Dance Novella</PubSeries>
    #      <PubSeriesNum>6</PubSeriesNum>
    #      <Price>$30.00</Price>
    #      <Pages>111</Pages>
    #      <Binding>hc</Binding>
    #      <Type>CHAPBOOK</Type>
    #      <Tag>THWNCHSTRH1998</Tag>
    #      <CoverArtists>
    #        <Artist>Eric Powell</Artist>
    #      </CoverArtists>
    #      <Note>Hardcover Limited Edition of 450 signed and numbered copies bound in full-cloth and Smyth sewn</Note>
    #      <External_IDs>
    #        <External_ID>
    #           <IDtype>1</IDtype>
    #           <IDtypeName>ASIN</IDtypeName>
    #           <IDvalue>B01G1K1RV8</IDvalue>
    #        </External_ID>
    #      </External_IDs>
    #    </Publication>
    #  </Publications>
    # </ISFDB>

    # getpub_by_ID.cgi
    # The getpub_by_ID.cgi API takes two arguments. The first argument is the External ID type --
    # see the leftmost column on the Advanced Publication Search by External Identifier page for a list of currently
    # supported External ID types. The second argument is the External ID value.
    # If more than one publication is associated with the requested External ID, multiple publication records will
    # be returned. The URL for getpub_by_ID.cgi should appear as follows:
    # https://www.isfdb.org/cgi-bin/rest/getpub_by_ID.cgi?ASIN+B0764JW7DK

    # getpub_by_internal_ID.cgi
    # The getpub_by_internal_ID.cgi API takes one argument, which must be the internal number/ID of the requested
    # publication. The URL for getpub_by_internal_ID.cgi should appear as follows:
    # https://www.isfdb.org/cgi-bin/rest/getpub_by_internal_ID.cgi?100 .
    # Note that, since internal publication IDs are unique within the ISFDB database, this API always returns one
    # record, but it uses the same XML structure as what is used by publication-specific APIs which can return m
    # ultiple records.

    #
