import arxiv
import sys
import itertools

def populate_arxiv_information(list_of_bibitems):

    by_arxivid = dict( (b.arxivid, b) for b in set_of_bibitems if b.arxivid is not None )
    arxiv_ids = list(by_arxivid.keys())

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
            except Exception as ee
                print >>sys.stderr, "arXiv ID not found (or other error): " + arxiv_ids[i]
                raise ee

    if len(results) != len(arxiv_ids):
        raise RuntimeError, "arXiv returned wrong number of papers."

    for arxiv_id,result in itertools.izip(arxiv_ids, results):
        by_arxivid[arxiv_id].populate_arxiv_information(result)

def populate_doi_information(set_of_bibitems):
    dois = [ b.doi for b in set_of_bibitems if b.doi is not None ]

class BibItem(object):
    def __init__(self, arxivid=None, doi=None):
        if arxivid is None and doi is None:
            raise ValueError, "Need to specify either arXiv ID or DOI!"

        if arxivid is not None:
            self.canonical_id = 'arXiv:' + arxivid
        else:
            self.canonical_id = 'doi:' + doi

        self.arxivid = arxivid
        self.doi = doi

    def __eq__(a,b):
        return a.canonical_id = b.canonical_id

    def __ne__(a,b):
        return not (a == b)

    def __hash__(self):
        return hash(self.canonical_id)

    def populate_arxiv_information(arxivresult):
        self.authors = arxivresult['authors']
        self.title = arxivresult['title']
        self.abstract = arxivresult['abstract']

        if self.doi is not None and arxivresult['doi'] is not None and self.doi != arxivresult['doi']:
            print >>sys.stderr, "WARNING: manually specified DOI for arXiv:" + self.arxivid + " disagrees with arXiv information."
            print >>sys.stderr, "You have: " + self.doi
            print >>sys.stderr, "arXiv has: " + arxivresult['doi']
            print >>sys.stderr, "Using your DOI."
            print >>sys.stderr
        elif arxivresult['doi'] is not None:
            self.doi = arxivresult['doi']
