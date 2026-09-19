#!/usr/bin/env python3
"""Render an authored vector into exact psplash RGBA format, never vendor code."""
import argparse,hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_native_display_review import validate_svg
from PyQt5.QtCore import QByteArray,QT_VERSION_STR
from PyQt5.QtGui import QImage,QPainter,QGuiApplication
from PyQt5.QtSvg import QSvgRenderer

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--svg',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    app=QGuiApplication([])
    data=Path(a.svg).read_bytes()
    validate_svg(data)
    renderer=QSvgRenderer(QByteArray(data))
    if not renderer.isValid() or renderer.defaultSize().width()!=1280 or renderer.defaultSize().height()!=720:raise ValueError('Native canvas required')
    image=QImage(1280,720,QImage.Format_RGBA8888);image.fill(0xff000000)
    painter=QPainter(image);painter.setRenderHint(QPainter.Antialiasing,True);renderer.render(painter);painter.end()
    pixels=image.bits().asstring(image.byteCount())
    if len(pixels)!=1280*720*4:raise ValueError('Unexpected row padding')
    dest=Path(a.output);dest.mkdir(mode=0o700)
    (dest/'root-mark.rgba').write_bytes(pixels)
    if not image.save(str(dest/'root-mark.png')):raise ValueError('Preview save failed')
    report={'qt':QT_VERSION_STR,'source_svg_sha256':hashlib.sha256(data).hexdigest(),'rgba_sha256':hashlib.sha256(pixels).hexdigest(),'width':1280,'height':720,'native_execution':False,'installed':False}
    (dest/'receipt.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    print(json.dumps(report))
if __name__=='__main__':main()
