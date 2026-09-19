#!/usr/bin/env python3
"""Isolated HOST Qt smoke test; only authored QML runs, never vendor resources."""
import argparse,hashlib,json,sys
from pathlib import Path
from PyQt5.QtCore import QUrl,QByteArray,QResource,QFile,QT_VERSION_STR,QSize
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtQml import QQmlComponent,QQmlExpression,QQmlContext
from PyQt5.QtQuick import QQuickView
from PyQt5.QtTest import QTest

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fragment',required=True);p.add_argument('--output',required=True);p.add_argument('--rcc');a=p.parse_args()
    dest=Path(a.output);dest.mkdir(mode=0o700)
    app=QGuiApplication([]);view=QQuickView();engine=view.engine()
    fragment=Path(a.fragment).read_text()
    authored='''import QtQuick 2.9 as QtQuick
QtQuick.Rectangle {
    width: 1280; height: 720; color: "#080a0c"
    '''+fragment+'''
    QtQuick.Rectangle { x: 48; y: 106; width: 1184; height: 1; color: "#292e33" }
    QtQuick.Text { x: 48; y: 30; text: "Form 3"; color: "#f6f8fa"; font.pixelSize: 26 }
    QtQuick.Text { x: 48; y: 66; text: ownerClockAppend("Idle", true); color: "#b8c0c8"; font.pixelSize: 20 }
    QtQuick.Text { x: 48; y: 656; text: "LOCAL LAYOUT TEST · authored fixture · no printer connected"; color: "#8b969f"; font.pixelSize: 16 }
}
'''
    component=QQmlComponent(engine);component.setData(QByteArray(authored.encode()),QUrl('file:///authored-clock.qml'))
    if component.isError():raise ValueError('Authored QML failed to compile: '+str(component.errors()))
    root=component.create();ctx=QQmlContext(engine.rootContext());ctx.setContextObject(root)
    if root is None:raise ValueError('No authored clock object')
    # Pause only fixture timers to test fixed synthetic instants deterministically.
    for obj in root.children():
        if obj.property('interval')==1000:obj.setProperty('running',False)
    def render(epoch,status,idle):
        root.setProperty('ownerClockEpochMs',epoch)
        expression=QQmlExpression(ctx,root,'ownerClockAppend('+json.dumps(status)+','+str(idle).lower()+')')
        value,undefined=expression.evaluate()
        if undefined or expression.hasError():raise ValueError('Clock expression failure')
        return value
    checks=[]
    def check(name,condition):
        checks.append({'name':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
    check('idle Berlin local timestamp',render(1789236600000,'Idle',True)=='Idle 12.09.26 20:10')
    check('ready Berlin local timestamp',render(1789236600000,'Ready',True)=='Ready 12.09.26 20:10')
    check('busy unchanged',render(1789236600000,'Printing',False)=='Printing')
    check('unknown clock visible',render(0,'Idle',True)=='Idle time unavailable')
    check('32bit boundary unavailable',render(2208988800000,'Idle',True)=='Idle time unavailable')
    check('minute rollover',render(1789236659000,'Idle',True)!=render(1789236660000,'Idle',True))
    resource=None
    if a.rcc:
        # Qt loads resource bytes; no vendor QML component is instantiated.
        check('Qt accepts rebuilt RCC',QResource.registerResource(a.rcc))
        f=QFile(':/qml/BaseScreen.qml');check('BaseScreen readable through Qt',f.open(QFile.ReadOnly))
        data=bytes(f.readAll());f.close()
        check('Qt sees authored clock',b'ownerClockAppend' in data)
        resource={'source_sha256':hashlib.sha256(Path(a.rcc).read_bytes()).hexdigest(),'BaseScreen_sha256':hashlib.sha256(data).hexdigest(),'vendor_QML_executed':False}
        QResource.unregisterResource(a.rcc)
    render(1789236600000,'Idle',True);view.setContent(QUrl(),component,root)
    view.resize(1280,720);view.show();view.requestUpdate();QTest.qWait(300)
    grab=root.grabToImage(QSize(1280,720))
    for unused in range(50):
        if not grab.image().isNull():break
        QTest.qWait(20)
    frame=grab.image();check('offscreen layout image',not frame.isNull())
    check('save screenshot',frame.save(str(dest/'idle-clock-layout.png')))
    receipt={'qt_version':QT_VERSION_STR,'execution':'HOST Qt authored fixture only','checks':checks,'target_Qt_5_9_proven':False,'resource':resource,'fragment_sha256':hashlib.sha256(fragment.encode()).hexdigest(),'external_network':False}
    (dest/'receipt.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
    print(json.dumps({'checks':len(checks),'passed':True,'qt':QT_VERSION_STR,'target_execution':False}))
if __name__=='__main__':main()
