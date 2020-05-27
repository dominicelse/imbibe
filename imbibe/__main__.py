import arxiv
import sys
import habanero
import re
import os
import unidecode
import argparse
import time
import progressbar
import json
import inspect
import urllib.request
import bibtexparser

try:
    from imbibe.opts import optional_bibtex_fields
except ModuleNotFoundError:
    from imbibe.opts_default import optional_bibtex_fields

try:
    with open("capitalized_words.txt", "r") as f:
        protected_words = [ line.rstrip("\n") for line in f ]
except FileNotFoundError:
    protected_words = []

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
    
    thisfile = inspect.getfile(inspect.currentframe())
    thisdir = os.path.dirname(thisfile)
    for filename in import_order:
        with open(os.path.join(thisdir, filename), "r") as f:
            for line in f.readlines():
                line = line.rstrip()
                if ";" in line and line[0] != '#':
                    split = line.split(";")
                    name = split[0]
                    name_abbrev = split[1]

                    abbrev[name] = name_abbrev
    return abbrev
journal_abbreviations = load_journal_abbreviations()

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

def populate_arxiv_information(list_of_bibitems):
    bibitems_with_arxivid = [ b for b in list_of_bibitems if
            (b.arxivid is not None and not b.arxiv_populated) ]
    arxiv_ids = [ b.arxivid for b in bibitems_with_arxivid ]

    if len(arxiv_ids) == 0:
        return

    try:
        results = arxiv.query(id_list=arxiv_ids, max_results=len(arxiv_ids))
    except Exception as e:
        if e.args[0] != 'HTTP Error 400 in query':
            raise e

        # Need to try all the arXiv IDs individually to find out which one was
        # not found.
        results = [ None ] * len(arxiv_ids)
        for i in range(len(results)):
            try:
                results[i] = arxiv.query(id_list=arxiv_ids[i])[0]
            except Exception as ee:
                print("arXiv ID not found (or other error): " + arxiv_ids[i], file=sys.stderr)
                raise ee from None

    if len(results) != len(arxiv_ids):
        raise RuntimeError("arXiv returned wrong number of papers.")

    for bibitem,result in zip(bibitems_with_arxivid, results):
        bibitem.read_arxiv_information(result)

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
    return auth['family'] + ", " + auth['given']

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
             "\u2212" : "--" }

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

def process_text(text):
    if isinstance(text, str):
        def replace(c):
            if c in charsubs.keys():
                return charsubs[c]
            else:
                return c

        return "".join(replace(c) for c in text)
    else:
        return text


def protect_words(title):
    split = re.split('([-\s])', title)
    for i in range(len(split)):
        word = split[i]
        if len(word) == 0:
            continue
        if (sum(c.isupper() for c in word) > 1
                or (word[0].isupper() and word in protected_words)):
            split[i] = "{" + word + "}"
    return ''.join(split)

def origcase_heuristic(title):
    words = title.split()
    n = len(words)
    ncapitalized = sum(word[0].isupper() for word in words)
    if ncapitalized / n > 0.5:
        return False
    else:
        return True

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

        self.arxiv_populated = False
        self.doi_populated = False
        self.aps_populated = False

    def load_bad_journals():
        thisfile = inspect.getfile(inspect.currentframe())
        filename = os.path.join(os.path.dirname(thisfile), "badjournals.txt")
        with open(filename, "r") as f:
            return [ line.rstrip("\n") for line in f ]

    @staticmethod
    def load_cache(filename):
        try:
            with open(filename, 'rb') as f:
                def init_from_dict(d):
                    obj = BibItem.__new__(BibItem)
                    obj.__dict__ = d
                    return obj

                BibItem.cache = dict( (k, init_from_dict(obj)) for k,obj in json.load(f).items())
        except FileNotFoundError:
            print("Warning: cache file not found.", file=sys.stderr)

    @staticmethod
    def save_cache(filename):
        with open(filename, 'w') as f:
            json.dump(dict( (k,i.__dict__) for k,i in BibItem.cache.items()),
                    f, indent=0)

    @staticmethod
    def init_from_input_file_line(line):
        if line in BibItem.cache:
            return BibItem.cache[line]

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

    def is_aps(self):
        try:
            if self.publisher is None:
                return False
            else:
                return self.publisher == "American Physical Society (APS)"
        except AttributeError:
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

        print("@article{" + self.generate_bibtexid() + ",")
        if self.abstract is not None:
            printfield("abstract", self.abstract)
        if self.arxivid is not None and (self.doi is None or eprint_published):
            printfield("archiveprefix", "arXiv")
            printfield("eprint", self.arxivid)
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
                print("   " + self.title, file=sys.stderr)
        if self.doi is not None:
            printfield("doi", self.doi)

        origcase = origcase_heuristic(self.title)
        title = bibtex_escape(self.title)
        if origcase:
            print("  title={{" + title + "}},")
        else:
            print("  title={" + protect_words(title) + "},")

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
        self.authors = arxivresult['authors']
        self.title = arxivresult['title']
        self.abstract = arxivresult['summary']

        if self.doi is not None and arxivresult['doi'] is not None and self.doi != arxivresult['doi']:
            print("WARNING: manually specified DOI for arXiv:" + self.arxivid + " disagrees with arXiv information.", file=sys.stderr)
            print("You have: ", file=sys.stderr)
            print("arXiv has: " + arxivresult['doi'], file=sys.stderr)
            print("Using your DOI.", file=sys.stderr)
            print(file=sys.stderr)
        elif arxivresult['doi'] is not None:
            self.doi = arxivresult['doi']

        self.arxiv_populated = True

    def read_aps_information(self, apsresult):
        # The Crossref information for APS journals has broken title field for titles
        # that contain an equation. On the other hand the APS website lets you export a
        # BibTeX entry for all their papers which does have the correct the information.
        # So we use that instead.
        self.title = apsresult['title']

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
            self.detailed_authors = cr_result['author']
            self.authors = [ format_author(auth) for auth in self.detailed_authors ]
            self.journal = cr_result['container-title'][0]
            self.publisher = cr_result['publisher']
            if self.journal in BibItem.badjournals:
                self.bad_journal_exit(self.journal)
            try:
                self.journal_short = cr_result['short-container-title'][0]
            except IndexError:
                self.journal_short = self.journal
            self.year = cr_result['issued']['date-parts'][0][0]
            self.title = cr_result['title'][0]

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

if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog='imbibe')
    parser.add_argument("--no-eprint-published", action='store_false',
            dest='eprint_published',
            help="For published papers, don't include the arXiv ID in the BibTeX file.")
    parser.add_argument("--print-keys", action='store_true',
            dest='print_keys',
            help="Instead of outputting BibTeX entries, just output the BibTeX IDs, separated by commas.")
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

        if args.print_keys:
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
