import imbibe
import bibtexparser
import sys
import time
import re

def errprint(*s):
    return print(*s, file=sys.stderr)

def process_entry(entry):
    if entry['ENTRYTYPE'] != 'article':
        return None
    elif 'imbibeable' in entry and entry['imbibeable'] == 'no':
        return None

    if 'journal' in entry:
        journal = entry['journal']
        re_m = re.search('arXiv preprint arXiv:(.+)', entry['journal'])
        if re_m is not None:
            return re_m.group(1)

    fieldtranslations = {
            'journal': 'journaltitle',
            'volume': 'volume',
            'pages': 'number',
            'year': 'year'
            }
    try:
        kwargs = dict( (b, entry[a]) for (a,b) in fieldtranslations.items())
    except KeyError:
        # Not enough information to look up journal reference.
        return None
    if 'title' in entry:
        kwargs['articletitle'] = entry['title']
        title = entry['title']
    else:
        title = None

    errprint(entry['ID'])

    match = imbibe.crossref_find_from_journalref(**kwargs)
    time.sleep(1)

    if match is None:
        print("WARNING: lookup for article with bibtex ID " + entry['ID'] + " failed.",
              file=sys.stderr)
        return None
    elif 'title' in entry and not imbibe.titles_equal(match['title'][0], entry['title']):
        errprint("WARNING: titles did not agree for article with bibtex ID " + entry['ID'])
        errprint("Bibtex entry has title:" + entry['title'])
        errprint("Crossref has title:" + match['title'][0])

    doi = match['DOI']
    arxivid = imbibe.arxiv_find(doi, title)
    if arxivid is None:
        if int(entry['year']) >= 1991 and not ('has_eprint' in entry and entry['has_eprint'] == 'no'):
            errprint("WARNING: No arXiv ID found for DOI: " + doi)
        id_ = 'doi:' + doi
    else:
        id_ = arxivid

    return id_ + ' [bibtex_id:' + entry['ID'] + ']'

def process(bibdatabase):
    lines = []
    def process_entry_(entry):
        line = process_entry(entry)
        if line is None:
            return entry
        else:
            lines.append(line)
            return None

    bibdatabase.entries = [ process_entry_(entry) for entry in bibdatabase.entries ]
    bibdatabase.entries = [ entry for entry in bibdatabase.entries if entry is not None ]

    for line in lines:
        print(line)

if __name__ == '__main__':
    if sys.argv[1] == '--delete':
        delete = True
        filename = sys.argv[2]
    else:
        delete = False
        filename = sys.argv[1]

    with open(filename, 'r') as f:
        bibdatabase = bibtexparser.load(f)

    process(bibdatabase)

    if delete:
        with open(filename, 'w') as f:
            bibtexparser.dump(bibdatabase, f)
