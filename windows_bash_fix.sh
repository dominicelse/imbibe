# This shell script creates an "imbibe" shell script in the bin/ directory that
# calls the "imbibe.bat" batch file. This prevents you from having to type
# "imbibe.bat" when running Bash on Windows.

echo "$PWD/bin/imbibe.bat" '"$@"' >bin/imbibe
chmod u+x bin/imbibe
