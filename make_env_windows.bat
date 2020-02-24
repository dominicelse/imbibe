@echo off

echo Setting up environment...

SET errhnd=^|^| ^(PAUSE ^&^& EXIT /B 1^)

py -3 --version >nul %errhnd%
mkdir imbibe_env %errhnd%
py -3 -m venv imbibe_env %errhnd%
call imbibe_env\Scripts\activate.bat %errhnd%
pip3 install wheel
pip3 install arxiv habanero unidecode %errhnd%
xcopy imbibe imbibe_env\Lib\site-packages\imbibe\ %errhnd%

echo ^@echo off >bin\imbibe.bat %errhnd%
echo setlocal >>bin\imbibe.bat %errhnd%
echo set PYTHONIOENCODING=UTF-8 >>bin\imbibe.bat %errhnd%
echo "%CD%\imbibe_env\Scripts\python" -m imbibe %%^* >>bin\imbibe.bat %errhnd%

echo call "%CD%\bin\imbibe" refs.txt ^>ref-autobib.bib %%^* ^|^| ^(pause ^&^& exit /b 1) >imbibehere.bat %errhnd%
echo echo Imbibe ran successfully. >>imbibehere.bat %errhnd%
echo pause >>imbibehere.bat %errhnd%

echo Done setting up environment!
pause
