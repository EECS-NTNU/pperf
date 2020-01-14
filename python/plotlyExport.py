#!/usr/bin/env python

# To export to any other format than html, you need a special orca version from plotly
# https://github.com/plotly/orca/releases
import os
import shutil
import subprocess
import tempfile
orcaBin = None
openWith = None


def openFile(fileName, defaultApp=None):
    if defaultApp is None:
        for app in ['xdg-open', 'open', 'start']:
            if shutil.which(app) is not None:
                defaultApp = app
                break
    if defaultApp is None:
        raise Exception('Could not find default application launcher!')
    try:
        subprocess.check_call([defaultApp, fileName], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    except Exception:
        raise Exception(f'Could not open {fileName}!')


def determineOrca():
    global orcaBin
    if orcaBin is not None:
        orcaBin = shutil.which(orcaBin)
    else:
        orcaBin = os.getenv('PLOTLY_ORCA')

    if orcaBin is None:
        for executable in ['/opt/plotly-orca/orca', '/opt/plotly/orca', '/opt/orca/orca', '/usr/bin/orca', 'orca']:
            orcaBin = shutil.which(executable)
            if orcaBin is not None:
                break

    if orcaBin is None:
        raise Exception('Could not find orca!')


def exportFigure(fig, width, height, exportFile, autoOpen=False):
    if exportFile.endswith('.html'):
        import plotly
        plotly.offline.plot(fig, filename=exportFile, auto_open=autoOpen)
        return
    else:
        import plotly.graph_objects as go
        global orcaBin
        if orcaBin is None:
            determineOrca()

        tmpFd, tmpFile = tempfile.mkstemp()
        try:
            exportFile = os.path.abspath(exportFile)
            exportDir = os.path.dirname(exportFile)
            exportFilename = os.path.basename(exportFile)
            _, fileExtension = os.path.splitext(exportFilename)
            fileExtension = fileExtension.lstrip('.')

            go.Figure(fig).write_json(tmpFile)
            cmd = [orcaBin, 'graph', tmpFile, '--output-dir', exportDir, '--output', exportFilename, '--format', fileExtension, '--mathjax', 'https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.5/MathJax.js']
            if width is not None:
                cmd.extend(['--width', f'{width}'])
            if height is not None:
                cmd.extend(['--height', f'{height}'])
            subprocess.run(cmd, check=True)
        finally:
            os.remove(tmpFile)
        if autoOpen:
            openFile(exportFile)


def exportInternal(fig, width, height, exportFile, autoOpen=False):
    import plotly
    import plotly.graph_objects as go
    if exportFile.endswith('.html'):
        plotly.offline.plot(fig, filename=exportFile, auto_open=autoOpen)
        return
    else:
        global orcaBin
        if orcaBin is None:
            determineOrca()
        plotly.io.orca.config.executable = orcaBin
        go.Figure(fig).write_image(exportFile, width=width, height=height)
        if autoOpen:
            openFile(exportFile)
