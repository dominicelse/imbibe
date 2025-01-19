import arxiv
import sys
import habanero
import re
import os
import os.path
import html
import unidecode
import argparse
import time
import progressbar
import json
import inspect
import urllib.request
import bibtexparser
import titlecase
import unicodedata
from lxml import etree
from io import StringIO

try:
    from imbibe.opts import optional_bibtex_fields
except ModuleNotFoundError:
    from imbibe.opts_default import optional_bibtex_fields

try:
    with open("capitalized_words.txt", "r") as f:
        protected_words = [ line.rstrip("\n") for line in f ]
except FileNotFoundError:
    protected_words = []
protected_words = set(protected_words)
protected_words_uppercase = dict( (word.upper(),word) for word in protected_words )

def thisdir():
    thisfile = inspect.getfile(inspect.currentframe())
    thisdir = os.path.dirname(thisfile)
    return thisdir

def load_journal_abbreviations():
    abbrev = {}

    import_order = [ 
      'journals/journal_abbreviations_acs.csv',
      'journals/journal_abbreviations_mathematics.csv',
      'journals/journal_abbreviations_ams.csv',
      'journals/journal_abbreviations_geology_physics.csv',
      'journals/journal_abbreviations_geology_physics_variations.csv',
      'journals/journal_abbreviations_ieee.csv',
      'journals/journal_abbreviations_lifescience.csv',
      'journals/journal_abbreviations_mechanical.csv',
      'journals/journal_abbreviations_meteorology.csv',
      'journals/journal_abbreviations_sociology.csv',
      'journals/journal_abbreviations_general.csv',
   ]

    import_order = [ os.path.join(thisdir(), filename) for filename in import_order ]
    custom_journals_filename = "journal_abbrev.csv"
    if os.path.exists(custom_journals_filename):
        import_order += [ custom_journals_filename ]
    
    for filename in import_order:
        with open(filename, "r", encoding='utf-8') as f:
            for line in f.readlines():
                line = line.rstrip()
                if ";" in line and line[0] != '#':
                    split = line.split(";")
                    name = split[0]
                    name_abbrev = split[1]

                    abbrev[name] = name_abbrev
    return abbrev
journal_abbreviations = load_journal_abbreviations()

def load_journal_aliases():
    filename = os.path.join(thisdir(), 'journal_aliases.txt')
    current_set = set()
    aliases = dict()
    with open(filename, "r", encoding="utf-8") as f:
        for line in f.readlines():
            line = line.rstrip()
            if line == '>>' and len(current_set) > 0:
                for name in current_set:
                    aliases[name.lower()] = current_set
                current_set = set()
            else:
                current_set.add(line)
    if len(current_set) != 0:
        raise RuntimeError("Syntax error in journal_aliases.txt")
    return aliases
journal_aliases = load_journal_aliases()

cr = habanero.Crossref(ua_string = "imbibe")

def unescape_string(s):
    return re.sub(r'(?<!\\)\\', '', s)

def bibtex_escape(s):
    # Bibtex can't deal with unmatched braces inside the entry, so we get rid of
    # them.
    def unmatched_brace_deleter(s, opposite=False):
        bracelevel = 0
        if opposite:
            closing = '{'
            opening = '}'
        else:
            closing = '}'
            opening = '{'
        for c in s:
            if c == closing:
                if bracelevel == 0:
                    continue
                bracelevel -= 1
            elif c == opening:
                bracelevel += 1
            yield c
    def reverse_string(s):
        return s[::-1]

    # Remove unmatched closing brace
    s = ''.join(unmatched_brace_deleter(s))

    # Remove unmatched opening brace
    s = reverse_string(s)
    s = ''.join(unmatched_brace_deleter(s, opposite=True))
    s = reverse_string(s)

    # todo: how do we know if we removed the right bracket?
    return s


def canonicalize_title(s):
    subs = { "\u2009": " ", "\xa0": " " }
    for c,rc in subs.items():
        s = s.replace(c, rc)
    return s.lower()

def titles_equal(t1,t2):
    return canonicalize_title(t1) == canonicalize_title(t2)

def populate_arxiv_information(list_of_bibitems):
    bibitems_with_arxivid = [ b for b in list_of_bibitems if
            (b.arxivid is not None and not b.arxiv_populated) ]
    arxiv_ids = [ b.arxivid for b in bibitems_with_arxivid ]

    if len(arxiv_ids) == 0:
        return

    results = list(arxiv.Search(id_list=arxiv_ids, max_results=len(arxiv_ids)).results())
    if len(results) != len(arxiv_ids):
        # Need to try all the arXiv IDs individually to find out which one was
        # not found.
        for i in range(len(arxiv_ids)):
            ret = list(arxiv.Search(id_list=[arxiv_ids[i]]).results())
            if len(ret) != 1:
                print("arXiv ID not found:" + arxiv_ids[i], file=sys.stderr)
                sys.exit(1)
        assert False

    for bibitem,result in zip(bibitems_with_arxivid, results):
        bibitem.read_arxiv_information(result)

def crossref_find_from_journalref(journaltitle, volume, number, year, articletitle=None, titlesearchbydefault=False, check_aliases=True):
    if check_aliases:
        lower = journaltitle.lower()
        try:
            aliases = journal_aliases[lower]
        except KeyError:
            aliases = [journaltitle]
        for alias in aliases:
            ret = crossref_find_from_journalref(
                    alias, volume, number, year, articletitle, titlesearchbydefault,
                    check_aliases=False)
            if ret is not None:
                return ret
        return None

    # Weirdly Crossref search by journal seems to be case sensitive...
    journaltitle = titlecase.titlecase(journaltitle)

    if titlesearchbydefault:
        assert articletitle is not None
        ret = cr.works(filter={'container-title': journaltitle,
                               'from-pub-date': str(int(year)-1),
                               'until-pub-date': year},
                       query_bibliographic=articletitle)
        if len(ret['message']['items']) == 0:
            ret = cr.works(filter={'from-pub-date': str(int(year)-1),
                                   'until-pub-date': year},
                           query_bibliographic=articletitle)
    else:
        ret = cr.works(filter={'article-number': number, 
                               'container-title': journaltitle,
                               'from-pub-date': str(int(year)-1),
                               'until-pub-date': year})
    matches = ret['message']['items']
    matches = [ match for match in matches if 
            (
               (
                   ('issued' in match and match['issued']['date-parts'][0][0] == int(year))
                   or ('published-print' in match and match['published-print']['date-parts'][0][0] == int(year))
               ) and
               ('volume' in match and match['volume'] == volume) and
               ( 
                  ('article-number' in match and match['article-number'] == number) or
                  ('page' in match and match['page'].split('-')[0] == number.replace(' ','').split('-')[0])
               ) and
               (
                   ('container-title' in match and match['container-title'][0] == journaltitle) or
                   ('short-container-title' in match and match['short-container-title'][0] == journaltitle)
               )
            )
            ]

    if len(matches) > 1:
        raise RuntimeError("More than one match for journal ref.")
    elif len(matches) == 0:
        if articletitle is not None and not titlesearchbydefault:
            return crossref_find_from_journalref(journaltitle, volume, number, year, articletitle,
                    titlesearchbydefault=True,
                    check_aliases=check_aliases)
        else:
            return None
    else:
        match = matches[0]
        return matches[0]

def arxiv_find(doi, title=None, searchbytitlefirst=False):
    if searchbytitlefirst:
        matches = arxiv.Search(query=title, max_results=10).results()
    else:
        matches = arxiv.Search(query=doi, max_results=10).results()

    matches = [ match for match in matches if match.doi is not None and match.doi.lower() == doi.lower() ]
    if len(matches) == 0:
        if title is not None and not searchbytitlefirst:
            return arxiv_find(doi, title, True)
        else:
            return None
    elif len(matches) > 1:
        if doi is not None:
            raise RuntimeError("More than one arXiv match for DOI: " + doi)

    match = matches[0]

    re_m = re.search('http://arxiv.org/abs/(.+?)v[0-9]*', match['id'])
    if re_m is None:
        raise RuntimeError("arXiv ID not properly formatted:" + match['id'])
    return re_m.group(1)

def crossref_read(dois):
    chunk_size = 1
    if len(dois) <= chunk_size:
        results = cr.works(ids=dois)
        if len(dois) == 1:
            results = [ results ]
        return results
    else:
        results = []
        it = range(0,len(dois),chunk_size)

        if len(dois) > 5:
            print("Retrieving Crossref data (might take a while)...", file=sys.stderr)
            it = progressbar.progressbar(it)

        for i in it:
            results += crossref_read(dois[i:(i+chunk_size)])
            time.sleep(0.1)
        return results

def aps_read(dois):
    if len(dois) == 0:
        return []
    elif len(dois) == 1:
        url = "https://dx.doi.org/" + dois[0]
        redirecturl = urllib.request.urlopen(url).geturl()
        exporturl = redirecturl.replace("abstract", "export")
        bibtex = urllib.request.urlopen(exporturl).read()
        bibtex_data = bibtexparser.loads(bibtex).entries[0]
        return [bibtex_data]
    else:
        results = []
        it = range(len(dois))
        if len(dois) > 5:
            print("Retrieving APS data (might take a while)...", file=sys.stderr)
            it = progressbar.progressbar(it)

        for i in it:
            results += aps_read([dois[i]])
            time.sleep(0.1)
        return results

def populate_doi_information(list_of_bibitems):
    bibitems_with_doi = [ b for b in list_of_bibitems if (b.doi is not None and
        not b.doi_populated) ]
    dois = [ b.doi for b in bibitems_with_doi ]
    if len(dois) == 0:
        return

    results = crossref_read(dois)

    for bibitem,result in zip(bibitems_with_doi, results):
        bibitem.read_journal_information(result)

def populate_aps_information(list_of_bibitems):
    bibitems_aps = [ b for b in list_of_bibitems if ((not b.aps_populated) and b.is_aps()) ]
    dois = [ b.doi for b in bibitems_aps ]
    if len(dois) == 0:
        return

    results = aps_read(dois)

    for bibitem,result in zip(bibitems_aps, results):
        bibitem.read_aps_information(result)

def format_author(auth):
    family = auth['family']
    given = auth['given']
    if isallcaps(family + given):
        family,given = (capitalize_first_letter(s.lower()) for s in (family,given))
    return family + ", " + given

def format_authorlist(l):
    if len(l) == 0:
        return ""
    else:
        return ''.join(s + " and " for s in l[0:-1]) + l[-1]

def strip_nonalphabetic(s):
    return ''.join(c for c in s if c.isalpha())

def make_bibtexid_from_arxivid(firstauthorlastname, arxivid):
    if "/" in arxivid:
        # Old style arxiv id.
        yymm = arxivid.split('/')[1][0:4]
    else:
        # New style arxiv id.
        yymm = arxivid.split(".")[0]
        assert len(yymm) == 4

    firstauthorlastname = unidecode.unidecode(strip_nonalphabetic(firstauthorlastname))
    return firstauthorlastname + "_" + yymm

def make_charsubs():
    # Some character substitutions to deal with Unicode characters that LaTeX tends to choke on.
    charsubs = { "\u2009" : " " ,
             "\u2212" : "--",
             "\u00B0" : "$^{\circ}$" }

    # This leaves out the letters which look identical to Roman
    # letters and don't have their own LaTeX codes.
    greek_letter_dict = {
        u'\u0393': 'Gamma',
        u'\u0394': 'Delta',
        u'\u0395': 'Epsilon',
        u'\u0396': 'Zeta',
        u'\u0398': 'Theta',
        u'\u039B': 'Lamda',
        u'\u039E': 'Xi',
        u'\u03A0': 'Pi',
        u'\u03A3': 'Sigma',
        u'\u03A6': 'Phi',
        u'\u03A8': 'Psi',
        u'\u03A9': 'Omega',
        u'\u03B1': 'alpha',
        u'\u03B2': 'beta',
        u'\u03B3': 'gamma',
        u'\u03B4': 'delta',
        u'\u03B5': 'epsilon',
        u'\u03B6': 'zeta',
        u'\u03B7': 'eta',
        u'\u03B8': 'theta',
        u'\u03B9': 'iota',
        u'\u03BA': 'kappa',
        u'\u03BB': 'lambda',
        u'\u03BC': 'mu',
        u'\u03BD': 'nu',
        u'\u03BE': 'xi',
        u'\u03C0': 'pi',
        u'\u03C1': 'rho',
        u'\u03C3': 'sigma',
        u'\u03C4': 'tau',
        u'\u03C5': 'upsilon',
        u'\u03C6': 'phi',
        u'\u03C7': 'chi',
        u'\u03C8': 'psi',
        u'\u03C9': 'omega'
    }

    for c,name in greek_letter_dict.items():
        charsubs[c] = '$' + name + '$'

    return charsubs
charsubs = make_charsubs()

# TODO: There are some cases not covered by this, e.g. \t{oo}
accent_map = {
        '`': '\u0300',
        "'": '\u0301',
        '^': '\u0302',
        '"': '\u0308',
        'H': '\u030b',
        '~': '\u0303',
        'c': '\u0327',
        'k': '\u0328',
        'l': '\u0142',
        '=': '\u0304',
        '.': '\u0307',
        'd': '\u0323',
        'r': '\u030a',
        'c': '\u0306',
        'v': '\u030c',
        'o': '\u00f8'
        }
accent_map_reversed = { v: k for k, v in accent_map.items() }
accent_map['\\'] = '\\'

def _decode_latex_accents_yielder(text):
    i = 0
    while i < len(text):
        if text[i] == '\\':
            if i >= len(text)-2:
                yield text[i]
            else:
                if text[i+1] in accent_map:
                    if i >= len(text)-4 and text[i+2] == '{' and text[i+4] == '}':
                        yield text[i+3]
                        yield accent_map[text[i+1]]
                        i += 4
                    else:
                        # The LaTeX parsing rules seem to be a little different depending on whether the 
                        # accent character is an alphabetic character or not.
                        if not text[i+1].isalpha():
                            yield text[i+2]
                            yield accent_map[text[i+1]]
                            i += 2
                        else:
                            yield text[i]
                else:
                    yield text[i]
        else:
            yield text[i]
        i += 1
def decode_latex_accents(text):
    return unicodedata.normalize('NFC', ''.join(_decode_latex_accents_yielder(text)))

def _encode_latex_accents_yielder(text):
    i = 0
    while i < len(text):
        if i >= len(text)-1 or text[i+1] not in accent_map_reversed:
            yield text[i]
            i += 1
        else:
            yield '\\'
            yield accent_map_reversed[text[i+1]]
            yield '{'
            yield text[i]
            yield '}'
            i += 2

def encode_latex_accents(text):
    text = unicodedata.normalize('NFD', text)
    return ''.join(_encode_latex_accents_yielder(text))

def process_text(text):
    if isinstance(text, str):
        def replace(c):
            if c in charsubs.keys():
                return charsubs[c]
            else:
                return c

        ret = "".join(replace(c) for c in text)
        if args.bibtex_encoding:
            ret = encode_latex_accents(ret)
        return ret
    else:
        return text


def protect_words(title):
    def protect_words_base(title):
        split = re.split("([-\s`'])", title)
        for i in range(len(split)):
            word = split[i]
            if len(word) == 0:
                continue
            nupper = sum(c.isupper() for c in word)
            if (nupper > 1 or 
                    (nupper == 1 and word in protected_words)):
                split[i] = "{" + word + "}"
        return ''.join(split)

    # Don't process equations.
    eqnsplit = title.split('$')
    s = ''
    ineqn = True
    for i in range(len(eqnsplit)):
        ineqn = not ineqn
        if ineqn:
            eqnsplit[i] = '{$' + eqnsplit[i] + '$}'
        else:
            eqnsplit[i] = protect_words_base(eqnsplit[i])
    return ''.join(eqnsplit)

def capitalize_first_letter(s):
    if len(s) == 0:
        return s
    else:
        return s[0].upper() + s[1:]

def unallcapsify(title, protect, firstwordcapitalized):
    split = re.split('([-\s])', title)
    for i in range(len(split)):
        word = split[i]
        if len(word) == 0:
            continue

        if word.upper() in protected_words_uppercase:
            word = protected_words_uppercase[word]
            if i == 0 and firstwordcapitalized:
                word = word[0].upper() + word[1:]
            if protect:
                word = "{" + word + "}"
        else:
            word = word.lower()
            if i == 0 and firstwordcapitalized:
                word = word[0].upper() + word[1:]
        split[i] = word
    return ''.join(split)

def isallcaps(s):
    ret = all(c.isupper() for c in s if c.isalpha())
    return ret

def origcase_heuristic(title):
    words = title.split()
    n = len(words)
    ncapitalized = sum(word[0].isupper() for word in words)
    if ncapitalized / n > 0.5:
        return False
    else:
        return True

class ValueUnknownException(Exception):
    pass

def crossref_title_to_latex(s):
    out = StringIO()
    root = etree.fromstring("<root>" + s + "</root>")
    for x in root.iter():
        if x.text is not None:
            text = x.text
        else:
            text = ''

        if x.tag in ('i','b','root'):
            out.write(text)
        elif x.tag == 'sub':
            out.write(r'\textsubscript{' + text + '}')
        elif x.tag == 'sup':
            out.write(r'\textsuperscript{' + text + '}')
        else:
            out.write(r'\textsuperscript{' + text + '}')
            print("WARNING: Unsupported markup in title: <" + x.tag + ">", file=sys.stderr)
        if x.tail is not None:
            out.write(x.tail)

    return out.getvalue()

def default_fn_for_json_encoding(obj):
    if isinstance(obj, LatexTitle):
        return {'titletype': 'latex', 'title': obj.title}
    elif isinstance(obj, CrossrefTitle):
        return {'titletype': 'crossref', 'title': obj.title}
    else:
        return obj

def object_hook_for_json_decoding(d):
    if 'titletype' in d:
        if d['titletype'] == 'latex':
            return LatexTitle(d['title'])
        elif d['titletype'] == 'crossref':
            return CrossrefTitle(d['title'])
        else:
            raise NotImplementedError
    else:
        return d

class LatexTitle(object):
    def __init__(self, title):
        self.title = title

    def to_latex(self):
        return self.title

class CrossrefTitle(object):
    def __init__(self, title):
        self.title = title

    def to_latex(self):
        return crossref_title_to_latex(self.title)

class BibItem(object):
    cache = {}
    badjournals = []

    def __init__(self, arxivid=None, doi=None):
        if arxivid is None and doi is None:
            raise ValueError("Need to specify either arXiv ID or DOI!")

        if arxivid is not None:
            self.canonical_id = 'arXiv:' + arxivid
        else:
            self.canonical_id = 'doi:' + doi

        self.arxivid = arxivid
        self.doi = doi
        self.journal = None
        self.detailed_authors = None
        self.bibtex_id = None
        self.abstract = None
        self.comment = None
        self.publisher = None
        self.title = []

        self.arxiv_populated = False
        self.doi_populated = False
        self.aps_populated = False

    def load_bad_journals():
        thisfile = inspect.getfile(inspect.currentframe())
        filename = os.path.join(os.path.dirname(thisfile), "badjournals.txt")
        with open(filename, "r") as f:
            return [ line.rstrip("\n") for line in f ]

    def __getattr__(self, name):
        if name == 'aps_populated':
            return False
        else:
            raise AttributeError(name)

    @staticmethod
    def load_cache(filename):
        try:
            with open(filename, 'rb') as f:
                def init_from_dict(d):
                    obj = BibItem.__new__(BibItem)
                    obj.__dict__ = d
                    return obj

                BibItem.cache = dict( (k, init_from_dict(obj)) for k,obj in 
                        json.load(f, object_hook=object_hook_for_json_decoding).items())
        except FileNotFoundError:
            print("Warning: cache file not found.", file=sys.stderr)

    @staticmethod
    def save_cache(filename):
        with open(filename, 'w') as f:
            json.dump(dict( (k,i.__dict__) for k,i in BibItem.cache.items()),
                    f, indent=2, default=default_fn_for_json_encoding)

    def is_fresh(self):
        global args
        try:
            if self.is_aps() and not self.aps_populated:
                return False
            if args.refresh_eprints and not self.doi_populated:
                return False
            else:
                return True
        except ValueUnknownException:
            return False

    @staticmethod
    def init_from_input_file_line(line):
        if line in BibItem.cache:
            cached = BibItem.cache[line]
            if cached.is_fresh():
                return cached

        splitline = re.split(r'(?<!\\)\[|(?<!\\)\]', line)
        main = splitline[0]
        doi = None
        arxivid = None
        main = main.strip()

        if main[0:4] == 'doi:':
            doi = main[4:]
        else:
            arxivid = main

        bibtex_id = None
        suppress_volumewarning = False

        comment = None
        extra_bibtex_fields = {}
        if len(splitline) > 1:
            opts = splitline[1]
            for opt in opts.split(","):
                opt = opt.strip()
                opt_split = opt.split(':')
                key = opt_split[0]
                value = opt_split[1]

                if key == 'doi':
                    if doi is not None:
                        raise RuntimeError("Specified DOI twice.")
                    else:
                        doi = value
                elif key == 'bibtex_id':
                    bibtex_id = value
                elif key == 'suppress_volumewarning':
                    if value == 'yes':
                        suppress_volumewarning = True
                    elif value == 'no':
                        pass
                    else:
                        raise RuntimeError("Invalid value: '" + value + "'")
                elif key == 'comment':
                    comment = unescape_string(value)
                elif key in optional_bibtex_fields:
                    extra_bibtex_fields[key] = unescape_string(value)
                else:
                    raise RuntimeError("Invalid option name: '" + key + "'")

        bibitem = BibItem(arxivid, doi)
        bibitem.bibtex_id = bibtex_id
        bibitem.suppress_volumewarning = suppress_volumewarning
        bibitem.comment = comment
        bibitem.extra_bibtex_fields = extra_bibtex_fields

        BibItem.cache[line] = bibitem
        return bibitem

    # def is_aps(self):
    #     try:
    #         if self.publisher is None:
    #             return False
    #         else:
    #             return self.publisher == "American Physical Society (APS)"
    #     except AttributeError:
    #          raise ValueUnknownException()

    def is_aps(self):
        # APS has started blocking bots from accessing its data, so we have to fall back to
        # CrossRef for all papers.
        return False

    def generate_bibtexid(self):
        if self.bibtex_id is not None:
            return self.bibtex_id
        elif self.arxivid is None:
            raise ValueError("For papers not referenced by arXiv ID, you have to" +
                              "manually specify a BibTeX ID.")
        else:
            return make_bibtexid_from_arxivid(self.first_author_lastname(), self.arxivid)

    def first_author_lastname(self):
        if self.detailed_authors is not None:
            return self.detailed_authors[0]['family']
        else:
            return self.authors[0].split(' ')[-1]

    def __eq__(a,b):
        return a.canonical_id == b.canonical_id

    def __ne__(a,b):
        return not (a == b)

    def __hash__(self):
        return hash(self.canonical_id)

    def output_bib(self, eprint_published):
        global args

        if self.bibtex_id is not None:
            bibtex_id = self.bibtex_id
        else:
            bibtex_id = self.generate_bibtexid()

        try:
            if self.comment is not None:
                print(self.comment)
        except AttributeError:
            pass

        def printfield(field,value, lastone=False):
            print("  " + field + "={" + bibtex_escape(value) + "}" +
                    ("" if lastone else ","))

        
        if self.journal is not None:
            bibtex_type="article"
        else:
            bibtex_type="unpublished"

        print("@" + bibtex_type + "{" + self.generate_bibtexid() + ",")
        if self.abstract is not None:
            printfield("abstract", self.abstract)
        if self.arxivid is not None and (self.doi is None or eprint_published):
            printfield("archiveprefix", "arXiv")
            printfield("eprint", self.arxivid)
        if self.arxivid is not None and self.doi is None and args.eprint_as_note:
            printfield("note", "arXiv eprint " + self.arxivid)
        if self.journal is not None:
            abbrevname = journal_abbreviations.get(self.journal)
            if abbrevname is None:
                abbrevname = self.journal
            printfield("journal", abbrevname)
            printfield("pages", self.page)
            printfield("year", str(self.year))

            # Sometimes papers don't come with volume numbers for some reason...
            if self.volume is not None:
                printfield("volume", self.volume)
            elif not self.suppress_volumewarning:
                print("WARNING: No volume in CrossRef data for paper:", file=sys.stderr)
                print("   " + str(self.title), file=sys.stderr)
        if self.doi is not None:
            printfield("doi", self.doi)

        # Compatibility for old cache files
        if isinstance(self.title, str):
            title = self.title
        else:
            title = self.title[-1].to_latex()

        allcaps = isallcaps(title)
        if allcaps:
            title = unallcapsify(title, protect=True, firstwordcapitalized=True)
        else:
            origcase = origcase_heuristic(title)
            if origcase:
                title = "{" + title + "}"
            else:
                title = protect_words(title)
        print("  title={" + title + "},")

        if not args.suppress_optional_fields:
            try:
                extra_bibtex_fields = self.extra_bibtex_fields
            except AttributeError:
                extra_bibtex_fields = {}
            for key,value in extra_bibtex_fields.items():
                printfield(key, value)

        printfield("author", format_authorlist(self.authors), lastone=True)
        print("}")
        print("")

    def read_arxiv_information(self,arxivresult):
        self.authors = [ str(author) for author in arxivresult.authors ]
        self.title.append(LatexTitle(arxivresult.title))
        self.abstract = arxivresult.summary

        if self.doi is not None and arxivresult.doi is not None and self.doi != arxivresult.doi:
            print("WARNING: manually specified DOI for arXiv:" + self.arxivid + " disagrees with arXiv information.", file=sys.stderr)
            print("You have: ", file=sys.stderr)
            print("arXiv has: " + arxivresult.doi, file=sys.stderr)
            print("Using your DOI.", file=sys.stderr)
            print(file=sys.stderr)
        elif arxivresult.doi is not None:
            self.doi = arxivresult.doi

        self.arxiv_populated = True

    def read_aps_information(self, apsresult):
        # The Crossref information for APS journals has broken title field for titles
        # that contain an equation. On the other hand the APS website lets you export a
        # BibTeX entry for all their papers which does have the correct the information.
        # So we use that instead.
        
        aps_title = apsresult['title']
        if '$' in aps_title:
            self.title.append(LatexTitle(aps_title))
        else:
            # The Crossref title should be fine as long as the APS title
            # didn't contain any equations.
            pass

        self.aps_populated = True

    def bad_journal_exit(self, journalname):
        print("The following journal is known to have improper Crossref data:", file=sys.stderr)
        print("    " + journalname, file=sys.stderr)
        print("You will need to add papers from this journal to your BibTeX file manually.", file=sys.stderr)
        print("Exiting with error.", file=sys.stderr)
        sys.exit(1)

    def bad_type_exit(self, crossref_type):
        print("The Crossref entry with DOI:", file=sys.stderr)
        print("    " + self.doi, file=sys.stderr)
        if self.arxivid is not None:
            print("linked to arXiv ID:", file=sys.stderr)
            print("    " + self.arxivid, file=sys.stderr)
        print("has type:", file=sys.stderr)
        print("    " + crossref_type, file=sys.stderr)
        print("Currently, only type 'journal-article' is supported.", file=sys.stderr)
        print("You will need to add this entry to your BibTeX file manually.", file=sys.stderr)
        print("Exiting with error.", file=sys.stderr)
        sys.exit(1)

    def read_journal_information(self,cr_result):
        try:
            cr_result = cr_result['message']
            crossref_type = cr_result['type']
            if crossref_type != "journal-article":
                self.bad_type_exit(crossref_type)

            self.journal = html.unescape(cr_result['container-title'][0])
            if self.journal in BibItem.badjournals:
                self.bad_journal_exit(self.journal)
            try:
                self.journal_short = cr_result['short-container-title'][0]
            except IndexError:
                self.journal_short = self.journal
            self.detailed_authors = cr_result['author']
            self.authors = [ format_author(auth) for auth in self.detailed_authors ]
            self.publisher = cr_result['publisher']
            self.year = cr_result['issued']['date-parts'][0][0]
            self.title.append(CrossrefTitle(cr_result['title'][0]))

            try:
                self.volume = cr_result['volume']
            except KeyError:
                self.volume = None

            try:
                self.page = cr_result['article-number']
            except KeyError:
                self.page = cr_result['page'].split('-')[0]

            self.doi_populated = True
        except KeyError:
            print(cr_result)
            raise
BibItem.badjournals = BibItem.load_bad_journals()

class OpenFileWithPath:
    @staticmethod
    def open(path, *args, **kwargs):
        return OpenFileWithPath(path, open(path, *args, **kwargs))

    def __init__(self, path, f):
        self.f = f
        self.path = path

    def close_and_delete(self):
        self.f.close()
        os.remove(self.path)

    def __getattr__(self, attr):
        return getattr(self.f, attr)

def main():
    global print
    global args
    global print_

    parser = argparse.ArgumentParser(prog='imbibe')
    parser.add_argument("--no-eprint-published", action='store_false',
            dest='eprint_published',
            help="For published papers, don't include the arXiv ID in the BibTeX file.")
    parser.add_argument("--refresh-eprints", action='store_true',
            dest='refresh_eprints',
            help="Ignore cache for entries where the cached entry has no publication information.")
    parser.add_argument("--eprint-as-note", action='store_true',
            dest='eprint_as_note',
            help="For entries that have no published journal information, put arXiv information in the note field.")
    parser.add_argument("--print-keys", action='store_true',
            dest='print_keys',
            help="Instead of outputting BibTeX entries, just output the BibTeX IDs, separated by commas.")
    parser.add_argument("--print-eprints", action='store_true',
            dest='print_eprints',
            help="Instead of outputting BibTeX entries, just output the arXiv IDs of papers that have no published version.")
    parser.add_argument("--suppress-optional-fields", action='store_true',
            dest='suppress_optional_fields',
            help="Don't output optional BibTeX fields such as 'comment' or 'addendum'")
    parser.add_argument("--bibtex-encoding", action='store_true',
            dest='bibtex_encoding',
            help="Where possible, convert accented characters to a LaTeX escaped character.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--arxiv")
    group.add_argument("--doi")
    group.add_argument("inputfile", nargs='?')
    parser.add_argument("outputfile", nargs='?')
    args = parser.parse_args()

    use_cache=False
    fout=None
    try:
        if args.arxiv is not None:
            bibitems = [ BibItem(arxivid=args.arxiv) ]
        elif args.doi is not None:
            bibitems = [ BibItem(doi=args.doi) ]
            bibitems[0].bibtex_id = 'ARTICLE'
        else:
            use_cache = True
            cache_filename = "imbibe-cache.json"
            BibItem.load_cache(cache_filename)

            if args.outputfile is not None:
                outputfilename = args.outputfile
                fout = OpenFileWithPath.open(outputfilename, 'w', encoding='utf-8')
            else:
                fout = sys.stdout
            print_ = print
            def myprint(*args, file=fout, **kwargs):
                print_(*(process_text(arg) for arg in args), file=file, **kwargs)
            print = myprint

            f = open(args.inputfile)
            bibitems = [ BibItem.init_from_input_file_line(line) for line in f.readlines() 
                    if line.strip() != '' ]

            if not args.print_keys:
                if 'IMBIBE_MSG' in os.environ:
                    msg = os.environ['IMBIBE_MSG']
                else:
                    msg = "File automatically generated by imbibe. DO NOT EDIT."
                print(msg)
                print()

        populate_arxiv_information(bibitems)
        populate_doi_information(bibitems)
        populate_aps_information(bibitems)

        if args.print_eprints:
            for bibitem in bibitems:
                if bibitem.doi is None:
                    print(bibitem.arxivid)
        elif args.print_keys:
            for bibitem in bibitems:
                print(bibitem.generate_bibtexid(), end=", ")
            print()
        else:
            for bibitem in bibitems:
                bibitem.output_bib(args.eprint_published)

        if use_cache:
            BibItem.save_cache(cache_filename)
    except:
        if fout is not None and isinstance(fout, OpenFileWithPath):
            fout.close_and_delete()
        raise
