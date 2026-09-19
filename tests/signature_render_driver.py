#!/usr/bin/env python3
"""Render shared vector layers to native fixed-colour pixels, without vendor code.

Separate transparent layers give exact foreground colours and thresholded coverage;
this bounds native RLE size without changing executable code or image allocation.
Panel rendering retains normal browser vector antialiasing.
"""
import argparse,hashlib,json,sys,xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from build_signature_brand import native,NS
from inspect_psplash_image import encode_rle,decode_rle
from PIL import Image
from PyQt5.QtCore import QByteArray,QT_VERSION_STR
from PyQt5.QtGui import QImage,QPainter,QGuiApplication
from PyQt5.QtSvg import QSvgRenderer

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    app=QGuiApplication([]);raw=Path(a.source).read_bytes();data=native(raw).encode();result=Image.new('RGBA',(1280,720),(0,0,0,255))
    colours=['#ffffff','#696969','#e58b38','#777777']
    for index,colour in enumerate(colours):
        tree=ET.fromstring(data);tree.remove(tree.find('{'+NS+'}rect'));group=tree.find('{'+NS+'}g')
        for i,child in enumerate(list(group)):
            if i!=index:group.remove(child)
        image=QImage(1280,720,QImage.Format_RGBA8888);image.fill(0)
        renderer=QSvgRenderer(QByteArray(ET.tostring(tree)));painter=QPainter(image);painter.setRenderHint(QPainter.Antialiasing,True);renderer.render(painter);painter.end()
        layer=Image.frombytes('RGBA',(1280,720),image.bits().asstring(image.byteCount()))
        mask=layer.getchannel('A').point(lambda x:255 if x>=128 else 0)
        result=Image.composite(Image.new('RGBA',result.size,colour),result,mask)
    pixels=result.tobytes();encoded=encode_rle(pixels)
    if len(encoded)>48739:raise ValueError('Fixed native image allocation exceeded')
    assert decode_rle(encoded,1280,720)[0]==pixels
    out=Path(a.output);out.mkdir(mode=0o700);result.save(out/'signature-boot.png');(out/'signature-boot.rgba').write_bytes(pixels)
    receipt={'source_svg_sha256':hashlib.sha256(raw).hexdigest(),'native_svg_sha256':hashlib.sha256(data).hexdigest(),'rgba_sha256':hashlib.sha256(pixels).hexdigest(),'width':1280,'height':720,'scale':1.3,'rle_bytes':len(encoded),'capacity':48739,'fixed_palette':colours+['#000000'],'coverage_threshold':128,'pixel_roundtrip':True,'qt':QT_VERSION_STR,'hardware_contact':False}
    (out/'receipt.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n');print(json.dumps(receipt))
if __name__=='__main__':main()
