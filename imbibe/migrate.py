import sys
import bibtexparser
from bibtexparser.bparser import BibTexParser
from habanero import crossref
import arxiv
import re

cr = crossref.Crossref()

parser = BibTexParser(common_strings=True)

with open(sys.argv[1]) as bibtex_file:
    bib_database = bibtexparser.load(bibtex_file)

def check_arxiv_id(arxiv_id, bibentry):
    result = arxiv.query(id_list=[arxiv_id])[0]
    if 'title' in bibentry and bibentry['title'].lower() != result['title'].lower():
        raise RuntimeError("Problem (arxiv):" + " " + entry['title'] + " " + result['title'])
    else:
        print(arxiv_id)

for entry in bib_database.entries[3:]:
    journal = entry['journal']
    match = re.search('arXiv:([0-9a-z\-.]+)', journal)
    if match is not None:
        arxiv_id = match.group(1)
        check_arxiv_id(arxiv_id, entry)
    else:
        try:
            query_string = entry['journal'] + " " + entry['volume'] + ", " + entry['pages']
        except KeyError:
            print(journal)
            print("No key:", entry['title'])
            raise KeyError()

        works = cr.works(query_bibliographic=query_string, limit=1)
        result = works['message']['items'][0]

        if 'title' not in entry:
            try:
                page = result['article-number']
            except KeyError:
                page = result['page'].split('-')[0]
            if (result['volume'].lower() != entry['volume'].lower() or
                    page != re.split('--|-', entry['pages'])):
                raise RuntimeError("Problem! volume or page:" + entry['title'])
        else:
            if not 'title' in result:
                print("WARNING: Could not find title for Crossref entry. " + entry['title'])
            elif result['title'][0].lower() != entry['title'].lower():
                raise RuntimeError("Problem!" + " " + entry['title'] + " " + result['title'][0])
            print(result['DOI'])
