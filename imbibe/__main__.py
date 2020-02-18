import arxiv
import sys
import habanero
import re
import pickle
import os

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


def populate_doi_information(list_of_bibitems):
    bibitems_with_doi = [ b for b in list_of_bibitems if (b.doi is not None and
        not b.doi_populated) ]
    dois = [ b.doi for b in bibitems_with_doi ]
    if len(dois) == 0:
        return

    cr = habanero.Crossref()
    results = cr.works(ids=dois)

    if len(dois) == 1:
        results = [ results ]

    for bibitem,result in zip(bibitems_with_doi, results):
        bibitem.read_journal_information(result)

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

    firstauthorlastname = strip_nonalphabetic(firstauthorlastname)
    return firstauthorlastname + "_" + yymm

class BibItem(object):
    cache = {}

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

        self.arxiv_populated = False
        self.doi_populated = False

    @staticmethod
    def load_cache(filename):
        try:
            with open(filename, 'rb') as f:
                BibItem.cache = pickle.load(f)
        except FileNotFoundError:
            print("Warning: cache file not found.", file=sys.stderr)

    @staticmethod
    def save_cache(filename):
        with open(filename, 'wb') as f:
            pickle.dump(BibItem.cache, f)

    @staticmethod
    def init_from_input_file_line(line):
        if line in BibItem.cache:
            return BibItem.cache[line]

        splitline = re.split('\[|\]', line)
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
                    comment = value
                else:
                    raise RuntimeError("Invalid option name: '" + key + "'")

        bibitem = BibItem(arxivid, doi)
        bibitem.bibtex_id = bibtex_id
        bibitem.suppress_volumewarning = suppress_volumewarning
        bibitem.comment = comment

        BibItem.cache[line] = bibitem
        return bibitem

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

    def output_bib(self):
        if self.bibtex_id is not None:
            bibtex_id = self.bibtex_id
        else:
            bibtex_id = self.generate_bibtexid()


        if self.comment is not None:
            print(self.comment)

        print("@article{" + self.generate_bibtexid() + ",")
        if self.abstract is not None:
            print("  abstract={" + self.abstract + "},")
        if self.arxivid is not None:
            print("  archiveprefix={arXiv},")
            print("  eprint={" + self.arxivid + "},")
        if self.journal is not None:
            print("  journal={" + self.journal_short + "},")
            print("  pages={" + self.page + "},")
            print("  year={" + str(self.year) + "},")

            # Sometimes papers don't come with volume numbers for some reason...
            if self.volume is not None:
                print("  volume={" + self.volume + "},")
            elif not self.suppress_volumewarning:
                print("WARNING: No volume in CrossRef data for paper:", file=sys.stderr)
                print("   " + self.title, file=sys.stderr)
        if self.doi is not None:
            print("  doi={" + self.doi + "},")
        print("  title={" + self.title + "},")
        print("  author={" + format_authorlist(self.authors) + "}")
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

    def read_journal_information(self,cr_result):
        try:
            cr_result = cr_result['message']
            self.detailed_authors = cr_result['author']
            self.authors = [ format_author(auth) for auth in self.detailed_authors ]
            self.journal = cr_result['container-title'][0]
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

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] == '--help':
        print("imbibe <input_file>", file=sys.stderr)
        print("imbibe --arxiv <arxiv_id>", file=sys.stderr)
        print("imbibe --doi <doi>", file=sys.stderr)
    else:
        arg = sys.argv[1]

        cache_filename = "imbibe-cache.pkl"

        BibItem.load_cache(cache_filename)

        if arg == '--arxiv':
            bibitems = [ BibItem(arxivid=sys.argv[2]) ]
        elif arg == '--doi':
            bibitems = [ BibItem(doi=sys.argv[2]) ]
        else:
            f = open(arg)
            bibitems = [ BibItem.init_from_input_file_line(line) for line in f.readlines() 
                    if line.strip() != '' ]

            if 'IMBIBE_MSG' in os.environ:
                msg = os.environ['IMBIBE_MSG']
            else:
                msg = "File automatically generated by imbibe. DO NOT EDIT."
            print(msg)
            print()

        populate_arxiv_information(bibitems)
        populate_doi_information(bibitems)
        for bibitem in bibitems:
            bibitem.output_bib()

        BibItem.save_cache(cache_filename)
