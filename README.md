[Metadata Source Plugin] ISFDB3 - Version 1.2.0 - 03-12-2023

Downloads metadata and covers from the Internet Speculative Fiction Database (http://www.isfdb.org/)

The ISFDB database provides a lot of data for sf titles and publications (covers, artists, translations, prices, notes, ...) and references to other sources, compiled by volunteers.

A web search form is available under http://www.isfdb.org/cgi-bin/adv_search_menu.cgi
There is also a web API under http://www.isfdb.org/wiki/index.php/Web_API, but this is not in use yet by the plugin, because the interface only supplies a subset of the data.

The data model distincts between titles and publications (connected m:n) and the database has also tables for series, translations, covers, ... A dump for MySQL is available under http://www.isfdb.org/wiki/index.php/ISFDB_Downloads.

Background:

This plugin is a fork of Adrianna Pińska's ISFDB2 (see https://github.com/confluence/isfdb2-calibre).
Adriana explained the very clever structure of her plugin herself in a YouTube video: »Custom metadata plugins for Caliber: cataloging an old paper library« (https://www.youtube.com/watch?v=UF6HAn5-YD0).

In mid 2021, I forked the codebase and make some changes and additions to the code for my needs.
Adriana contacted me and wrote: 
"Hello! I haven't worked on this for a while, but I intend to get back to it (I still haven't finished cataloguing my library!). 
When I do I will go through your code and see if I can merge some of the features. (...)
I don't mind if this plugin is submitted to the plugin repository -- but I am not active on the Mobileread forums, so I am unlikely to do this anytime soon. 
You are welcome to! If you decide to submit your forked version, please change the name (to isfdb3-calibre?), to make it clear that it's not the same plugin and may have slightly different behaviour."

So I have created the plugin ISFDB3 and submitted it to the plugin repository at mobileread.

Main changes compared to ISFDB2:

1) Different search strategy for publications
2) No mixing of identical titles

to 1): ISFDB2 searches publications (if no id is available) with the specified title and author. Publications are only found if they have the same search term as the title (i.e. have the same name).
ISFDB3 uses the list of publications in the title record and follows the links. So it may also find publications that contain the title (usually a short story) but have a different name, i.e. anthologies, magazines, ...
Extreme example: H. P. Lovecraft, In the Vault. ISFDB2 finds one title and no publications, ISFDB3 95 publications with this story.
Another example: Publications are not found by ISFDB2, if the title/publication pair as only a slightly different spelling:
Title: Best S.F. Stories from New Worlds (http://www.isfdb.org/cgi-bin/title.cgi?36317), but publication reads: Publication: Best S.F. Stories from New Worlds (http://www.isfdb.org/cgi-bin/pl.cgi?35921).

to 2): Calibre's default behavior merges titles and publicatications with the same author and title in one result, regardles of other data (publication date, series, publisher, ...).
Therefore, to preserve all search results, ISFDB3 qualifies the title field with the ISFDB id before put it in the result queue.
Example: K. H. Scheer, Expedition. The title was published six times in the years 1961 - 1980, in different series and adaptations. ISFDB2 returns only one publication, ISFDB3 all.
Other example (H. P. Lovecraft, In the Vault):
title list has two title records (in ISFDB2 there are merged to one):
title record one: http://www.isfdb.org/cgi-bin/title.cgi?2946687 -> pub record http://www.isfdb.org/cgi-bin/pl.cgi?868274
title record two: http://www.isfdb.org/cgi-bin/title.cgi?41896 -> a lot of pub records!

As a drawback, the qualifier in the title field has to be deleted manually or with a search-and-replace regex. 
And another: You probably need to increase the runtime for the plugin ("Configure Metadata Download" button).

Note for searching by title and author: Since the default search uses the keyword "contains", the title and author name may be shortened. This is always recommended when the spelling is in doubt ("Clark Ashton Smith" vs. "C.A. Smith" or "Eliteeinheit Luna Port" vs. "Eliteeinheit Lunaport").

Other changes compared to ISFDB2:

- Changes character encoding in GET parameters (search strings) from utf-8 to iso-8859-1 to avoid none matches for non-ASCII chars (for example german umlauts). The database data itself is in utf-8.
- Adds additional identifiers found in ISFDB. Currently: DNB and OCLC/WorldCat (more on request).
- Modifies the method "clean_downloaded_metadata()": Fixcase title and author(s) only when the title language is english.
- Gets additional info about series hierarchy from the series page. Option for combine main series and series names to use Calibre's hierarchical view feature.
- Workarounds for not Calibre's float format compatible series numbers (as 61/62 or roman numbers)
- Converts language field text in the isfdb to Calibre's language code

Planned Features / ToDo's:

There are a lot of to do's (and suggestions?).

- Notify referenced webpages (in pub record), if not already in Calibre's info window.
- Find series in the contents block (in pub record)
- Notify about translations in comments field

Limitations:

- Since there is no language field in publication records, only in title records, following the publication linkss in a title list may show up publications in not desired languages. However, the publications list in the title page has a button »Not displaying translations«, so some research is already meeded.

- For not logged in users, isfdb.org has recently stopped the advanced search access. 
  ISFDB3 has a fallback to simple search with itle only and a filter for record types (INTERIORART, ...).
  To avoid large title lists for short or generic titles ("Stars") with the default "contains" search, the search is switched to "exact match", if the first character in title field is an equal sign ("=").


Version History:

Version 1.2.0 03-12-2023
- New: Fetch all idemtifier types from ISFDB publication page.
- New: In simple sarch mode, very short or generic titles returns a lot of title and/or pub records.
  '=' as the first character in title fields raises an exact title search.
- Translation of ISFDB pages text as an option started (very experimental at the moment).
- Handling of unwanted tags fixed.
- New: Handling of ratings.
- Protocol of isfdb.org links is now https.
Version 1.1.6 02-17-2023
- Pub types added: NONFICTIOB and OMNIBUS (was ignored till now).
Version 1.1.5 01-27-2023
- Pub type added: MAGAZINE (was ignored till now).
Version 1.1.4 11-30-2022
- Handling redirection to a title page, if only one title record found.
Version 1.1.3 11-15-2022
- In simple search, to filter authors from title list, unquote the author's name from url
  (convert percent encoded characters back).
Version 1.1.2 07-14-2022
- Comparing author in simple search case-insensitive.
Version 1.1.1 07-13-2022
- Advanced search is now only for logged-in users. Fallback to simple search.
Version 1.1.0 02-16-2022
- Configuration for unwanted tags / Remove duplicates in tags.
- Erroneously series source link in comment, not source links for titles and pubs.
Version 1.0.3 02-10-2022
- Optimized title/pub merge: Cache title id for all pub ids in author/title search (analig search with ISBN).
Version 1.0.2 02-06-2022
- Parse error for dictionary LANGUAGES (moved from class to module scope).
- Typo in calling translate method.
Version 1.0.1 - 02-05-2022
- Small typo: none vs. None.
Version 1.0.0 - 01-31-2022
- Initial release.


Installation:

Download the attached zip file and install the plugin as described in the Introduction to plugins thread (https://www.mobileread.com/forums/showthread.php?t=118680).
The plugin is also available in Calibre's Plugin Updater.

How to report bugs and suggestions:

If you find any issues please report them in this thread or on Github: https://github.com/bertholdm/isfdb3-calibre.


