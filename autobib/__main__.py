import arxiv
import sys
import habanero
import re

def populate_arxiv_information(list_of_bibitems):
    bibitems_with_arxivid = [ b for b in list_of_bibitems if b.arxivid is not None ]
    arxiv_ids = [ b.arxivid for b in bibitems_with_arxivid ]

    try:
        results = arxiv.query(id_list=arxiv_ids)
    except Exception as e:
        if e.args[0] != 'HTTP Error 400 in query':
            raise e

        # Need to try all the arXiv IDs individually to find out which one was
        # not found.
        results = [ None ] * len(arxiv_ids)
        for i in xrange(len(results)):
            try:
                results[i] = arxiv.query(id_list=arxiv_ids[i])[0]
            except Exception as ee:
                print("arXiv ID not found (or other error): " + arxiv_ids[i], file=sys.stderr)
                raise ee

    if len(results) != len(arxiv_ids):
        raise RuntimeError("arXiv returned wrong number of papers.")

    for bibitem,result in zip(bibitems_with_arxivid, results):
        bibitem.read_arxiv_information(result)


def populate_doi_information(list_of_bibitems):
    bibitems_with_doi = [ b for b in list_of_bibitems if b.doi is not None ]
    dois = [ b.doi for b in bibitems_with_doi ]

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

def make_bibtexid_from_arxivid(firstauthorlastname, arxivid):
    if "/" in arxivid:
        # Old style arxiv id.
        yymm = arxivid.split('/')[0:4]
    else:
        # New style arxiv id.
        yymm = arxivid.split(".")[0]
        assert len(yymm) == 4
    return firstauthorlastname + "_" + yymm

class BibItem(object):
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

    @staticmethod
    def init_from_input_file_line(line):
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

        bibitem = BibItem(arxivid, doi)
        bibitem.bibtex_id = bibtex_id

        return bibitem

    def generate_bibtexid(self):
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
        print("@article{" + self.generate_bibtexid() + ",")
        if self.journal is not None:
            print("  journal={" + self.journal_short + "},")
            print("  volume={" + self.volume + "},")
            print("  pages={" + self.page + "},")
            print("  year={" + str(self.year) + "},")
        print("  title={" + self.title + "},")
        print("  author={" + format_authorlist(self.authors) + "},")
        print("  abstract={" + self.abstract + "},")
        print("  archiveprefix={arXiv},")
        print("  eprint={" + self.arxivid + "}")
        print("}")

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

    def read_journal_information(self,cr_result):
        cr_result = cr_result['message']
        self.detailed_authors = cr_result['author']
        self.authors = [ format_author(auth) for auth in self.detailed_authors ]
        self.journal_short = cr_result['short-container-title'][0]
        self.journal = cr_result['container-title'][0]
        self.year = cr_result['created']['date-parts'][0][0]
        self.volume = cr_result['volume']
        self.page = cr_result['article-number']

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] == '--help':
        print("autobib <input_file>", file=sys.stderr)
        print("autobib --arxiv <arxiv_id>", file=sys.stderr)
        print("autobib --doi <doi>", file=sys.stderr)
    else:
        arg = sys.argv[1]
        if arg == '--arxiv':
            bibitems = [ BibItem(arxivid=sys.argv[2]) ]
        elif arg == '--doi':
            bibitems = [ BibItem(doi=sys.argv[2]) ]
        else:
            f = open(arg)
            bibitems = [ BibItem.init_from_input_file_line(line) for line in f.readlines() ]

        populate_arxiv_information(bibitems)
        populate_doi_information(bibitems)
        for bibitem in bibitems:
            bibitem.output_bib()
