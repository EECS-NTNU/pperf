#!/usr/bin/env python

import plotly
import plotly.graph_objects as go
import os
import subprocess
import tempfile

orca = 'orca'
orcaArgs = ['--mathjax', 'https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.5/MathJax.js']

if os.path.exists('/opt/plotly-orca/orca'):
    orca = '/opt/plotly-orca/orca'
    plotly.io.orca.config.executable = '/opt/plotly-orca/orca'


def exportFigure(fig, width, height, exportFile):
    tmpFd, tmpFile = tempfile.mkstemp()
    try:
        exportFile = os.path.abspath(exportFile)
        exportDir = os.path.dirname(exportFile)
        exportFilename = os.path.basename(exportFile)
        _, fileExtension = os.path.splitext(exportFilename)
        fileExtension = fileExtension.lstrip('.')
        go.Figure(fig).write_json(tmpFile)

        cmd = [orca]
        cmd.extend(['graph', tmpFile, '--output-dir', exportDir, '--output', exportFilename, '--format', fileExtension])
        if width is not None:
            cmd.extend(['--width', f'{width}'])
        if height is not None:
            cmd.extend(['--height', f'{height}'])
        cmd.extend(orcaArgs)
        subprocess.run(cmd, check=True)
    finally:
        os.remove(tmpFile)
    pass


def exportInternal(fig, width, height, exportFile):
    go.Figure(fig).write_image(exportFile, width=width, height=height)
