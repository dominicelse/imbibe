import subprocess
import urllib.request
import zipfile
import shutil
import sys
import os

try:
    subprocess.run(["git", "submodule", "init"])
    subprocess.run(["git", "submodule", "update"])
except FileNotFoundError:
    print("Warning: No git executable found in PATH. Falling back to downloading", file=sys.stderr)
    print("from github directly.", file=sys.stderr)

    url = "https://github.com/JabRef/abbrv.jabref.org/archive/master.zip"
    urllib.request.urlretrieve(url, "abbrv.zip")

    try:
        with zipfile.ZipFile("abbrv.zip","r") as abbrv_zip:
            abbrv_zip.extractall()

        shutil.rmtree("abbrv.jabref.org")
        shutil.move("abbrv.jabref.org-master",  "abbrv.jabref.org")
    finally:
        os.remove("abbrv.zip")
