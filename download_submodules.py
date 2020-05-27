import subprocess
import urllib.request
import zipfile

try:
    subprocess.run(["git", "submodule", "init"])
    subprocess.run(["git", "submodule", "update"])
except FileNotFoundError:
    print("Warning: No git executable found in PATH. Falling back to downloading", file=sys.stderr)
    print("from github directly.", file=sys.stderr)

    url = "https://github.com/JabRef/abbrv.jabref.org/archive/master.zip"
    urllib.request.urlretrive(url, "abbrv.zip")

    with zipfile.ZipFile("abbrv.zip","r") as abbrv_zip:
        abbrv_zip.exctractall()
        shutil.rmtree("abbrv.jabref.org")
        shutil.move("abbrv.jabref.org-master",  "abbrv.jabref.org")
