#!/usr/bin/env python

import plotly.graph_objects as go
import os
import subprocess
import tempfile
import shutil

defaultOrca = ['/opt/plotly-orca/orca', '/opt/plotly/orca', '/opt/orca/orca', '/usr/bin/orca', 'orca']

orcaBin = os.getenv('PLOTLY_ORCA')
orcaArgs = ['--mathjax', 'https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.5/MathJax.js']

if orcaBin is None:
    for executable in defaultOrca:
        orcaBin = shutil.which(executable)
        if orcaBin is not None:
            break
else:
    orcaBin = shutil.which(orcaBin)

if orcaBin is None:
    raise Exception('Could not find orca!')


def exportFigure(fig, width, height, exportFile):
    tmpFd, tmpFile = tempfile.mkstemp()
    try:
        exportFile = os.path.abspath(exportFile)
        exportDir = os.path.dirname(exportFile)
        exportFilename = os.path.basename(exportFile)
        _, fileExtension = os.path.splitext(exportFilename)
        fileExtension = fileExtension.lstrip('.')
        go.Figure(fig).write_json(tmpFile)

        cmd = [orcaBin]
        cmd.extend(['graph', tmpFile, '--output-dir', exportDir, '--output', exportFilename, '--format', fileExtension])
        if width is not None:
            cmd.extend(['--width', f'{width}'])
        if height is not None:
            cmd.extend(['--height', f'{height}'])
        cmd.extend(orcaArgs)
        subprocess.run(cmd, check=True)
    finally:
        os.remove(tmpFile)


def exportInternal(fig, width, height, exportFile):
    plotly.io.orca.config.executable = orcaBin
    go.Figure(fig).write_image(exportFile, width=width, height=height)
